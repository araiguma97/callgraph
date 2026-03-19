# callgraph

A static analysis tool that builds and visualizes call graphs from C/C++ source files using libclang Python bindings.

## Features

- Analyzes single files or entire directories recursively
- Supports C and C++ (namespaces, classes, constructors, templates)
- Detects virtual dispatch and renders it as dashed arrows
- Filters with `--from` (BFS subgraph) or `--around` (1-hop neighbors)
- Outputs DOT source or renders to SVG/PNG/PDF via Graphviz

## Requirements

- Python 3.10+
- libclang Python bindings: `pip install libclang`
- Graphviz Python package: `pip install graphviz`
- Graphviz CLI (`dot`): `brew install graphviz` (macOS)

## Setup

```bash
pip install libclang graphviz
brew install graphviz   # macOS
```

## Usage

```bash
# Analyze a single file
python3 src/callgraph.py sample/sample.cpp

# Analyze a directory recursively
python3 src/callgraph.py sample/

# Render to SVG
python3 src/callgraph.py sample/ --render out.svg

# Show subgraph reachable from a function
python3 src/callgraph.py sample/ --from main --render out.svg

# Show direct callers and callees of a function (1-hop)
python3 src/callgraph.py sample/ --around report --render out.svg

# Pass extra clang arguments after --
python3 src/callgraph.py sample/ --render out.svg -- -std=c++17 -Iinclude
```

On macOS, system headers may require additional clang flags:

```bash
python3 src/callgraph.py sample/ --render out.svg -- \
  -isysroot $(xcrun --show-sdk-path) \
  -resource-dir $(clang -print-resource-dir)
```

## Troubleshooting

### Missing header files

If a header file required by your project is not available (e.g. a third-party library header such as `somelib.h`), libclang may fail to parse the dependent source files fully, causing some function calls to be missing from the call graph.

**Workaround:** Create a minimal stub header in your include path:

```bash
# Example: create a stub for a missing third-party header
echo "// stub" > /path/to/include/somelib.h
```

Then pass the include path to the tool:

```bash
python3 src/callgraph.py src/ --render out.svg -- -std=c++17 -I/path/to/include
```

The stub only needs to declare the types and functions that your source files actually use. An empty file is sufficient if the header is included transitively but none of its symbols are referenced directly.
