"""
Extractor: walks a Python source file's AST and produces an ir.Program.

Scope (matches b1/b3/b4/b6/b7 + real-world asyncio repo patterns):
  - asyncio.Lock / asyncio.Queue / asyncio.LifoQueue / asyncio.Event objects,
    found via assignment tracking (`x = asyncio.Lock()`, `self.x = ...`).
  - `async with lock:` blocks -> ACQUIRE/RELEASE pair.
  - `await lock.acquire()` / `lock.release()` -> ACQUIRE/RELEASE.
  - `await q.get()` -> Q_GET ; `q.put_nowait(v)` / `await q.put(v)` -> Q_PUT.
  - `await ev.wait()` -> EV_WAIT ; `ev.set()` -> EV_SET.
  - `await asyncio.wait_for(...)` / `await compat.wait_for(...)` (bare await
    or `return await ...`) -> recorded in Program.wait_for_sites, along with
    whether a same-scope except/finally cleanup handler was found.

Anything else awaited is recorded as GENERIC_AWAIT (not modeled precisely,
but kept so the encoder / user can see what was skipped).

SCOPING (the fix for the name-conflation issue found on real corpus code):
`self.attr = asyncio.Lock()` is resolved PER ENCLOSING CLASS, not globally by
attribute name. redis-py's `connection.py`, for example, has three unrelated
classes each with their own `self._lock = asyncio.Lock()` -- these are now
tracked as three distinct sync objects (keyed by class-qualified name), not
conflated into one. A bare module-level `x = asyncio.Lock()` (no enclosing
function) remains a single shared object visible to every coroutine in the
file, as it should be. A local variable inside a function body (not a
`self.attr`) is scoped to that function, so two sibling functions using the
same local variable name for genuinely different Lock() instances are also
kept separate.

This is a pattern extractor, not a full points-to analysis: it does not
handle locks passed as function arguments, stored in containers, or built
via a factory/indirection.
"""

import ast
from ir import Program, OpKind, SyncKind


CONSTRUCTOR_KIND = {
    "Lock": SyncKind.LOCK,
    "Queue": SyncKind.QUEUE,
    "LifoQueue": SyncKind.QUEUE,
    "PriorityQueue": SyncKind.QUEUE,
    "Event": SyncKind.EVENT,
}

# Only these module prefixes are accepted as "this really is asyncio's
# primitive" -- matching on short class name alone (the previous
# behavior) silently accepted trio.Event(), threading.Lock(), and any
# other same-named-but-differently-behaved class from an unrelated
# concurrency model. Confirmed as a real issue during manual corpus
# verification: websockets/trio/connection.py's `trio.Event()` was being
# analyzed as if it were asyncio.Event(), applying SNF's asyncio-
# scheduler-specific structured encoding to a primitive this pipeline was
# never validated against. `compat` is included because real repos (e.g.
# asyncpg) use a `compat` shim module that re-exports asyncio-compatible
# primitives under that name.
ACCEPTED_MODULE_PREFIXES = ("asyncio", "compat")


def _is_recognized_constructor_call(fn_name):
    """Returns (is_recognized, short_class_name). A bare name (no module
    prefix, e.g. `from asyncio import Lock; Lock()`) is accepted, since
    there's no prefix to check and this is overwhelmingly the common case
    for direct imports. A dotted name is only accepted if its immediate
    prefix is asyncio/compat -- `trio.Event()`, `threading.Lock()`,
    `multiprocessing.Lock()`, etc. are explicitly excluded."""
    parts = fn_name.split(".")
    short = parts[-1]
    if short not in CONSTRUCTOR_KIND:
        return False, None
    if len(parts) == 1:
        return True, short
    prefix = parts[-2]
    if prefix in ACCEPTED_MODULE_PREFIXES:
        return True, short
    return False, None

MODULE_SCOPE = ("module",)


def _name_of(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name_of(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


class ScopeTracker(ast.NodeVisitor):
    """Walks the whole tree once, recording, for every node, which
    (class_scope, function_scope) it's lexically inside. class_scope is a
    dotted path of enclosing ClassDefs (e.g. "Outer.Inner"), or None if not
    inside any class. function_scope is a dotted path including the
    innermost enclosing function/method (e.g. "Outer.Inner.method" or
    "free_function"), or None if at true module level.

    Results are stored keyed by id(node) in self.node_scope, since ast nodes
    aren't hashable-by-value but id() is stable for the lifetime of the tree.
    """

    def __init__(self):
        self.class_stack = []
        self.func_stack = []
        self.node_scope = {}  # id(node) -> (class_scope, function_scope)

    def _record(self, node):
        class_scope = ".".join(self.class_stack) if self.class_stack else None
        function_scope = ".".join(self.class_stack + self.func_stack) if self.func_stack else None
        self.node_scope[id(node)] = (class_scope, function_scope)

    def visit_ClassDef(self, node):
        self._record(node)
        self.class_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self.class_stack.pop()

    def _visit_func(self, node):
        self._record(node)
        self.func_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self.func_stack.pop()

    def visit_FunctionDef(self, node):
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_func(node)

    def generic_visit(self, node):
        self._record(node)
        super().generic_visit(node)

    def scope_of(self, node):
        return self.node_scope.get(id(node), (None, None))


import re as _re
_SYNC_NAME_RE = _re.compile(r"(lock|queue|event|mutex|sem(aphore)?|cond(ition)?)", _re.IGNORECASE)


class SymbolTableBuilder(ast.NodeVisitor):
    """Finds `x = asyncio.Lock()`-style constructor assignments anywhere in
    the module, and resolves each to a scope key:
      - `self.attr` / `cls.attr` target  -> ("class", <enclosing class path>, attr)
      - plain `name` target inside a function -> ("function", <enclosing function path>, name)
      - plain `name` target at true module level -> MODULE_SCOPE + (name,)

    Also collects `unresolved_refs`: assignments like `self.lock = lock` (a
    bare Name, not a constructor call) whose target name LOOKS sync-like
    (matches _SYNC_NAME_RE) -- these are typically locks/queues/events
    passed into __init__ as a parameter, or otherwise built elsewhere. They
    can't be resolved to a SyncKind by this pass, but are surfaced instead
    of silently vanishing.
    """

    def __init__(self, scopes: ScopeTracker):
        self.scopes = scopes
        self.symbols = {}  # scope_key tuple -> SyncKind
        self.unresolved_refs = []  # list[dict]
        self.task_refs = {}  # (class_scope, attr) -> callee_name, for ANY
                              # self.attr = some_call(...) assignment --
                              # used to resolve `wait_for(self.attr, ...)`
                              # back to whatever function/task created it,
                              # regardless of whether that call is a
                              # Lock/Queue/Event constructor.

    def visit_Assign(self, node):
        call = node.value
        if isinstance(call, ast.Call):
            fn_name = _name_of(call.func)
            if fn_name:
                recognized, short = _is_recognized_constructor_call(fn_name)
                if recognized:
                    class_scope, function_scope = self.scopes.scope_of(node)
                    for target in node.targets:
                        self._record_target(target, class_scope, function_scope,
                                             CONSTRUCTOR_KIND[short])
                    self.generic_visit(node)
                    return
            # Any self.attr = <call>(...) -- record for wait_for resolution
            # even if it's not a recognized sync-object constructor.
            class_scope, _ = self.scopes.scope_of(node)
            callee_name = call.func.attr if isinstance(call.func, ast.Attribute) else (
                call.func.id if isinstance(call.func, ast.Name) else None)
            if callee_name:
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                            and target.value.id in ("self", "cls"):
                        self.task_refs[(class_scope, target.attr)] = callee_name
        # Not a recognized constructor call -- check for the "passed in"
        # shape: self.attr = <bare name>, where attr looks sync-like.
        if isinstance(call, ast.Name):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                        and target.value.id in ("self", "cls") \
                        and _SYNC_NAME_RE.search(target.attr):
                    class_scope, _ = self.scopes.scope_of(node)
                    self.unresolved_refs.append({
                        "attr": target.attr,
                        "class_scope": class_scope,
                        "source_name": call.id,
                        "line": node.lineno,
                        "reason": "assigned from a bare name (likely a constructor "
                                  "parameter or externally-built object), not a "
                                  "recognized asyncio.Lock/Queue/Event() call",
                    })
        self.generic_visit(node)

    def _record_target(self, target, class_scope, function_scope, kind):
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                and target.value.id in ("self", "cls"):
            attr = target.attr
            if class_scope is not None:
                key = ("class", class_scope, attr)
            else:
                # self.attr with no enclosing class (unusual) -- fall back
                # to function scope, then module.
                key = ("function", function_scope, attr) if function_scope else MODULE_SCOPE + (attr,)
            self.symbols[key] = kind
        elif isinstance(target, ast.Name):
            name = target.id
            if function_scope is not None:
                key = ("function", function_scope, name)
            else:
                key = MODULE_SCOPE + (name,)
            self.symbols[key] = kind


class CoroutineExtractor(ast.NodeVisitor):
    def __init__(self, program: Program, symbols: dict, scopes: ScopeTracker):
        self.program = program
        self.symbols = symbols
        self.scopes = scopes
        self.current_coro = None
        self.current_class_scope = None
        self.current_function_scope = None
        self.current_func_node = None
        self.current_is_async = True
        self.seq_counter = 0
        self._seen_wait_for_ids = set()
        self._visited_func_ids = set()

    def _display_name(self, kind_tag, scope_parts, short):
        # Build a human-readable, still-unique object name for the Program's
        # sync_objects dict, e.g. "ClassName._lock" instead of bare "_lock",
        # so distinct classes' locks don't collide in output either.
        if kind_tag == "class":
            return f"{scope_parts}.{short}"
        if kind_tag == "function":
            return f"{scope_parts}::{short}"
        return short  # module scope: bare name is already globally unique

    def _resolve_sync(self, name_node):
        name = _name_of(name_node)
        if not name:
            return None
        short = name.split(".")[-1]
        is_self_attr = name.startswith("self.") or name.startswith("cls.")

        if is_self_attr and self.current_class_scope is not None:
            key = ("class", self.current_class_scope, short)
            if key in self.symbols:
                disp = self._display_name("class", self.current_class_scope, short)
                self.program.add_sync(disp, self.symbols[key])
                return disp

        if self.current_function_scope is not None:
            # Closure resolution: try the most specific scope first, then
            # progressively strip the innermost dotted segment to check
            # each enclosing function, matching real Python closure
            # semantics (a nested function can see its enclosing
            # function's locals).
            scope = self.current_function_scope
            while scope:
                key = ("function", scope, short)
                if key in self.symbols:
                    disp = self._display_name("function", scope, short)
                    self.program.add_sync(disp, self.symbols[key])
                    return disp
                if "." in scope:
                    scope = scope.rsplit(".", 1)[0]
                else:
                    break

        key = MODULE_SCOPE + (short,)
        if key in self.symbols:
            self.program.add_sync(short, self.symbols[key])
            return short

        return None

    def _emit(self, kind, sync_name, line, note=""):
        self.seq_counter += 1
        coro = self.program.coro(self.current_coro)
        coro.ops.append(
            __import__("ir").Op(kind=kind, sync_obj=sync_name or "",
                                 coro=self.current_coro, seq=self.seq_counter,
                                 line=line, note=note)
        )

    def visit_AsyncFunctionDef(self, node):
        self._visit_function_common(node, is_async=True)

    def visit_FunctionDef(self, node):
        """Plain `def` methods are visited too (not just `async def`).
        This matters because Event.set()/clear(), Lock.release(), and
        Queue.put_nowait() are all SYNCHRONOUS asyncio methods -- no
        `await` required -- and it's completely normal for them to be
        called from a plain `def`, most commonly asyncio Protocol
        callback methods (`data_received`, `pause_writing`,
        `resume_writing`, etc.), which asyncio always calls synchronously
        by design, never as coroutines. Confirmed as a real, systematic
        false-negative source via manual corpus verification: aiosonic's
        `Http2Handler._on_window_updated` and sanic's `SanicProtocol`'s
        writer-pause/data-received callbacks all call `.set()` from a
        plain `def`, which was invisible to the old async-only traversal
        -- undercounting `num_sets`/etc. to 0 and leaving the wake
        guarantee unconstrained in the structured encoding, producing a
        spurious `sat` (both-sat) result on real code across 3 separate
        real-world objects in one corpus sweep.

        ACQUIRE/Q_GET/EV_WAIT/wait_for are NOT emitted from a plain def
        (see _visit_function_common's is_async gating) -- those all
        require `await`, which is a SyntaxError outside `async def`, so
        there's nothing legitimate to model there; any such call sitting
        in a plain def in real code would be a no-op bug in the target
        code itself (calling `.acquire()` without awaiting it discards
        the coroutine object without ever running it), not something this
        tool should treat as real synchronization."""
        self._visit_function_common(node, is_async=False)

    def _visit_function_common(self, node, is_async):
        if id(node) in self._visited_func_ids:
            return  # already processed via an enclosing function's own
                     # body traversal -- prevents double-counting ops for
                     # nested defs (e.g. workers nested inside a
                     # benchmark function, or asyncpg's _acquire_impl
                     # nested inside _acquire)
        self._visited_func_ids.add(id(node))
        prev_coro = self.current_coro
        prev_class = self.current_class_scope
        prev_func = self.current_function_scope
        prev_node = self.current_func_node
        prev_is_async = self.current_is_async
        self.current_coro = node.name
        enclosing_class_scope, enclosing_function_scope = self.scopes.scope_of(node)
        # The scope FOR STATEMENTS INSIDE this function's body is its own
        # name appended to whatever it's enclosed in -- NOT the same as
        # scope_of(node), which gives the scope the function itself lives
        # in (its enclosing context). Conflating the two meant a bare
        # outer-function-level call (e.g. event.set() in the same
        # function that declared event = asyncio.Event()) would resolve
        # to function_scope=None instead of the outer function's own
        # name, failing to match the symbol table entry for `event`.
        self.current_class_scope = enclosing_class_scope
        self.current_function_scope = (
            f"{enclosing_function_scope}.{node.name}" if enclosing_function_scope else node.name
        )
        self.current_func_node = node
        self.current_is_async = is_async
        self.program.coro(node.name)
        for stmt in node.body:
            self.visit(stmt)
        self.current_coro = prev_coro
        self.current_class_scope = prev_class
        self.current_function_scope = prev_func
        self.current_func_node = prev_node
        self.current_is_async = prev_is_async

    def visit_AsyncWith(self, node):
        acquired = []
        for item in node.items:
            ctx = item.context_expr
            call_target = ctx.func if isinstance(ctx, ast.Call) else ctx
            sync_name = self._resolve_sync(call_target)
            if sync_name and self.program.sync_objects.get(sync_name) == __import__("ir").SyncKind.LOCK:
                self._emit(OpKind.ACQUIRE, sync_name, node.lineno, "async with")
                acquired.append(sync_name)
        for stmt in node.body:
            self.visit(stmt)
        for sync_name in acquired:
            self._emit(OpKind.RELEASE, sync_name, node.lineno, "end async with")

    def visit_With(self, node):
        """No visit_With existed before this fix, so a `with
        contextlib.suppress(...):` directly wrapping a `wait_for(...)` call
        (not nested inside a try/except -- contextlib.suppress used this way
        REPLACES try/except, it doesn't sit inside one) fell through to the
        generic bare-call path, which unconditionally marks
        handled_locally=False. That path is exactly the common
        `with contextlib.suppress(asyncio.TimeoutError): await wait_for(...)`
        idiom the README documents as recognized -- it wasn't, because
        nothing here ever checked a With node the way visit_Try checks a Try
        node. Mirrors visit_Try's structure: a wait_for call directly inside
        a suppress-with is handled_locally=True, since the suppress itself
        catching the TimeoutError there is the handling mechanism."""
        if _is_suppress_with(node):
            wf_call = _contains_wait_for_call(node)
            if wf_call is not None and id(wf_call) not in self._seen_wait_for_ids:
                self.program.wait_for_sites.append({
                    "coro": self.current_coro,
                    "line": wf_call.lineno,
                    "handled_locally": True,
                    "callee": _wait_for_callee_name(wf_call, self.current_func_node, self.program.task_refs, self.current_class_scope),
                })
                self._seen_wait_for_ids.add(id(wf_call))
        self.generic_visit(node)

    def visit_Try(self, node):
        wf_call = _contains_wait_for_call(node)
        if wf_call is not None:
            handled = _try_has_cleanup_handler(node)
            self.program.wait_for_sites.append({
                "coro": self.current_coro,
                "line": wf_call.lineno,
                "handled_locally": handled,
                "callee": _wait_for_callee_name(wf_call, self.current_func_node, self.program.task_refs, self.current_class_scope),
            })
            self._seen_wait_for_ids.add(id(wf_call))
        self.generic_visit(node)

    def visit_Expr(self, node):
        self._handle_call_expr(node.value, node.lineno)
        self.generic_visit(node)

    def visit_Assign(self, node):
        self._handle_call_expr(node.value, node.lineno)
        self.generic_visit(node)

    def visit_Return(self, node):
        if node.value is not None:
            self._handle_call_expr(node.value, node.lineno)
        self.generic_visit(node)

    def _handle_call_expr(self, value, lineno):
        call = value.value if isinstance(value, ast.Await) else value
        if not isinstance(call, ast.Call):
            return
        fname = call.func.attr if isinstance(call.func, ast.Attribute) else (
            call.func.id if isinstance(call.func, ast.Name) else None)
        is_await = isinstance(value, ast.Await)

        if fname == "wait_for" and is_await and _is_true_wait_for_call(call):
            if id(call) not in self._seen_wait_for_ids:
                self._seen_wait_for_ids.add(id(call))
                self.program.wait_for_sites.append({
                    "coro": self.current_coro, "line": lineno,
                    "handled_locally": False,
                    "callee": _wait_for_callee_name(call, self.current_func_node, self.program.task_refs, self.current_class_scope),
                })
            return

        if not isinstance(call.func, ast.Attribute):
            # Bare name call, e.g. `await _acquire_impl()` -- previously
            # silently dropped entirely (not even GENERIC_AWAIT). Now
            # recorded so it's visible in the audit trail AND resolvable
            # as a callee for call-chain analysis (multiplicity
            # propagation, wait_for resolution).
            if is_await and isinstance(call.func, ast.Name):
                self._emit(OpKind.GENERIC_AWAIT, None, lineno, f".{call.func.id}()")
            return
        method = call.func.attr
        sync_name = self._resolve_sync(call.func.value)

        if sync_name is None:
            if is_await:
                self._emit(OpKind.GENERIC_AWAIT, None, lineno, f".{method}()")
            return

        kind = self.program.sync_objects[sync_name]
        if kind == __import__("ir").SyncKind.LOCK:
            if method == "acquire" and self.current_is_async:
                self._emit(OpKind.ACQUIRE, sync_name, lineno)
            elif method == "release":
                self._emit(OpKind.RELEASE, sync_name, lineno)
        elif kind == __import__("ir").SyncKind.QUEUE:
            if method == "get" and self.current_is_async:
                self._emit(OpKind.Q_GET, sync_name, lineno)
            elif method == "put_nowait":
                self._emit(OpKind.Q_PUT, sync_name, lineno)
            elif method == "put" and self.current_is_async:
                self._emit(OpKind.Q_PUT, sync_name, lineno)
        elif kind == __import__("ir").SyncKind.EVENT:
            if method == "wait" and self.current_is_async:
                self._emit(OpKind.EV_WAIT, sync_name, lineno)
            elif method == "set":
                self._emit(OpKind.EV_SET, sync_name, lineno)


def _wait_for_callee_name(wf_call, enclosing_func_node=None, task_refs=None, class_scope=None):
    """For `wait_for(callee_expr, timeout=...)`, return the function/method
    name of callee_expr if it's itself a call (e.g. `_acquire_impl()` ->
    "_acquire_impl"), else None.

    Also handles the indirect shape `coro = callee_expr(); ... ;
    wait_for(coro, timeout=...)` -- if arg0 is a bare Name, search backward
    through the enclosing function's own statement list (not a full
    dataflow analysis, just "last simple assignment to this name in this
    function") for `name = some_call(...)` and resolve THAT call's name
    instead."""
    if not wf_call.args:
        return None
    arg0 = wf_call.args[0]
    if isinstance(arg0, ast.Call):
        if isinstance(arg0.func, ast.Name):
            return arg0.func.id
        if isinstance(arg0.func, ast.Attribute):
            return arg0.func.attr
    if isinstance(arg0, ast.Name) and enclosing_func_node is not None:
        target_name = arg0.id
        found = None
        for n in ast.walk(enclosing_func_node):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == target_name:
                        if isinstance(n.value.func, ast.Name):
                            found = n.value.func.id
                        elif isinstance(n.value.func, ast.Attribute):
                            found = n.value.func.attr
        if found:
            return found
    # self.attr / cls.attr receiver -- look up what created it via the
    # class-scoped task_refs map (typically populated from __init__,
    # a different function than the one containing this wait_for call).
    if isinstance(arg0, ast.Attribute) and isinstance(arg0.value, ast.Name) \
            and arg0.value.id in ("self", "cls") and task_refs is not None:
        return task_refs.get((class_scope, arg0.attr))
    return None


def _function_has_cleanup_handler(func_node):
    """Does this function/method contain ANY try/except or try/finally
    whose handler performs a put_nowait/put/release-shaped cleanup call,
    OR any standalone contextlib.suppress(...) with-block -- used on its
    own as a try/except replacement, not just nested inside one --
    anywhere in its body (not just wrapping a wait_for)?"""
    for n in ast.walk(func_node):
        if isinstance(n, ast.Try):
            if _try_has_cleanup_handler(n):
                return True
        if isinstance(n, (ast.With, ast.AsyncWith)):
            if _is_suppress_with(n):
                return True
    return False


def _is_suppress_with(with_node):
    """True if this With/AsyncWith's context expression is
    contextlib.suppress(...) / suppress(...). contextlib.suppress used as a
    with-statement IS the handler mechanism -- it replaces try/except
    entirely rather than nesting inside one, so this must be checked
    independently of _try_has_cleanup_handler, which only ever fires from
    inside an ast.Try node and can never see a standalone suppress block."""
    for item in with_node.items:
        ctx = item.context_expr
        fn = ctx.func if isinstance(ctx, ast.Call) else ctx
        fname = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else None)
        if fname == "suppress":
            return True
    return False


def _is_true_wait_for_call(n):
    """True only for `wait_for(...)` (bare name) or `X.wait_for(...)` where
    X is itself a simple Name (e.g. `asyncio.wait_for`, `compat.wait_for`).
    Deliberately excludes `self._condition.wait_for(predicate)` --
    asyncio.Condition.wait_for is a completely different primitive (a
    predicate-wait loop, not a timeout race) that happens to share the
    method name. The receiver there is an Attribute (`self._condition`),
    not a bare Name, which is exactly the distinguishing signal."""
    if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "wait_for"):
        return isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "wait_for"
    return isinstance(n.func.value, ast.Name)


def _contains_wait_for_call(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and _is_true_wait_for_call(n):
            return n
    return None


CLEANUP_CALL_NAMES = (
    "put_nowait", "put", "release", "cancel", "close", "discard",
    "set", "clear", "reset", "disconnect",
    # broadened for limitation #4: additional exact verbs seen in real
    # cleanup/requeue/teardown paths that weren't covered before.
    "abort", "rollback", "shutdown", "terminate", "requeue", "unlock",
    "free", "dispose", "giveback", "recycle",
)

# Fuzzy, LOW-CONFIDENCE stems for a secondary, clearly-labeled hint only --
# never flips handled_locally to True by itself (too imprecise for that),
# but surfaced in wait_for site resolution text so a human reviewer knows
# to look closer instead of the tool silently saying "no handler found"
# when something cleanup-shaped, just not exactly-matched, is actually
# right there.
CLEANUP_FUZZY_STEMS = (
    "clean", "teardown", "revert", "restore", "invalidate", "expire",
)


def _find_fuzzy_handler_hint(node):
    """Scan for any call whose method name CONTAINS (case-insensitive) one
    of CLEANUP_FUZZY_STEMS but doesn't exactly match CLEANUP_CALL_NAMES.
    Returns the first such call's method name, or None. This is a hint for
    manual review, not a detection result -- see CLEANUP_FUZZY_STEMS."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            attr_lower = n.func.attr.lower()
            if attr_lower in CLEANUP_CALL_NAMES:
                continue
            for stem in CLEANUP_FUZZY_STEMS:
                if stem in attr_lower:
                    return n.func.attr
    return None


def _try_has_cleanup_handler(try_node):
    """Recursively scans except/finally bodies (including nested
    try/except inside them, and contextlib.suppress(...) blocks) for a
    cleanup-shaped call. Broader than a single flat pass: any call whose
    method name is in CLEANUP_CALL_NAMES anywhere inside the handler
    counts, not just at the top level of the handler body."""
    handlers = list(try_node.handlers) + ([try_node.finalbody] if try_node.finalbody else [])
    flat_stmts = []
    for h in handlers:
        if isinstance(h, list):
            flat_stmts.extend(h)
        else:
            flat_stmts.extend(h.body)
    for stmt in flat_stmts:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                if n.func.attr in CLEANUP_CALL_NAMES:
                    return True
            # contextlib.suppress(...) / suppress(...) as an async/with context
            # manager counts as an intentional cleanup-suppression idiom.
            if isinstance(n, (ast.With, ast.AsyncWith)):
                for item in n.items:
                    ctx = item.context_expr
                    fn = ctx.func if isinstance(ctx, ast.Call) else ctx
                    fname = fn.attr if isinstance(fn, ast.Attribute) else (
                        fn.id if isinstance(fn, ast.Name) else None)
                    if fname == "suppress":
                        return True
    return False


SPAWN_FUNC_NAMES = ("create_task", "ensure_future")


def _callee_name_of_call(call_node):
    """Best-effort function/method name a Call node invokes, e.g.
    `producer(0, 4)` -> "producer", `self._drain()` -> "_drain"."""
    if isinstance(call_node.func, ast.Name):
        return call_node.func.id
    if isinstance(call_node.func, ast.Attribute):
        return call_node.func.attr
    return None


def _find_spawn_targets(tree):
    """Detect coroutines spawned as concurrent tasks, and return a dict
    coro_name -> total_multiplicity (>=1; only entries with >=2 are
    interesting, meaning "detected as spawned concurrently").

    Three source patterns recognized:
      1. `asyncio.create_task(FN(...))` / `asyncio.ensure_future(FN(...))`
         as a direct call, OUTSIDE any loop/comprehension -- contributes
         +1 (one concrete concurrent instance per distinct call site).
      2. The same call pattern INSIDE a `for` loop, or inside a list/
         generator/set comprehension -- contributes +2. We don't try to
         evaluate the loop/range bound; detecting "this runs in a loop at
         all" is sufficient to prove/disprove a PAIRWISE mutual-exclusion
         property, since if a violation is possible for ANY two
         concurrent instances, two instances already exhibit it.
      3. `asyncio.gather(FN(...), FN(...), ...)` with the same FN
         appearing more than once as a direct argument -- contributes +1
         per occurrence.

    This only sees spawning that happens WITHIN THE FILE being analyzed --
    a coroutine spawned concurrently by external/library-consumer code is
    invisible to this detector. See pipeline.py's
    --assume-public-concurrent for that separate, explicitly-opt-in case.
    """
    multiplicity = {}

    def _bump(name, amount):
        if name:
            multiplicity[name] = multiplicity.get(name, 0) + amount

    def walk(node, in_loop):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While,
                              ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp)):
            for child in ast.iter_child_nodes(node):
                walk(child, True)
            return
        if isinstance(node, ast.Call):
            fname = _callee_name_of_call(node)
            if fname in SPAWN_FUNC_NAMES and node.args:
                inner = node.args[0]
                if isinstance(inner, ast.Call):
                    target = _callee_name_of_call(inner)
                    _bump(target, 2 if in_loop else 1)
            elif fname == "gather":
                seen_here = {}
                for arg in node.args:
                    if isinstance(arg, ast.Call):
                        target = _callee_name_of_call(arg)
                        if target:
                            seen_here[target] = seen_here.get(target, 0) + 1
                for target, count in seen_here.items():
                    if count >= 2:
                        _bump(target, count)
        for child in ast.iter_child_nodes(node):
            walk(child, in_loop)

    walk(tree, False)
    return multiplicity


def _find_coro_name_collisions(tree, scopes):
    """LIMITATION #9 detector, not a fix: Program.coroutines (and every
    bare-name-based cross-referencing mechanism -- wait_for call-chain
    resolution, spawn-multiplicity detection, --assume-public-concurrent
    propagation) all key coroutines by their bare function/method name,
    not a class-qualified one. Two DIFFERENT classes defining a method
    with the same name would have their ops silently merged into one
    bucket by encoder.py's site-counting.

    A full fix requires reconciling every one of those bare-name-based
    mechanisms with class-qualified identity simultaneously (a
    substantially larger change than fixing this in isolation, since
    `self._foo()` in the AST only ever gives you the bare name "foo" --
    knowing which class `self` refers to at that call site requires real
    points-to analysis, not just scope tracking). Deferred as a larger,
    separate undertaking; this function instead DETECTS the collision and
    surfaces it, so it's visible and can be manually checked rather than
    silently causing merged results, exactly like inspect_gaps.py already
    does for sync-object constructor collisions.
    """
    by_name = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            class_scope, _ = scopes.scope_of(node)
            by_name.setdefault(node.name, set()).add(class_scope)

    collisions = {}
    for name, class_scopes in by_name.items():
        if len(class_scopes) > 1:
            collisions[name] = sorted(
                (cs if cs is not None else "(module level)") for cs in class_scopes
            )
    return collisions


def extract(source: str, coroutine_names=None) -> Program:
    """Parse `source`, return a Program. If coroutine_names is given, restrict
    extraction to those async def names (useful for pulling one function out
    of a large real-world file)."""
    tree = ast.parse(source)

    scopes = ScopeTracker()
    scopes.visit(tree)

    sym_builder = SymbolTableBuilder(scopes)
    sym_builder.visit(tree)

    program = Program()
    program.unresolved_refs = sym_builder.unresolved_refs
    program.task_refs = sym_builder.task_refs
    program.spawn_multiplicity = _find_spawn_targets(tree)
    _raw_coro_name_collisions = _find_coro_name_collisions(tree, scopes)
    extractor = CoroutineExtractor(program, sym_builder.symbols, scopes)

    all_funcs = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            if coroutine_names is None or node.name in coroutine_names:
                extractor.visit_AsyncFunctionDef(node)
        elif isinstance(node, ast.FunctionDef):
            if coroutine_names is None or node.name in coroutine_names:
                extractor.visit_FunctionDef(node)

    # Multi-hop interprocedural resolution (same file only, depth-limited
    # to avoid pathological recursion): if a wait_for site wasn't handled
    # in its own scope, walk the call chain -- does the function it awaits
    # have a handler? If not, does THAT function's own awaited callee have
    # one? Etc, up to MAX_HOPS. This is exactly the asyncpg
    # `_acquire` -> `_acquire_impl` shape, generalized to longer chains.
    # Cross-file callees (imported from another module) still can't be
    # resolved -- those are labeled explicitly rather than silently
    # counted as "no handler".
    MAX_HOPS = 5

    def _resolve_chain(callee_name, seen):
        if not callee_name or callee_name in seen:
            return None, "cycle or dead end"
        seen = seen | {callee_name}
        if callee_name not in all_funcs:
            return None, f"callee '{callee_name}' not in this file"
        fn = all_funcs[callee_name]
        if _function_has_cleanup_handler(fn):
            return callee_name, None
        # look for a further wait_for/await-of-a-call inside this callee
        # to keep walking the chain.
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                inner_name = None
                if isinstance(n.func, ast.Name):
                    inner_name = n.func.id
                elif isinstance(n.func, ast.Attribute):
                    inner_name = n.func.attr
                if inner_name and inner_name != callee_name and inner_name in all_funcs:
                    found, reason = _resolve_chain(inner_name, seen)
                    if found:
                        return found, None
        return None, "no handler found within same-file call chain"

    for site in program.wait_for_sites:
        if site["handled_locally"]:
            site["resolution"] = "handled_locally"
            continue
        callee = site.get("callee")
        if not callee:
            site["resolution"] = "no callee name resolved -- needs manual check"
            continue
        hops = 0
        seen = set()
        current = callee
        resolved_at = None
        last_reason = None
        while current and hops < MAX_HOPS:
            found, reason = _resolve_chain(current, seen)
            if found:
                resolved_at = found
                break
            last_reason = reason
            break  # _resolve_chain already recurses internally; one call covers the chain
        if resolved_at:
            site["handled_locally"] = True
            site["resolution"] = f"handled_in_callee_chain:{resolved_at}"
        else:
            base_msg = f"{last_reason} -- needs manual check"
            # Limitation #4 mitigation: before giving up, check if the
            # containing function has a call that LOOKS cleanup-shaped by
            # a fuzzy stem match, even though it didn't exactly match
            # CLEANUP_CALL_NAMES. This never flips handled_locally --
            # it's surfaced as a hint so a reviewer knows to look, rather
            # than the tool implying nothing relevant is even present.
            fn_node = all_funcs.get(site["coro"])
            hint = _find_fuzzy_handler_hint(fn_node) if fn_node is not None else None
            if hint:
                base_msg += (f" (possible handler hint: a call to '.{hint}()' was seen "
                             f"nearby but isn't an exact cleanup-verb match -- verify manually)")
            site["resolution"] = base_msg

    # Filter #9's raw name-collision candidates down to ones that actually
    # matter: a bare name colliding across classes is only an ACTIONABLE
    # risk if the coroutine that ended up in program.coroutines under
    # that name (a) touches a Lock/Queue/Event, or (b) is a wait_for
    # site's containing coroutine. Dunder methods like __init__ collide
    # in almost every multi-class file and essentially never touch a
    # contended sync object -- surfacing those as "risk" is pure noise
    # that buries the collisions worth checking (e.g. 'acquire'/'release'
    # colliding across two connection-pool-shaped classes).
    SYNC_OP_KINDS_FOR_FILTER = {OpKind.ACQUIRE, OpKind.RELEASE, OpKind.Q_GET,
                                 OpKind.Q_PUT, OpKind.EV_WAIT, OpKind.EV_SET}
    wait_for_coro_names = {s["coro"] for s in program.wait_for_sites}
    program.coro_name_collisions = {}
    for name, class_scopes in _raw_coro_name_collisions.items():
        coro = program.coroutines.get(name)
        is_relevant = (coro is not None and
                       any(op.kind in SYNC_OP_KINDS_FOR_FILTER for op in coro.ops)) \
                      or name in wait_for_coro_names
        if is_relevant:
            program.coro_name_collisions[name] = class_scopes

    return program