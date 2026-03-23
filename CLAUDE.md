# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
uv run pytest

# Run a single test
uv run pytest tests/test_analyzer.py::TestDeclarations::test_function_declaration_is_recorded

# Run a test class
uv run pytest tests/test_analyzer.py::TestIncludeHandling

# Install in editable mode
uv pip install -e .

# Build distribution
hatch build

# Run the CLI
openscad-dependencies [-d out.dot] [-c] <file.scad>
```

## Architecture

This is a single-module Python package (`openscad_dependencies/__init__.py`) that provides a CLI tool for analyzing call dependencies across OpenSCAD source files.

### Two-phase analysis

**Phase 1 — `process_file()` / `_walk()`**: Recursively parses `.scad` files via `openscad_parser.ast.getASTfromFile()` and walks the AST, recording:
- Declarations (`declared_functions`, `declared_modules`, `declared_variables`) — keyed by name, valued by `ItemDecl(name, file)` indicating which file owns the declaration.
- Calls/accesses (`func_calls`, `mod_calls`, `var_accesses`) — keyed by calling file, then by symbol name.
- Include/use edges (`include_calls`, `use_calls`) — resolved and walked immediately, attributing declarations to the library file, not the caller.

**Phase 2 — `analyze_external_calls()`**: Cross-references calls against declarations to identify which calls are external (defined in a different file). Populates `ext_calls_in_file` and `called_files` (a mapping from `calling_file → called_file → [symbol_names]`).

### Key design decisions

- `include<>` vs `use<>`: both load and walk the library file; `use<>` additionally adds the file to `use_files`, which causes its variables to be treated as external even when accessed from the same file (matching OpenSCAD semantics).
- Circular include/use detection uses a `load_stack` list; cycles are reported to stdout and skipped.
- Built-in OpenSCAD functions and modules are filtered out at call-recording time so they never appear as external dependencies.
- AST walking dispatches by node type via `_walk()`; generic nodes fall through to `_walk_generic()` which iterates dataclass fields. Parameter names and named-argument labels are explicitly skipped to avoid false variable-access records.

### Output

- `get_results()` returns a human-readable string and optionally writes a GraphViz DOT digraph to a file (`-d`).
- The `--no-calls` / `-c` flag suppresses listing individual symbol names in both text and DOT output.
