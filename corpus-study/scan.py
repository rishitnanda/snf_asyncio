#!/usr/bin/env python3
"""
scan.py — Detect shared-state interactions inside `async def` functions across
a corpus of repos, and classify each interaction as "mediated" (goes through
an asyncio.Lock/Queue/Event/Semaphore/Condition in the same function) or
"unmediated" (direct read/write with no synchronization primitive visible in
the same function body).

METHODOLOGY / HEURISTICS (read before trusting the numbers):

1. Shared name = a Name/Attribute referenced inside an async function that is
   NOT one of: the function's own locals (params, assignment targets, for/with
   targets, walrus targets, except-as, nested-def names), a builtin, or an
   import alias. We bucket these into three shared-state kinds:
     - SELF_ATTR   : `self.<x>` or `cls.<x>` attribute access
     - GLOBAL      : name bound at module top level (module-level assignment,
                     top-level class/def, or `global` statement target)
     - CLOSURE     : name bound in an enclosing *function* scope (free
                     variable captured by a nested async def / async gen /
                     lambda), detected via a scope-chain walk.
   Pure local variables, parameters, and loop variables are excluded — they
   are not shared across tasks and are irrelevant to interference.

2. A shared-name access is a Store (write) or Load (read) of that name/attr.
   Augmented assignment (x += 1) counts as one interaction with kind="rw".

3. Mediation test: within the *same function*, we track whether the
   statement containing the access is lexically inside a `with` / `async
   with` block whose context-manager expression:
     - is a call/attribute plausibly on an asyncio synchronization primitive
       (heuristic name match: contains "lock", "semaphore", "condition",
       "event", or is `asyncio.Lock/Semaphore/BoundedSemaphore/Condition/
       Event(...)`), OR
     - the accessed object is itself the primitive and the access is via one
       of its safe methods (`.put`/`.put_nowait`/`.get`/`.get_nowait`/
       `.acquire`/`.release`/`.wait`/`.wait_for`/`.set`/`.clear`/`.is_set`/
       `.notify`/`.notify_all` on an asyncio.Queue/Lock/Event/Semaphore/
       Condition-typed object) — this is treated as mediated *by
       construction*, since correct use of these APIs is the synchronization
       itself, not an act requiring an external lock.
   Everything else is unmediated.

   This is a syntactic/heuristic proxy, not a proof. It will:
     - MISS locks acquired in a caller and just assumed held (undercounts
       mediation → conservative in one direction)
     - MISS locks stored under names that don't contain a recognizable
       keyword (undercounts mediation)
     - COUNT `async with self._lock:` blocks as mediating *everything*
       textually inside them, even unrelated attribates the lock wasn't
       intended to guard (overcounts mediation in a different way)
   Numbers should be read as an approximate, reproducible static signal, not
   a formal proof of data-race freedom.

4. We do NOT analyze cross-function call graphs. "Mediation" is a per-
   function, lexical property only, per the task spec.

Output: one JSON file per repo in results/, plus a combined summary.
"""
import ast
import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict

BUILTINS = set(dir(__builtins__)) if isinstance(__builtins__, type(sys)) else set(dir(__builtins__))
LOCK_KEYWORDS = ("lock", "semaphore", "condition", "mutex")
EVENT_QUEUE_KEYWORDS = ("event", "queue", "cond")
ASYNCIO_PRIMITIVE_CTORS = {
    "Lock", "RLock", "BoundedSemaphore", "Semaphore", "Condition", "Event", "Queue",
    "LifoQueue", "PriorityQueue",
}
MEDIATING_METHODS = {
    "acquire", "release", "wait", "wait_for", "set", "clear", "is_set",
    "notify", "notify_all", "put", "put_nowait", "get", "get_nowait", "join", "task_done",
}

SKIP_DIR_NAMES = {
    ".git", "tests", "test", "testing", "docs", "doc", "examples", "example",
    "benchmarks", "bench", "node_modules", ".tox", ".venv", "venv", "__pycache__",
}

# Some repos in the corpus are mixed sync/async codebases where the async
# support is a thin layer over a much larger sync implementation. Scanning
# the whole repo folds in a large volume of purely-sync interactions that
# have nothing to do with async interference; restricting the walk to the
# actual async submodule(s) isolates "the async client/engine" from "the
# whole library". Leave a repo out of this dict to scan it unscoped
# (unchanged behavior for every other repo in the corpus).
REPO_ASYNC_SCOPE = {
    "sqlalchemy": [
        "lib/sqlalchemy/ext/asyncio",
        "lib/sqlalchemy/dialects/postgresql/asyncpg.py",
        "lib/sqlalchemy/dialects/mysql/aiomysql.py",
        "lib/sqlalchemy/dialects/mysql/asyncmy.py",
        "lib/sqlalchemy/dialects/sqlite/aiosqlite.py",
        "lib/sqlalchemy/dialects/oracle/oracledb_async.py",
    ],
    "elasticsearch-py": [
        "elasticsearch/_async",
    ],
    "redis-py": [
        "redis/asyncio",
    ],
}

# Exclusion prefixes -- for repos where it's cleaner to exclude one or two
# known non-asyncio subtrees than to enumerate every legitimate file.
# websockets ships a genuine parallel threading-based sync client
# (src/websockets/sync) and a Trio backend (src/websockets/trio) -- Trio is
# already excluded from pooled scheduler-level statistics elsewhere in this
# study, so excluding its websockets backend here is consistent with that
# decision, not a new one. kubernetes_asyncio/client/models is ~800
# auto-generated OpenAPI DTO classes (V1Pod, V1Service, etc.) with plain
# __init__ assignments and no async methods -- not a "program with
# interference" at all, and the source of most of that repo's
# name-collision evidence.
REPO_ASYNC_EXCLUDE = {
    "websockets": [
        "src/websockets/sync",
        "src/websockets/trio",
    ],
    "kubernetes_asyncio": [
        "kubernetes_asyncio/client/models",
        "kubernetes_asyncio/test",
    ],
}


def _in_scope(relpath: Path, scope_prefixes, exclude_prefixes=None):
    """True if relpath (relative to repo root) falls under any of the given
    include prefixes (or no include list is given), AND does not fall under
    any exclude prefix. A prefix ending in .py is matched as an exact file;
    otherwise it's matched as a directory prefix."""
    rp = relpath.as_posix()

    def matches(prefix):
        if prefix.endswith(".py"):
            return rp == prefix
        return rp == prefix or rp.startswith(prefix.rstrip("/") + "/")

    if exclude_prefixes and any(matches(p) for p in exclude_prefixes):
        return False
    if scope_prefixes is None:
        return True
    return any(matches(p) for p in scope_prefixes)


def iter_python_files(root: Path, include_tests: bool, scope_prefixes=None, exclude_prefixes=None):
    for dirpath, dirnames, filenames in os.walk(root):
        base = os.path.basename(dirpath)
        if not include_tests and base.lower() in SKIP_DIR_NAMES - {"testing"}:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__", ".tox", ".venv", "venv")]
        for f in filenames:
            if not f.endswith(".py"):
                continue
            fpath = Path(dirpath) / f
            if not _in_scope(fpath.relative_to(root), scope_prefixes, exclude_prefixes):
                continue
            yield fpath


def name_hints_lock(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in LOCK_KEYWORDS)


def name_hints_sync_primitive(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in LOCK_KEYWORDS) or any(k in n for k in EVENT_QUEUE_KEYWORDS)


def expr_repr(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<expr>"


class ModuleScope:
    """Collect module-level bound names for a single file, split into:
      - names: assigned/def'd at module level -> real candidates for "GLOBAL"
               shared mutable state (module-level variables, and function/class
               *names themselves*, which can plausibly be treated as read-only
               references much like imports -- see import_names below).
      - import_names: names bound via import/import-from. These are excluded
        from GLOBAL classification entirely: referencing an imported module,
        class, or function (`asyncio.Lock`, `Frame`, `Opcode(...)`) is not a
        mutable shared-state interaction between concurrent coroutines -- the
        binding itself is immutable after import. Counting these as "unmediated
        global access" would be a methodological error, so we treat them the
        same as builtins."""
    def __init__(self, tree: ast.Module):
        self.names = set()
        self.import_names = set()
        for node in tree.body:
            self._collect(node)

    def _collect(self, node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.names.add(node.name)
        elif isinstance(node, (ast.Assign,)):
            for t in node.targets:
                self._collect_target(t)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            self._collect_target(node.target)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                self.import_names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.If):
            for n in node.body + node.orelse:
                self._collect(n)
        elif isinstance(node, (ast.Try,)):
            for n in node.body + node.orelse + node.finalbody:
                self._collect(n)
            for h in node.handlers:
                for n in h.body:
                    self._collect(n)
        elif isinstance(node, ast.With) or isinstance(node, ast.AsyncWith):
            for item in node.items:
                if item.optional_vars:
                    self._collect_target(item.optional_vars)
            for n in node.body:
                self._collect(n)

    def _collect_target(self, t):
        if isinstance(t, ast.Name):
            self.names.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                self._collect_target(e)


def collect_local_binds(fn_node) -> set:
    """All names bound *within* fn_node (params, assigns, for/with targets,
    walrus, except-as, nested def/class names). Does NOT descend into nested
    function bodies (their locals are their own scope), but nested function
    *names themselves* are locals of the outer function."""
    locals_ = set()

    args = fn_node.args
    for a in (args.posonlyargs + args.args + args.kwonlyargs):
        locals_.add(a.arg)
    if args.vararg:
        locals_.add(args.vararg.arg)
    if args.kwarg:
        locals_.add(args.kwarg.arg)

    def add_target(t):
        if isinstance(t, ast.Name):
            locals_.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                add_target(e)
        elif isinstance(t, ast.Starred):
            add_target(t.value)

    class LocalCollector(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            locals_.add(node.name)
        def visit_AsyncFunctionDef(self, node):
            if node is not fn_node:
                locals_.add(node.name)
                return
            self.generic_visit(node)
        def visit_ClassDef(self, node):
            locals_.add(node.name)
        def visit_Assign(self, node):
            for t in node.targets:
                add_target(t)
            self.generic_visit(node)
        def visit_AnnAssign(self, node):
            add_target(node.target)
            self.generic_visit(node)
        def visit_AugAssign(self, node):
            add_target(node.target)
            self.generic_visit(node)
        def visit_NamedExpr(self, node):
            add_target(node.target)
            self.generic_visit(node)
        def visit_For(self, node):
            add_target(node.target)
            self.generic_visit(node)
        def visit_AsyncFor(self, node):
            add_target(node.target)
            self.generic_visit(node)
        def visit_With(self, node):
            for item in node.items:
                if item.optional_vars:
                    add_target(item.optional_vars)
            self.generic_visit(node)
        def visit_AsyncWith(self, node):
            for item in node.items:
                if item.optional_vars:
                    add_target(item.optional_vars)
            self.generic_visit(node)
        def visit_ExceptHandler(self, node):
            if node.name:
                locals_.add(node.name)
            self.generic_visit(node)
        def visit_Global(self, node):
            pass
        def visit_Nonlocal(self, node):
            pass
        def visit_Lambda(self, node):
            pass  # lambda has its own scope; don't descend
        def visit_comprehension(self, node):
            add_target(node.target)

    LocalCollector().visit(fn_node)
    return locals_


MUTATING_METHODS_COMMUTATIVE = {"append", "extend", "add", "update", "setdefault", "union", "put", "put_nowait"}
MUTATING_METHODS_NONCOMMUTATIVE = {"pop", "remove", "discard", "clear", "insert", "popitem", "sort", "reverse", "get"}
COMMUTATIVE_AUGOPS = (ast.Add, ast.BitOr, ast.BitAnd, ast.BitXor)


@dataclass
class Interaction:
    file: str
    func: str
    lineno: int
    name: str
    kind: str          # SELF_ATTR | GLOBAL | CLOSURE
    access: str         # read | write | rw
    mediated: bool
    reason: str
    write_form: str = "read"   # read | full_rebind | subscript_write | augmented_commutative |
                                # augmented_noncommutative | mutating_method_commutative |
                                # mutating_method_noncommutative | other_write


def is_sync_primitive_ctor_call(node) -> bool:
    """asyncio.Lock() / asyncio.Semaphore() / Lock() etc."""
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr in ASYNCIO_PRIMITIVE_CTORS
    if isinstance(f, ast.Name):
        return f.id in ASYNCIO_PRIMITIVE_CTORS
    return False


class FunctionAnalyzer:
    def __init__(self, filepath, fn_node, module_scope: ModuleScope, enclosing_locals_stack):
        self.filepath = filepath
        self.fn = fn_node
        self.module_scope = module_scope
        self.locals = collect_local_binds(fn_node)
        self.enclosing_locals_stack = enclosing_locals_stack  # list of sets, outer->inner (excluding self)
        self.interactions = []
        # track lock-guarded regions via a stack while walking statements
        self._guard_stack = []  # list of (guard_kind, guard_repr)

    def analyze(self):
        self._walk_body(self.fn.body)
        return self.interactions

    def _stmt_guard(self, node):
        """Given a With/AsyncWith node, does it look like a sync-primitive guard?"""
        for item in node.items:
            expr = item.context_expr
            txt = expr_repr(expr)
            if name_hints_lock(txt) or is_sync_primitive_ctor_call(expr):
                return True, txt
        return False, None

    def _walk_body(self, stmts):
        for stmt in stmts:
            self._walk_stmt(stmt)

    def _walk_stmt(self, stmt):
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            guarded, guard_repr = self._stmt_guard(stmt)
            # also scan the context expressions themselves for shared-state access
            for item in stmt.items:
                self._scan_expr(item.context_expr, guarded=False)
            if guarded:
                self._guard_stack.append(guard_repr)
            self._walk_body(stmt.body)
            if guarded:
                self._guard_stack.pop()
            return
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                self._handle_target(t, write_form="full_rebind")
            self._walk_generic(stmt.value)
            return
        if isinstance(stmt, ast.AnnAssign):
            self._handle_target(stmt.target, write_form="full_rebind")
            if stmt.value is not None:
                self._walk_generic(stmt.value)
            return
        if isinstance(stmt, ast.AugAssign):
            commutative = isinstance(stmt.op, COMMUTATIVE_AUGOPS)
            wf = "augmented_commutative" if commutative else "augmented_noncommutative"
            self._handle_target(stmt.target, write_form=wf)
            self._walk_generic(stmt.value)
            return
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Nested function bodies are analyzed by the top-level walk_scopes
            # pass, which reaches async defs nested inside *sync* defs too.
            # Don't recurse here to avoid double-counting.
            return
        if isinstance(stmt, ast.Lambda):
            return
        # Generic: walk children statements & expressions, but don't recurse into nested defs above
        for field_name, value in ast.iter_fields(stmt):
            self._walk_generic(value)

    def _walk_generic(self, value):
        if isinstance(value, list):
            for v in value:
                self._walk_generic(v)
        elif isinstance(value, ast.AST):
            if isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._walk_stmt(value)
            elif isinstance(value, (ast.With, ast.AsyncWith)):
                self._walk_stmt(value)
            elif isinstance(value, ast.Lambda):
                return
            elif isinstance(value, ast.stmt):
                self._walk_stmt(value)
            else:
                self._scan_expr(value, guarded=bool(self._guard_stack))
                for field_name, sub in ast.iter_fields(value):
                    self._walk_generic(sub)

    def _classify_name(self, name):
        # local?
        if name in self.locals:
            return None
        if name in BUILTINS or name in ("self", "cls", "True", "False", "None"):
            return None
        if name in self.module_scope.import_names:
            return None  # imported symbol: immutable binding, not shared mutable state
        # closure (enclosing function locals, innermost first)
        for outer_locals in reversed(self.enclosing_locals_stack):
            if name in outer_locals:
                return "CLOSURE"
        if name in self.module_scope.names:
            return "GLOBAL"
        return None  # unresolved (likely an import we can't see, e.g. star-import); skip

    def _mediation_for_attr(self, obj_name_or_attr_chain: str, method: str = None) -> (bool, str):
        if self._guard_stack:
            return True, f"inside guarded with-block ({self._guard_stack[-1]})"
        if method and method in MEDIATING_METHODS and name_hints_sync_primitive(obj_name_or_attr_chain):
            return True, f"safe method .{method}() on primitive-like name"
        return False, "no lock/queue/event mediation found in function"

    def _handle_target(self, target, write_form):
        """Handle an assignment target (Assign/AugAssign/AnnAssign), correctly
        distinguishing a full rebind of a shared name from a subscript-write
        into a shared container (which does NOT rebind the container itself,
        and reads it rather than storing to it at the AST level)."""
        if isinstance(target, ast.Subscript):
            # x[key] = val  --  container `x` is READ (to get __setitem__), the
            # *slot* is written. This is the "independent key insertion" case.
            self._emit_for_expr(target.value, write_form="subscript_write")
            self._walk_generic(target.slice)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for e in target.elts:
                self._handle_target(e, write_form)
            return
        if isinstance(target, ast.Starred):
            self._handle_target(target.value, write_form)
            return
        if isinstance(target, ast.Attribute):
            self._emit_for_expr(target, write_form=write_form, force_ctx="store")
            return
        if isinstance(target, ast.Name):
            self._emit_for_expr(target, write_form=write_form, force_ctx="store")
            return

    def _emit_for_expr(self, node, write_form, force_ctx=None):
        """Emit an interaction for a resolved self.attr / Name expression with
        an explicit write_form, bypassing the generic ctx-based read/write
        inference (needed because e.g. the container in `x[k]=v` has ctx=Load
        at the AST level even though it's semantically part of a write)."""
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and base.id in ("self", "cls"):
                access = "write" if write_form != "read" else "read"
                mediated, reason = self._mediation_for_attr(node.attr, method=None)
                self.interactions.append(Interaction(
                    file=self.filepath, func=self.fn.name, lineno=node.lineno,
                    name=f"self.{node.attr}", kind="SELF_ATTR", access=access,
                    mediated=mediated, reason=reason, write_form=write_form,
                ))
                return
            # not a self/cls attribute chain (e.g. obj.attr[k]=v on some other
            # object) -- fall through to generic scan for whatever it resolves to
        if isinstance(node, ast.Name):
            cls = self._classify_name(node.id)
            if cls:
                access = "write" if write_form != "read" else "read"
                mediated, reason = self._mediation_for_attr(node.id, method=None)
                self.interactions.append(Interaction(
                    file=self.filepath, func=self.fn.name, lineno=node.lineno,
                    name=node.id, kind=cls, access=access,
                    mediated=mediated, reason=reason, write_form=write_form,
                ))
            return
        # complex target (e.g. a.b[c].d = v, or obj().attr = v) -- best effort:
        # generically scan it so we at least don't lose the read-side references
        self._walk_generic(node)

    def _scan_expr(self, node, guarded):
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and base.id in ("self", "cls"):
                is_store = isinstance(node.ctx, ast.Store) or isinstance(node.ctx, ast.Del)
                access = "write" if is_store else "read"
                wf = "other_write" if is_store else "read"
                mediated, reason = self._mediation_for_attr(node.attr, method=None)
                self.interactions.append(Interaction(
                    file=self.filepath, func=self.fn.name, lineno=node.lineno,
                    name=f"self.{node.attr}", kind="SELF_ATTR", access=access,
                    mediated=mediated, reason=reason, write_form=wf,
                ))
                return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = node.func.value
            method = node.func.attr
            if method in MUTATING_METHODS_COMMUTATIVE:
                mwf = "mutating_method_commutative"
            elif method in MUTATING_METHODS_NONCOMMUTATIVE:
                mwf = "mutating_method_noncommutative"
            else:
                mwf = "read"
            if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id in ("self", "cls"):
                attr_name = base.attr
                mediated, reason = self._mediation_for_attr(attr_name, method=method)
                access = "rw" if method in ("acquire", "release") else ("write" if mwf != "read" else "read")
                self.interactions.append(Interaction(
                    file=self.filepath, func=self.fn.name, lineno=node.lineno,
                    name=f"self.{attr_name}", kind="SELF_ATTR", access=access,
                    mediated=mediated, reason=reason, write_form=mwf,
                ))
                return  # avoid double count with generic Attribute walk below
            if isinstance(base, ast.Name):
                cls = self._classify_name(base.id)
                if cls:
                    mediated, reason = self._mediation_for_attr(base.id, method=method)
                    access = "rw" if method in ("acquire", "release") else ("write" if mwf != "read" else "read")
                    self.interactions.append(Interaction(
                        file=self.filepath, func=self.fn.name, lineno=node.lineno,
                        name=base.id, kind=cls, access=access,
                        mediated=mediated, reason=reason, write_form=mwf,
                    ))
                    return
        if isinstance(node, ast.Name):
            cls = self._classify_name(node.id)
            if cls:
                is_store = isinstance(node.ctx, (ast.Store, ast.Del))
                access = "write" if is_store else "read"
                wf = "other_write" if is_store else "read"
                mediated, reason = self._mediation_for_attr(node.id, method=None)
                self.interactions.append(Interaction(
                    file=self.filepath, func=self.fn.name, lineno=node.lineno,
                    name=node.id, kind=cls, access=access,
                    mediated=mediated, reason=reason, write_form=wf,
                ))
            return


def walk_scopes(node, mod_scope, enclosing_locals_stack, relpath, out_interactions):
    """Walk the whole module tree tracking a function-scope chain (locals of
    each enclosing FunctionDef/AsyncFunctionDef; ClassDef does NOT introduce a
    closure scope in Python, matching real semantics). Every AsyncFunctionDef
    found anywhere -- top-level, a method, nested in a sync function, nested
    in another async function/coroutine -- gets analyzed exactly once."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.AsyncFunctionDef):
            analyzer = FunctionAnalyzer(relpath, child, mod_scope, list(enclosing_locals_stack))
            out_interactions.extend(analyzer.analyze())
            new_stack = enclosing_locals_stack + [collect_local_binds(child)]
            walk_scopes(child, mod_scope, new_stack, relpath, out_interactions)
        elif isinstance(child, ast.FunctionDef):
            new_stack = enclosing_locals_stack + [collect_local_binds(child)]
            walk_scopes(child, mod_scope, new_stack, relpath, out_interactions)
        elif isinstance(child, ast.Lambda):
            continue  # not analyzed (can't contain async code anyway)
        else:
            # ClassDef, If, Try, With, etc. -- descend without adding a scope
            walk_scopes(child, mod_scope, enclosing_locals_stack, relpath, out_interactions)


def scan_file(path: Path, repo_root: Path):
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src, filename=str(path))
    except (SyntaxError, ValueError):
        return []
    mod_scope = ModuleScope(tree)
    relpath = str(path.relative_to(repo_root))
    interactions = []
    walk_scopes(tree, mod_scope, [], relpath, interactions)
    return interactions


def scan_repo(repo_dir: Path, include_tests=False, scope_prefixes=None, exclude_prefixes=None):
    all_interactions = []
    n_files = 0
    for f in iter_python_files(repo_dir, include_tests=include_tests, scope_prefixes=scope_prefixes, exclude_prefixes=exclude_prefixes):
        n_files += 1
        all_interactions.extend(scan_file(f, repo_dir))
    return all_interactions, n_files


def summarize(interactions):
    total = len(interactions)
    mediated = sum(1 for i in interactions if i.mediated)
    by_kind = {}
    for i in interactions:
        by_kind.setdefault(i.kind, {"total": 0, "mediated": 0})
        by_kind[i.kind]["total"] += 1
        if i.mediated:
            by_kind[i.kind]["mediated"] += 1
    return {
        "total_interactions": total,
        "mediated": mediated,
        "unmediated": total - mediated,
        "pct_mediated": round(100 * mediated / total, 2) if total else None,
        "by_kind": by_kind,
    }


def main():
    corpus_root = Path(__file__).parent
    repo_src = corpus_root / "repo_src"
    results_dir = corpus_root / "results"
    results_dir.mkdir(exist_ok=True)

    repos = sorted([d for d in repo_src.iterdir() if d.is_dir()])
    combined = []
    per_repo_summary = {}

    for repo_dir in repos:
        name = repo_dir.name
        scope = REPO_ASYNC_SCOPE.get(name)
        exclude = REPO_ASYNC_EXCLUDE.get(name)
        interactions, n_files = scan_repo(repo_dir, scope_prefixes=scope, exclude_prefixes=exclude)
        combined.extend(interactions)
        summ = summarize(interactions)
        summ["n_python_files_scanned"] = n_files
        summ["n_async_functions_with_interactions"] = len({(i.file, i.func) for i in interactions})
        summ["scoped_to"] = scope
        per_repo_summary[name] = summ
        with open(results_dir / f"{name}.json", "w") as fh:
            json.dump({
                "repo": name,
                "summary": summ,
                "interactions": [asdict(i) for i in interactions],
            }, fh, indent=2)
        scope_tag = " [scoped]" if scope else ""
        print(f"{name:22s}{scope_tag} files={n_files:5d}  interactions={summ['total_interactions']:6d}  "
              f"mediated={summ['mediated']:6d}  pct={summ['pct_mediated']}")

    overall = summarize(combined)
    with open(results_dir / "_SUMMARY.json", "w") as fh:
        json.dump({"per_repo": per_repo_summary, "overall": overall}, fh, indent=2)

    print("\n=== OVERALL ===")
    print(json.dumps(overall, indent=2))


if __name__ == "__main__":
    main()