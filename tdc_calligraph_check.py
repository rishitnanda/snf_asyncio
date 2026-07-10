"""
tdc_callgraph_check.py (v4) — call-graph-aware Thread-Disjointness
measurement, with correct callable-target resolution.

Fix over v3: v3 extracted only the final attribute name of the submitted
callable (e.g. "get" from `self.client.get`, or "close" from `f.close`)
and then matched that bare name against ANY same-named function in the
file — including the class's own unrelated coroutine of the same name.
This produced systematic false positives: redis-py's `get` "submitting"
`get` was actually `self.client.get` (a different object, an unrelated
sync HTTP client), and asyncpg's `_copy_in` "submitting" `close` was
actually a local file handle's `f.close`, not `Connection.close`.

This version only attempts resolution when the callable is:
  (a) a bare module-level function name, or
  (b) a DIRECT `self.<name>` attribute access (single-level, not
      `self.client.get` or `self.x.y.z`)
Anything else (nested attribute access, or attribute access on a
non-self local variable) is reported as unresolved with a specific
reason ("external object method — cannot resolve without type info"),
rather than guessed at. This trades recall for not fabricating false
overlaps.

Usage:
    python tdc_callgraph_check.py <repo_root> [--max-depth N] [--out PATH] [--repo-name NAME]
"""
import ast
import argparse
import os
import sys
from collections import defaultdict

THREAD_SUBMIT_METHOD_NAMES = {"run_in_executor", "submit"}
THREAD_CTOR_NAMES = {"Thread", "ThreadPoolExecutor"}


class ResolvedTarget:
    __slots__ = ("kind", "name")
    # kind: "bare_function", "self_method", "unresolvable", "lambda"
    def __init__(self, kind, name=None):
        self.kind = kind
        self.name = name


class FunctionIndex(ast.NodeVisitor):
    def __init__(self, module_globals):
        self.functions = {}
        self.module_globals = module_globals
        self._stack = []

    def _qualname(self, node_name):
        return ".".join(self._stack + [node_name])

    def _resolve_target(self, node):
        """Only resolve bare names and direct self.<name> attributes.
        Everything else (nested attrs, non-self attrs, calls, subscripts)
        is left unresolved rather than guessed."""
        if isinstance(node, ast.Name):
            return ResolvedTarget("bare_function", node.id)
        if isinstance(node, ast.Lambda):
            return ResolvedTarget("lambda")
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                return ResolvedTarget("self_method", node.attr)
            # nested attribute (self.client.get) or attribute on a
            # non-self variable (f.close) — cannot safely resolve
            return ResolvedTarget("unresolvable", f"<external-object>.{node.attr}")
        return ResolvedTarget("unresolvable", "<complex-expression>")

    def _extract_submitted_target(self, call_node):
        func = call_node.func
        fname = self._call_name(func)
        if fname in THREAD_SUBMIT_METHOD_NAMES:
            if call_node.args:
                if fname == "run_in_executor" and len(call_node.args) >= 2:
                    target = call_node.args[1]
                else:
                    target = call_node.args[0]
                return self._resolve_target(target)
        if fname in THREAD_CTOR_NAMES:
            for kw in call_node.keywords:
                if kw.arg == "target":
                    return self._resolve_target(kw.value)
        return None

    def _visit_fn(self, node, is_async):
        qn = self._qualname(node.name)
        self.functions[qn] = {
            "is_async": is_async,
            "calls": set(),
            "shared": set(),
            "thread_submissions": [],  # list of ResolvedTarget
        }
        self._stack.append(node.name)
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                fname = self._call_name(child.func)
                if fname:
                    self.functions[qn]["calls"].add(fname)
                if fname in THREAD_SUBMIT_METHOD_NAMES or fname in THREAD_CTOR_NAMES:
                    target = self._extract_submitted_target(child)
                    if target:
                        self.functions[qn]["thread_submissions"].append(target)
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                if child.value.id == "self":
                    self.functions[qn]["shared"].add(f"self.{child.attr}")
            if isinstance(child, ast.Name) and child.id in self.module_globals:
                self.functions[qn]["shared"].add(child.id)
        self._stack.pop()
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._visit_fn(node, is_async=False)

    def visit_AsyncFunctionDef(self, node):
        self._visit_fn(node, is_async=True)

    @staticmethod
    def _call_name(func_node):
        if isinstance(func_node, ast.Name):
            return func_node.id
        if isinstance(func_node, ast.Attribute):
            return func_node.attr
        return None


def collect_module_globals(tree):
    globs = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    globs.add(t.id)
    return globs


def reachable_shared(fn_name, functions, max_depth=6):
    seen, shared, frontier = set(), set(), {fn_name}
    depth = 0
    while frontier and depth < max_depth:
        nxt = set()
        for f in frontier:
            if f in seen or f not in functions:
                continue
            seen.add(f)
            shared |= functions[f]["shared"]
            for called in functions[f]["calls"]:
                nxt |= {g for g in functions if g.endswith("." + called) or g == called}
        frontier = nxt - seen
        depth += 1
    return shared


def resolve_in_index(resolved_target, functions, submitting_coro_qualname):
    """Only matches bare_function (module-level) and self_method
    (same-CLASS method, i.e. same qualname prefix minus the coroutine
    name) targets — never cross-object name collisions."""
    if resolved_target.kind == "bare_function":
        name = resolved_target.name
        if name in functions:
            return name
        matches = [g for g in functions if g == name or g.endswith("." + name)]
        # Only accept an UNAMBIGUOUS single match for bare module functions.
        return matches[0] if len(matches) == 1 else None
    if resolved_target.kind == "self_method":
        # Same class as the submitting coroutine: same qualname prefix.
        prefix_parts = submitting_coro_qualname.split(".")[:-1]
        class_prefix = ".".join(prefix_parts)
        candidate = f"{class_prefix}.{resolved_target.name}" if class_prefix else resolved_target.name
        if candidate in functions:
            return candidate
        return None
    return None


def analyze_file(path, max_depth):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return [], []
    globs = collect_module_globals(tree)
    idx = FunctionIndex(globs)
    idx.visit(tree)

    async_fns = {name: info for name, info in idx.functions.items() if info["is_async"]}

    results = []
    unresolved = []

    for coro_name, coro_info in async_fns.items():
        for target in coro_info["thread_submissions"]:
            if target.kind in ("lambda", "unresolvable"):
                unresolved.append({
                    "file": path, "coroutine": coro_name,
                    "reason": f"{target.kind}: {target.name or 'inline lambda'} — needs manual inspection",
                })
                continue
            resolved = resolve_in_index(target, idx.functions, coro_name)
            if resolved is None:
                unresolved.append({
                    "file": path, "coroutine": coro_name,
                    "reason": f"could not resolve '{target.name}' ({target.kind}) to a definite same-scope function",
                })
                continue
            thread_footprint = reachable_shared(resolved, idx.functions, max_depth=max_depth)
            if not thread_footprint:
                continue
            for other_name, other_info in async_fns.items():
                if other_name == coro_name:
                    continue
                overlap = thread_footprint & other_info["shared"]
                if overlap:
                    results.append({
                        "file": path,
                        "thread_submitting_coroutine": coro_name,
                        "submitted_callable": resolved,
                        "other_coroutine": other_name,
                        "overlap": sorted(overlap),
                    })
    return results, unresolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_root")
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "tdc_callgraph_results.json"))
    ap.add_argument("--unresolved-out", default=os.path.join(os.getcwd(), "tdc_unresolved.json"))
    ap.add_argument("--repo-name", default=None)
    args = ap.parse_args()

    repo_label = args.repo_name or os.path.basename(os.path.normpath(args.repo_root))

    this_run_results, this_run_unresolved = [], []
    for dirpath, _, filenames in os.walk(args.repo_root):
        if "test" in dirpath.lower():
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                r, u = analyze_file(os.path.join(dirpath, fn), args.max_depth)
                this_run_results.extend(r)
                this_run_unresolved.extend(u)

    for r in this_run_results:
        r["repo"] = repo_label
    for u in this_run_unresolved:
        u["repo"] = repo_label

    print(f"[{repo_label}] {len(this_run_results)} genuine candidate overlaps "
          f"(same-class self.method or unambiguous bare-function targets only).")
    print(f"[{repo_label}] {len(this_run_unresolved)} thread-submission call sites "
          f"left unresolved (external-object methods, lambdas, ambiguous names) — inspect by hand.")

    import json

    def merge_and_write(path, new_items, repo_label):
        acc = []
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    acc = json.load(f)
            except (json.JSONDecodeError, OSError):
                acc = []
        acc = [r for r in acc if r.get("repo") != repo_label]
        acc.extend(new_items)
        with open(path, "w") as f:
            json.dump(acc, f, indent=2)
        return acc

    acc_results = merge_and_write(args.out, this_run_results, repo_label)
    acc_unresolved = merge_and_write(args.unresolved_out, this_run_unresolved, repo_label)

    by_repo = defaultdict(int)
    for r in acc_results:
        by_repo[r.get("repo", "unknown")] += 1
    print(f"\nAccumulated genuine-candidate results ({len(acc_results)} total, "
          f"{len(by_repo)} repos so far):")
    for repo, count in sorted(by_repo.items(), key=lambda kv: -kv[1]):
        print(f"  {repo}: {count}")

    by_repo_unres = defaultdict(int)
    for u in acc_unresolved:
        by_repo_unres[u.get("repo", "unknown")] += 1
    print(f"\nAccumulated unresolved call sites ({len(acc_unresolved)} total) — inspect by hand:")
    for repo, count in sorted(by_repo_unres.items(), key=lambda kv: -kv[1]):
        print(f"  {repo}: {count}")


if __name__ == "__main__":
    sys.exit(main())