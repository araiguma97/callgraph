#!/usr/bin/env python3
"""
Build a call graph from a C/C++ source file or directory using libclang.

Data structure:
  CallGraph:
    edges:        dict[str, set[str]]  -- caller -> {callee, ...}
    defined_in:   dict[str, str]       -- function name -> source file path
    virtual_edges: set[tuple[str,str]] -- edges that represent virtual dispatch

Usage:
  # Analyze a single file
  python3 callgraph.py <file.c/.cpp> [--from FUNC] [--around FUNC] [--dot F] [--render F] [-- clang args]
  # Analyze all C/C++ files in a directory (recursive)
  python3 callgraph.py <dir/> [--from FUNC] [--around FUNC] [--dot F] [--render F] [-- clang args]

C++ example:
  python3 callgraph.py src/ --from main --render out.svg -- -std=c++17
"""

import os
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
import clang.cindex as cindex

_FUNC_KINDS = {
    cindex.CursorKind.FUNCTION_DECL,
    cindex.CursorKind.CXX_METHOD,
    cindex.CursorKind.CONSTRUCTOR,
    cindex.CursorKind.DESTRUCTOR,
    cindex.CursorKind.FUNCTION_TEMPLATE,
}

_C_EXTENSIONS   = {".c"}
_CPP_EXTENSIONS = {".cpp", ".cc", ".cxx"}
_ALL_EXTENSIONS = _C_EXTENSIONS | _CPP_EXTENSIONS



def _qualified_name(node) -> str:
    """Return the fully qualified name, e.g. 'math::Calculator::multiply'."""
    parts = [node.spelling]
    parent = node.semantic_parent
    while parent and parent.kind != cindex.CursorKind.TRANSLATION_UNIT:
        if parent.spelling:
            parts.append(parent.spelling)
        parent = parent.semantic_parent
    return "::".join(reversed(parts))


def _unqualified(qname: str) -> str:
    return qname.rsplit("::", 1)[-1]


def _effective_clang_args(filepath: Path, common_args: list[str]) -> list[str]:
    """Strip C++-specific flags when compiling a plain C file."""
    if filepath.suffix in _C_EXTENSIONS:
        return [a for a in common_args if not a.startswith("-std=c++")]
    return list(common_args)


@dataclass
class CallGraph:
    edges:         dict[str, set[str]]    = field(default_factory=dict)
    defined_in:    dict[str, str]         = field(default_factory=dict)
    virtual_edges: set[tuple[str, str]]   = field(default_factory=set)
    # spelling -> set of qualified names that override that spelling
    # (populated during parsing, consumed by resolve_virtual_dispatch)
    _override_impls: dict[str, set[str]]  = field(default_factory=dict)
    # class qualified name -> set of direct base class qualified names
    _class_bases:    dict[str, set[str]]  = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def defined(self) -> set[str]:
        return set(self.defined_in.keys())

    def add_edge(self, caller: str, callee: str) -> None:
        self.edges.setdefault(caller, set()).add(callee)

    def callees_of(self, func: str) -> set[str]:
        return self.edges.get(func, set())

    def all_functions(self) -> set[str]:
        """All function names appearing as caller or callee."""
        result = set(self.edges.keys())
        for callees in self.edges.values():
            result |= callees
        return result

    def iter_edges(self) -> Iterator[tuple[str, str]]:
        for caller, callees in self.edges.items():
            for callee in sorted(callees):
                yield caller, callee

    # ------------------------------------------------------------------
    # Multi-file support
    # ------------------------------------------------------------------

    def merge(self, other: "CallGraph") -> None:
        """Merge another CallGraph into this one (in-place)."""
        for caller, callees in other.edges.items():
            self.edges.setdefault(caller, set()).update(callees)
        for name, path in other.defined_in.items():
            self.defined_in.setdefault(name, path)
        for spelling, impls in other._override_impls.items():
            self._override_impls.setdefault(spelling, set()).update(impls)
        for cls, bases in other._class_bases.items():
            self._class_bases.setdefault(cls, set()).update(bases)
        self.virtual_edges |= other.virtual_edges

    # ------------------------------------------------------------------
    # Virtual dispatch resolution
    # ------------------------------------------------------------------

    def _is_descendant(self, cls: str, ancestor: str) -> bool:
        """Return True if cls inherits from ancestor (directly or transitively)."""
        visited: set[str] = set()
        queue: deque[str] = deque([cls])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for base in self._class_bases.get(current, set()):
                if base == ancestor:
                    return True
                queue.append(base)
        return False

    def resolve_virtual_dispatch(self) -> None:
        """Expand virtual call edges to all known concrete override implementations.

        For each edge (caller -> base_virtual):
          - Find all concrete overrides (in defined_in) that share the same
            unqualified method name AND whose class descends from the callee's class.
          - Replace the edge to the pure virtual base with edges to each
            concrete override, and mark them in virtual_edges.
          - If the base has a concrete body (is in defined_in), keep it as
            a virtual dispatch edge too.
        """
        for caller in list(self.edges.keys()):
            for callee in list(self.edges.get(caller, set())):
                spelling = _unqualified(callee)
                callee_class = callee.rsplit("::", 1)[0] if "::" in callee else ""
                impls = {
                    impl for impl in self._override_impls.get(spelling, set())
                    if impl in self.defined_in
                    and impl != callee
                    and (
                        not callee_class
                        or self._is_descendant(
                            impl.rsplit("::", 1)[0] if "::" in impl else "",
                            callee_class,
                        )
                    )
                }
                if not impls:
                    continue

                # Add virtual dispatch edges to concrete overrides
                for impl in impls:
                    self.add_edge(caller, impl)
                    self.virtual_edges.add((caller, impl))

                # If base is pure virtual (not in defined_in), remove edge to it
                if callee not in self.defined_in:
                    self.edges[caller].discard(callee)
                else:
                    # Base has a body: keep it but mark as virtual dispatch
                    self.virtual_edges.add((caller, callee))

    # ------------------------------------------------------------------
    # Subgraph extraction
    # ------------------------------------------------------------------

    def callers_of(self, func: str) -> set[str]:
        """Return the set of functions that directly call func."""
        return {caller for caller, callees in self.edges.items() if func in callees}

    def neighbors_of(self, func: str) -> "CallGraph":
        """Return a subgraph of the direct callers and callees of func (1 hop each way)."""
        if func not in self.all_functions():
            raise ValueError(f"Function '{func}' not found in call graph")

        sub = CallGraph(defined_in=dict(self.defined_in))
        for callee in self.callees_of(func):
            sub.add_edge(func, callee)
            if (func, callee) in self.virtual_edges:
                sub.virtual_edges.add((func, callee))
        for caller in self.callers_of(func):
            sub.add_edge(caller, func)
            if (caller, func) in self.virtual_edges:
                sub.virtual_edges.add((caller, func))
        return sub

    def subgraph_from(self, root: str) -> "CallGraph":
        """Return a subgraph of edges reachable from root (BFS)."""
        if root not in self.all_functions():
            raise ValueError(f"Function '{root}' not found in call graph")

        visited: set[str] = set()
        queue: deque[str] = deque([root])
        sub = CallGraph(defined_in=dict(self.defined_in))

        while queue:
            caller = queue.popleft()
            if caller in visited:
                continue
            visited.add(caller)
            for callee in self.callees_of(caller):
                sub.add_edge(caller, callee)
                if (caller, callee) in self.virtual_edges:
                    sub.virtual_edges.add((caller, callee))
                if callee not in visited:
                    queue.append(callee)

        return sub

    # ------------------------------------------------------------------
    # Graphviz output
    # ------------------------------------------------------------------

    def to_dot(self, root: str | None = None, focus: str | None = None) -> str:
        """Return a Graphviz DOT string.

        Node styles:
          root/focus: double circle (blue for root, orange for focus)
          others    : ellipse, light grey fill
        Edge styles:
          regular call    : solid black arrow
          virtual dispatch: dashed black arrow
        """
        import graphviz

        def node_id(name: str) -> str:
            return name.replace("::", "__")

        g = graphviz.Digraph(
            name="callgraph",
            graph_attr={"rankdir": "LR", "fontname": "Helvetica"},
            node_attr={"fontname": "Helvetica", "fontsize": "12"},
            edge_attr={"fontname": "Helvetica", "fontsize": "10"},
        )

        pinned = {n for n in (root, focus) if n}
        nodes: set[str] = self.defined | pinned

        for name in sorted(nodes):
            nid = node_id(name)
            if name == root:
                g.node(nid, label=name, shape="doublecircle", style="filled",
                       fillcolor="#4a90d9", fontcolor="white")
            elif name == focus:
                g.node(nid, label=name, shape="doublecircle", style="filled",
                       fillcolor="#e67e22", fontcolor="white")
            else:
                g.node(nid, label=name, shape="ellipse", style="filled", fillcolor="#eeeeee")

        for caller, callee in self.iter_edges():
            if caller not in nodes or callee not in nodes:
                continue
            if (caller, callee) in self.virtual_edges:
                g.edge(node_id(caller), node_id(callee), style="dashed", color="black")
            else:
                g.edge(node_id(caller), node_id(callee))

        return g.source


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------

def build_callgraph(
    filepath: str,
    clang_args: list[str] | None = None,
) -> CallGraph:
    """Parse a single C/C++ file and return its CallGraph."""
    real_filepath = os.path.realpath(filepath)
    effective_args = _effective_clang_args(Path(filepath), clang_args or [])

    index = cindex.Index.create()
    tu = index.parse(filepath, args=effective_args)

    for diag in tu.diagnostics:
        if diag.severity >= cindex.Diagnostic.Warning:
            print(f"[WARN] {diag}", file=sys.stderr)

    cg = CallGraph()

    _CLASS_KINDS = {cindex.CursorKind.CLASS_DECL, cindex.CursorKind.STRUCT_DECL}

    for node in tu.cursor.walk_preorder():
        # Collect class inheritance: class -> {direct base classes}
        if node.kind in _CLASS_KINDS and node.spelling:
            cls_name = _qualified_name(node)
            for child in node.get_children():
                if child.kind == cindex.CursorKind.CXX_BASE_SPECIFIER:
                    base_ref = child.referenced
                    if base_ref is not None and base_ref.spelling:
                        base_name = _qualified_name(base_ref)
                        cg._class_bases.setdefault(cls_name, set()).add(base_name)

        if node.kind not in _FUNC_KINDS:
            continue
        if not node.is_definition():
            continue
        if node.location.file is None:
            continue
        if os.path.realpath(node.location.file.name) != real_filepath:
            continue

        caller = _qualified_name(node)
        cg.defined_in[caller] = real_filepath

        # Collect override implementations (methods with `override` keyword)
        if node.is_virtual_method():
            has_override = any(
                c.kind == cindex.CursorKind.CXX_OVERRIDE_ATTR
                for c in node.get_children()
            )
            if has_override:
                spelling = node.spelling
                cg._override_impls.setdefault(spelling, set()).add(caller)

        for call_node in node.walk_preorder():
            if call_node.kind != cindex.CursorKind.CALL_EXPR:
                continue
            ref = call_node.referenced
            if ref is None or ref.kind not in _FUNC_KINDS:
                continue
            callee = _qualified_name(ref)
            if callee and callee != caller:
                cg.add_edge(caller, callee)

    cg.resolve_virtual_dispatch()
    return cg


def build_callgraph_from_dir(
    dirpath: str,
    clang_args: list[str] | None = None,
) -> CallGraph:
    """Recursively scan dirpath for C/C++ files and return a merged CallGraph."""
    root = Path(dirpath)
    files = sorted(p for p in root.rglob("*") if p.suffix in _ALL_EXTENSIONS)

    if not files:
        print(f"[WARN] No C/C++ source files found in '{dirpath}'", file=sys.stderr)

    merged = CallGraph()
    for fpath in files:
        print(f"  Parsing {fpath} ...", file=sys.stderr)
        cg = build_callgraph(str(fpath), clang_args)
        merged.merge(cg)

    # Re-run resolution on the merged graph to catch cross-file overrides
    merged.resolve_virtual_dispatch()
    return merged


# ----------------------------------------------------------------------
# Display
# ----------------------------------------------------------------------

def print_callgraph(cg: CallGraph) -> None:
    print("=== Call Graph (edge list) ===\n")
    for caller, callee in cg.iter_edges():
        if callee not in cg.defined:
            continue
        tag = " [virtual]" if (caller, callee) in cg.virtual_edges else ""
        print(f"  {caller}  -->  {callee}{tag}")

    print(f"\n=== Defined functions ({len(cg.defined_in)}) ===")
    files = sorted(set(cg.defined_in.values()))
    for fpath in files:
        funcs = sorted(n for n, p in cg.defined_in.items() if p == fpath)
        label = Path(fpath).name
        for func in funcs:
            print(f"  [{label}]  {func}")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    argv = sys.argv[1:]
    if "--" in argv:
        sep = argv.index("--")
        own_argv, clang_args = argv[:sep], argv[sep + 1:]
    else:
        own_argv, clang_args = argv, []

    parser = argparse.ArgumentParser(
        description="Build a call graph from a C/C++ source file or directory.",
        epilog=(
            "Examples:\n"
            "  %(prog)s sample.cpp --from main --render out.svg -- -std=c++17\n"
            "  %(prog)s src/ --from main --render out.svg -- -std=c++17"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target",
                        help="C/C++ source file or directory to analyze")
    parser.add_argument("--from", dest="root", metavar="FUNC",
                        help="show only the subgraph reachable from this function (BFS)")
    parser.add_argument("--around", dest="focus", metavar="FUNC",
                        help="show only the direct callers and callees of this function (1 hop)")
    parser.add_argument("--dot", metavar="FILE",
                        help="write DOT source to FILE")
    parser.add_argument("--render", metavar="FILE",
                        help="render graph image to FILE (svg, png, pdf, ...)")

    args = parser.parse_args(own_argv)

    if args.root and args.focus:
        print("Error: --from and --around cannot be used together.", file=sys.stderr)
        sys.exit(1)

    target = Path(args.target)
    if target.is_dir():
        cg = build_callgraph_from_dir(str(target), clang_args or None)
    else:
        cg = build_callgraph(str(target), clang_args or None)

    if args.root:
        try:
            cg = cg.subgraph_from(args.root)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.focus:
        try:
            cg = cg.neighbors_of(args.focus)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    if args.dot or args.render:
        dot_source = cg.to_dot(root=args.root, focus=args.focus)

        if args.dot:
            Path(args.dot).write_text(dot_source)
            print(f"DOT source written to: {args.dot}")

        if args.render:
            import graphviz
            out = Path(args.render)
            fmt = out.suffix.lstrip(".") or "svg"
            src = graphviz.Source(dot_source)
            rendered = src.render(filename=str(out.with_suffix("")), format=fmt, cleanup=True)
            print(f"Graph rendered to: {rendered}")
    else:
        if args.root:
            print(f"(subgraph rooted at '{args.root}')\n")
        elif args.focus:
            print(f"(neighbors of '{args.focus}')\n")
        print_callgraph(cg)
