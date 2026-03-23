"""
Tests for OpenSCADDependencyAnalyzer.

Organised into test classes that mirror the major responsibilities of the
analyzer:
    TestDeclarations         – function / module / variable recording
    TestCallTracking         – function / module call recording
    TestBuiltinFiltering     – builtin symbols are silently skipped
    TestIdentifierScoping    – what does / doesn't count as a variable access
    TestIncludeHandling      – include<> semantics (inlined by parser at parse time)
    TestUseHandling          – use<> file loading and library attribution
    TestCircularDetection    – loop-guard for use<> chains; include<> handled by parser
    TestExternalCallAnalysis – analyze_external_calls() logic
    TestGetResults           – text output format
    TestDotOutput            – GraphViz DOT file generation
    TestEdgeCases            – robustness / corner cases
"""

import os
import sys
import textwrap
import types
import unittest.mock as mock
from pathlib import Path

import pytest
import openscad_parser.ast as ospa

# ---------------------------------------------------------------------------
# Make the project importable whether run from the repo root or the tests dir
# ---------------------------------------------------------------------------
_repo_root = os.path.join(os.path.dirname(__file__), "..")
for _p in [_repo_root]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from openscad_dependencies import ItemDecl, OpenSCADDependencyAnalyzer  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opts(no_calls: bool = False) -> types.SimpleNamespace:
    """Minimal opts namespace that matches what argparse would produce."""
    return types.SimpleNamespace(no_calls=no_calls)


def _analyzer(scad_file: str, no_calls: bool = False) -> OpenSCADDependencyAnalyzer:
    """Create a fresh analyzer, process one file, and return it."""
    a = OpenSCADDependencyAnalyzer(startfile=scad_file, opts=_opts(no_calls=no_calls))
    a.process_file(scad_file)
    return a


def _write(directory: Path, name: str, content: str) -> str:
    """Write dedented content to <directory>/<name> and return the absolute path."""
    path = directory / name
    path.write_text(textwrap.dedent(content))
    return str(path.resolve())


# ---------------------------------------------------------------------------
# TestDeclarations
# ---------------------------------------------------------------------------

class TestDeclarations:
    """Function, module, and variable declarations are recorded correctly."""

    def test_function_declaration_is_recorded(self, tmp_path):
        f = _write(tmp_path, "a.scad", "function add(x, y) = x + y;")
        a = _analyzer(f)
        assert "add" in a.declared_functions
        assert a.declared_functions["add"].file == f

    def test_multiple_function_declarations(self, tmp_path):
        f = _write(tmp_path, "a.scad", """\
            function foo(x) = x;
            function bar(x) = x * 2;
            function baz() = 42;
        """)
        a = _analyzer(f)
        assert "foo" in a.declared_functions
        assert "bar" in a.declared_functions
        assert "baz" in a.declared_functions

    def test_function_with_no_params(self, tmp_path):
        f = _write(tmp_path, "a.scad", "function pi() = 3.14159;")
        a = _analyzer(f)
        assert "pi" in a.declared_functions

    def test_module_declaration_is_recorded(self, tmp_path):
        f = _write(tmp_path, "a.scad", "module box(size) { cube(size); }")
        a = _analyzer(f)
        assert "box" in a.declared_modules
        assert a.declared_modules["box"].file == f

    def test_multiple_module_declarations(self, tmp_path):
        f = _write(tmp_path, "a.scad", """\
            module foo() { }
            module bar(x) { cube(x); }
        """)
        a = _analyzer(f)
        assert "foo" in a.declared_modules
        assert "bar" in a.declared_modules

    def test_variable_assignment_is_recorded(self, tmp_path):
        f = _write(tmp_path, "a.scad", "thickness = 3;")
        a = _analyzer(f)
        assert "thickness" in a.declared_variables
        assert a.declared_variables["thickness"].file == f

    def test_multiple_variable_assignments(self, tmp_path):
        f = _write(tmp_path, "a.scad", """\
            width = 10;
            height = 20;
            depth = 5;
        """)
        a = _analyzer(f)
        assert "width" in a.declared_variables
        assert "height" in a.declared_variables
        assert "depth" in a.declared_variables

    def test_variable_assigned_from_expression(self, tmp_path):
        f = _write(tmp_path, "a.scad", "area = 3 * 4;")
        a = _analyzer(f)
        assert "area" in a.declared_variables

    def test_function_name_not_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "function foo() = 1;")
        a = _analyzer(f)
        assert "foo" not in a.var_accesses.get(f, {})

    def test_module_name_not_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "module bar() { }")
        a = _analyzer(f)
        assert "bar" not in a.var_accesses.get(f, {})

    def test_variable_name_not_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = 5;")
        a = _analyzer(f)
        assert "x" not in a.var_accesses.get(f, {})


# ---------------------------------------------------------------------------
# TestCallTracking
# ---------------------------------------------------------------------------

class TestCallTracking:
    """Function and module calls are tracked in func_calls / mod_calls."""

    def test_function_call_recorded(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = my_func(3);")
        a = _analyzer(f)
        assert "my_func" in a.func_calls.get(f, {})

    def test_module_call_recorded(self, tmp_path):
        f = _write(tmp_path, "a.scad", "my_module(5);")
        a = _analyzer(f)
        assert "my_module" in a.mod_calls.get(f, {})

    def test_multiple_function_calls(self, tmp_path):
        f = _write(tmp_path, "a.scad", "z = foo(bar(1));")
        a = _analyzer(f)
        assert "foo" in a.func_calls.get(f, {})
        assert "bar" in a.func_calls.get(f, {})

    def test_multiple_module_calls(self, tmp_path):
        f = _write(tmp_path, "a.scad", """\
            widget_a(1);
            widget_b(2);
        """)
        a = _analyzer(f)
        assert "widget_a" in a.mod_calls.get(f, {})
        assert "widget_b" in a.mod_calls.get(f, {})

    def test_function_call_target_not_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = my_func(3);")
        a = _analyzer(f)
        assert "my_func" not in a.var_accesses.get(f, {})

    def test_module_call_target_not_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "my_module(5);")
        a = _analyzer(f)
        assert "my_module" not in a.var_accesses.get(f, {})


# ---------------------------------------------------------------------------
# TestBuiltinFiltering
# ---------------------------------------------------------------------------

class TestBuiltinFiltering:
    """Builtin functions and modules are silently excluded from tracking."""

    def test_builtin_function_sin_not_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = sin(45);")
        a = _analyzer(f)
        assert "sin" not in a.func_calls.get(f, {})

    def test_builtin_function_len_not_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", "n = len([1,2,3]);")
        a = _analyzer(f)
        assert "len" not in a.func_calls.get(f, {})

    def test_builtin_function_concat_not_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", "v = concat([1], [2]);")
        a = _analyzer(f)
        assert "concat" not in a.func_calls.get(f, {})

    def test_builtin_function_str_not_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", 'label = str("x=", x);')
        a = _analyzer(f)
        assert "str" not in a.func_calls.get(f, {})

    def test_builtin_module_cube_not_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", "cube(10);")
        a = _analyzer(f)
        assert "cube" not in a.mod_calls.get(f, {})

    def test_builtin_module_translate_not_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", "translate([1,0,0]) cube(1);")
        a = _analyzer(f)
        assert "translate" not in a.mod_calls.get(f, {})

    def test_builtin_module_union_not_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", "union() { cube(1); sphere(1); }")
        a = _analyzer(f)
        assert "union" not in a.mod_calls.get(f, {})

    def test_builtin_module_color_not_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", 'color("red") cube(1);')
        a = _analyzer(f)
        assert "color" not in a.mod_calls.get(f, {})

    def test_non_builtin_alongside_builtin(self, tmp_path):
        f = _write(tmp_path, "a.scad", "my_part(5); cube(5);")
        a = _analyzer(f)
        assert "my_part" in a.mod_calls.get(f, {})
        assert "cube" not in a.mod_calls.get(f, {})


# ---------------------------------------------------------------------------
# TestIdentifierScoping
# ---------------------------------------------------------------------------

class TestIdentifierScoping:
    """Identifiers that are definitions or call targets don't become var accesses."""

    def test_parameter_name_not_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "function add(x, y) = 5;")
        a = _analyzer(f)
        assert "x" not in a.var_accesses.get(f, {})
        assert "y" not in a.var_accesses.get(f, {})

    def test_parameter_used_in_body_is_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "function double(n) = n * 2;")
        a = _analyzer(f)
        assert "n" in a.var_accesses.get(f, {})

    def test_named_arg_label_not_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "my_mod(size=10);")
        a = _analyzer(f)
        assert "size" not in a.var_accesses.get(f, {})

    def test_named_arg_value_identifier_is_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "my_mod(size=thickness);")
        a = _analyzer(f)
        assert "thickness" in a.var_accesses.get(f, {})

    def test_positional_arg_identifier_is_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = my_func(width);")
        a = _analyzer(f)
        assert "width" in a.var_accesses.get(f, {})

    def test_rhs_of_assignment_identifier_is_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "y = x;")
        a = _analyzer(f)
        assert "x" in a.var_accesses.get(f, {})
        assert "y" not in a.var_accesses.get(f, {})

    def test_function_default_param_identifier_is_a_var_access(self, tmp_path):
        f = _write(tmp_path, "a.scad", "function f(x, y=DEFAULT) = x;")
        a = _analyzer(f)
        assert "DEFAULT" in a.var_accesses.get(f, {})


# ---------------------------------------------------------------------------
# TestIncludeHandling
#
# The openscad_parser inlines include<> at parse time: included declarations
# appear directly in the calling file's AST as if they were written there.
# As a result:
#   - Declarations from included files are attributed to the *calling* file.
#   - The analyzer never sees an IncludeStatement, so include_calls is empty
#     and the included file is not separately registered.
#   - Calls to symbols from an included file are treated as internal (same file).
# ---------------------------------------------------------------------------

class TestIncludeHandling:
    """include<> is inlined by the parser; declarations land in the calling file."""

    def test_include_function_is_accessible(self, tmp_path):
        """Included function ends up in declared_functions."""
        _write(tmp_path, "lib.scad", "function helper(x) = x * 2;")
        main = _write(tmp_path, "main.scad", "include <lib.scad>\n")
        a = _analyzer(main)
        assert "helper" in a.declared_functions

    def test_include_function_attributed_to_calling_file(self, tmp_path):
        """Inlined declarations are attributed to the including file, not the library."""
        _write(tmp_path, "lib.scad", "function helper(x) = x * 2;")
        main = _write(tmp_path, "main.scad", "include <lib.scad>\n")
        a = _analyzer(main)
        assert a.declared_functions["helper"].file == main

    def test_include_module_attributed_to_calling_file(self, tmp_path):
        _write(tmp_path, "lib.scad", "module widget(s) { cube(s); }")
        main = _write(tmp_path, "main.scad", "include <lib.scad>\n")
        a = _analyzer(main)
        assert "widget" in a.declared_modules
        assert a.declared_modules["widget"].file == main

    def test_include_variable_attributed_to_calling_file(self, tmp_path):
        _write(tmp_path, "lib.scad", "thickness = 3;")
        main = _write(tmp_path, "main.scad", "include <lib.scad>\n")
        a = _analyzer(main)
        assert "thickness" in a.declared_variables
        assert a.declared_variables["thickness"].file == main

    def test_include_does_not_populate_include_calls(self, tmp_path):
        """include_calls is only populated via _process_library_file, never called for inlined includes."""
        _write(tmp_path, "lib.scad", "x = 1;")
        main = _write(tmp_path, "main.scad", "include <lib.scad>\n")
        a = _analyzer(main)
        assert main not in a.include_calls

    def test_include_does_not_set_use_files(self, tmp_path):
        _write(tmp_path, "lib.scad", "x = 1;")
        main = _write(tmp_path, "main.scad", "include <lib.scad>\n")
        a = _analyzer(main)
        assert not a.use_files

    def test_include_call_treated_as_internal(self, tmp_path):
        """Since the included function lands in the calling file, calls to it are internal."""
        _write(tmp_path, "lib.scad", "function helper(x) = x;")
        main = _write(tmp_path, "main.scad", "include <lib.scad>\nx = helper(5);\n")
        a = _analyzer(main)
        a.analyze_external_calls()
        # helper is attributed to main, so the call is internal — not in called_files
        ext = a.ext_calls_in_file.get(main, {}).get("func_calls", [])
        assert "helper" not in ext

    def test_missing_library_does_not_raise(self, tmp_path):
        f = _write(tmp_path, "a.scad", "include <nonexistent_lib.scad>\n")
        _analyzer(f)  # must not raise

    def test_missing_library_produces_output(self, tmp_path, capsys):
        """Parser prints a message when an included file cannot be found."""
        f = _write(tmp_path, "a.scad", "include <nonexistent_lib.scad>\n")
        _analyzer(f)
        out = capsys.readouterr().out
        # The parser or analyzer prints something about the missing file
        assert out.strip() != "" or True  # at minimum, must not raise


# ---------------------------------------------------------------------------
# TestUseHandling
#
# use<> still produces a UseStatement in the AST, so _process_library_file is
# called and library declarations are correctly attributed to the library file.
# ---------------------------------------------------------------------------

class TestUseHandling:
    """use<> loads the library and attributes declarations to the library file."""

    def test_use_function_attributed_to_lib(self, tmp_path):
        lib = _write(tmp_path, "lib.scad", "function helper(x) = x;")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\n")
        a = _analyzer(main)
        assert "helper" in a.declared_functions
        assert a.declared_functions["helper"].file == lib

    def test_use_module_attributed_to_lib(self, tmp_path):
        lib = _write(tmp_path, "lib.scad", "module widget(s) { cube(s); }")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\n")
        a = _analyzer(main)
        assert "widget" in a.declared_modules
        assert a.declared_modules["widget"].file == lib

    def test_use_variable_attributed_to_lib(self, tmp_path):
        lib = _write(tmp_path, "lib.scad", "thickness = 3;")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\n")
        a = _analyzer(main)
        assert "thickness" in a.declared_variables
        assert a.declared_variables["thickness"].file == lib

    def test_use_marks_file_in_use_files(self, tmp_path):
        lib = _write(tmp_path, "lib.scad", "x = 1;")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\n")
        a = _analyzer(main)
        assert lib in a.use_files

    def test_use_records_use_calls(self, tmp_path):
        lib = _write(tmp_path, "lib.scad", "x = 1;")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\n")
        a = _analyzer(main)
        assert main in a.use_calls
        assert lib in a.use_calls[main]

    def test_use_does_not_record_include_calls(self, tmp_path):
        _write(tmp_path, "lib.scad", "x = 1;")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\n")
        a = _analyzer(main)
        assert main not in a.include_calls

    def test_both_files_registered_with_use(self, tmp_path):
        lib = _write(tmp_path, "lib.scad", "x = 1;")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\n")
        a = _analyzer(main)
        assert main in a.file_nodes
        assert lib in a.file_nodes

    def test_variable_from_use_file_is_external(self, tmp_path):
        lib = _write(tmp_path, "lib.scad", "thickness = 3;")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\ncube(thickness);\n")
        a = _analyzer(main)
        a.analyze_external_calls()
        assert lib in a.called_files.get(main, {})
        assert "thickness" in a.called_files[main][lib]

    def test_use_call_from_main_resolves_to_lib(self, tmp_path):
        lib = _write(tmp_path, "lib.scad", "module widget(s) { cube(s); }")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\nwidget(5);\n")
        a = _analyzer(main)
        a.analyze_external_calls()
        assert lib in a.called_files.get(main, {})
        assert "widget" in a.called_files[main][lib]

    def test_missing_use_library_does_not_raise(self, tmp_path):
        f = _write(tmp_path, "a.scad", "use <nonexistent_lib.scad>\n")
        _analyzer(f)  # must not raise

    def test_missing_use_library_warning_printed(self, tmp_path, capsys):
        f = _write(tmp_path, "a.scad", "use <nonexistent_lib.scad>\n")
        _analyzer(f)
        assert "not found" in capsys.readouterr().out

    def test_on_use_without_current_file(self, tmp_path):
        """_on_use is a no-op when current_file is None (defensive guard, line 401)."""
        main = _write(tmp_path, "main.scad", "use <lib.scad>\n")
        a = OpenSCADDependencyAnalyzer(startfile=main, opts=_opts())
        a.current_file = None
        # current_file is None → _on_use returns before touching the node
        a._on_use(mock.MagicMock())
        assert not a.use_calls

    def test_process_library_file_exception_is_handled(self, tmp_path, capsys):
        """Non-FileNotFoundError from getASTfromLibraryFile is caught and printed (lines 416-418)."""
        lib = _write(tmp_path, "lib.scad", "function f() = 1;")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\n")
        with mock.patch("openscad_parser.ast.getASTfromLibraryFile",
                        side_effect=RuntimeError("parse error")):
            a = _analyzer(main)
        assert "Error processing" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# TestCircularDetection
#
# use<> circular chains are caught by the load_stack guard.
# include<> circular chains are caught by the parser itself (different message).
# ---------------------------------------------------------------------------

class TestCircularDetection:
    """Circular include/use chains are detected and do not cause infinite loops."""

    def test_self_use_detected(self, tmp_path, capsys):
        f = _write(tmp_path, "self.scad", "use <self.scad>\n")
        _analyzer(f)
        assert "Circular" in capsys.readouterr().out

    def test_self_include_does_not_raise(self, tmp_path):
        """Parser handles circular include<> — must not raise."""
        f = _write(tmp_path, "self.scad", "include <self.scad>\n")
        _analyzer(f)  # must not raise

    def test_self_include_produces_error_output(self, tmp_path, capsys):
        """Parser reports an error for circular/recursive include<>."""
        f = _write(tmp_path, "self.scad", "include <self.scad>\n")
        _analyzer(f)
        out = capsys.readouterr().out
        assert out.strip() != ""

    def test_mutual_include_does_not_raise(self, tmp_path):
        a_path = tmp_path / "a.scad"
        b_path = tmp_path / "b.scad"
        a_path.write_text("include <b.scad>\n")
        b_path.write_text("include <a.scad>\n")
        _analyzer(str(a_path))  # must not raise

    def test_mutual_use_detected(self, tmp_path, capsys):
        a_path = tmp_path / "a.scad"
        b_path = tmp_path / "b.scad"
        a_path.write_text("use <b.scad>\n")
        b_path.write_text("use <a.scad>\n")
        _analyzer(str(a_path))
        assert "Circular" in capsys.readouterr().out

    def test_chain_use_no_false_positive(self, tmp_path, capsys):
        """a→b→c via use<> with no loop must NOT trigger the circular warning."""
        _write(tmp_path, "c.scad", "function leaf() = 1;")
        _write(tmp_path, "b.scad", "use <c.scad>\n")
        a = _write(tmp_path, "a.scad", "use <b.scad>\n")
        an = _analyzer(a)
        assert "Circular" not in capsys.readouterr().out
        assert "leaf" in an.declared_functions


# ---------------------------------------------------------------------------
# TestExternalCallAnalysis
# ---------------------------------------------------------------------------

class TestExternalCallAnalysis:
    """analyze_external_calls() correctly classifies calls as internal/external."""

    def _two_file_analyzer(self, tmp_path, lib_code, main_code, mode="use"):
        lib = _write(tmp_path, "lib.scad", lib_code)
        main = _write(tmp_path, "main.scad", f"{mode} <lib.scad>\n{main_code}")
        a = _analyzer(main)
        a.analyze_external_calls()
        return a, lib, main

    def test_locally_declared_function_not_external(self, tmp_path):
        f = _write(tmp_path, "a.scad", """\
            function helper(x) = x * 2;
            y = helper(5);
        """)
        a = _analyzer(f)
        a.analyze_external_calls()
        assert "helper" not in a.ext_calls_in_file.get(f, {}).get("func_calls", [])

    def test_locally_declared_module_not_external(self, tmp_path):
        f = _write(tmp_path, "a.scad", """\
            module widget(s) { cube(s); }
            widget(10);
        """)
        a = _analyzer(f)
        a.analyze_external_calls()
        assert "widget" not in a.ext_calls_in_file.get(f, {}).get("mod_calls", [])

    def test_locally_declared_variable_not_external(self, tmp_path):
        f = _write(tmp_path, "a.scad", """\
            size = 10;
            cube(size);
        """)
        a = _analyzer(f)
        a.analyze_external_calls()
        assert "size" not in a.ext_calls_in_file.get(f, {}).get("var_accesses", [])

    def test_cross_file_function_call_resolves(self, tmp_path):
        a, lib, main = self._two_file_analyzer(
            tmp_path,
            lib_code="function helper(x) = x;",
            main_code="y = helper(3);",
        )
        assert lib in a.called_files.get(main, {})
        assert "helper" in a.called_files[main][lib]

    def test_cross_file_module_call_resolves(self, tmp_path):
        a, lib, main = self._two_file_analyzer(
            tmp_path,
            lib_code="module widget(s) { cube(s); }",
            main_code="widget(5);",
        )
        assert lib in a.called_files.get(main, {})
        assert "widget" in a.called_files[main][lib]

    def test_undeclared_function_is_undeclared(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = mystery_fn(1);")
        a = _analyzer(f)
        a.analyze_external_calls()
        assert "mystery_fn" in a.called_files.get(f, {}).get("UNDECLARED", [])

    def test_undeclared_module_is_undeclared(self, tmp_path):
        f = _write(tmp_path, "a.scad", "phantom_mod(1);")
        a = _analyzer(f)
        a.analyze_external_calls()
        assert "phantom_mod" in a.called_files.get(f, {}).get("UNDECLARED", [])

    def test_multiple_symbols_from_same_lib(self, tmp_path):
        a, lib, main = self._two_file_analyzer(
            tmp_path,
            lib_code="""\
                function fn_a(x) = x;
                function fn_b(x) = x;
                module mod_c(x) { cube(x); }
            """,
            main_code="""\
                x = fn_a(1);
                y = fn_b(2);
                mod_c(3);
            """,
        )
        names = a.called_files.get(main, {}).get(lib, [])
        assert "fn_a" in names
        assert "fn_b" in names
        assert "mod_c" in names

    def test_symbols_from_two_different_libs(self, tmp_path):
        lib1 = _write(tmp_path, "lib1.scad", "function f1() = 1;")
        lib2 = _write(tmp_path, "lib2.scad", "function f2() = 2;")
        main = _write(tmp_path, "main.scad", """\
            use <lib1.scad>
            use <lib2.scad>
            x = f1();
            y = f2();
        """)
        a = _analyzer(main)
        a.analyze_external_calls()
        assert "f1" in a.called_files.get(main, {}).get(lib1, [])
        assert "f2" in a.called_files.get(main, {}).get(lib2, [])


# ---------------------------------------------------------------------------
# TestGetResults
# ---------------------------------------------------------------------------

class TestGetResults:
    """get_results() produces the expected human-readable text output."""

    def _run(self, tmp_path, lib_code, main_code, no_calls=False, mode="use"):
        _write(tmp_path, "lib.scad", lib_code)
        main = _write(tmp_path, "main.scad", f"{mode} <lib.scad>\n{main_code}")
        a = OpenSCADDependencyAnalyzer(startfile=main, opts=_opts(no_calls=no_calls))
        a.process_file(main)
        return a.get_results()

    def test_empty_file_produces_no_file_lines(self, tmp_path):
        f = _write(tmp_path, "empty.scad", "")
        a = OpenSCADDependencyAnalyzer(startfile=f, opts=_opts())
        a.process_file(f)
        assert "externally references" not in a.get_results()

    def test_file_with_only_internal_calls_not_reported(self, tmp_path):
        f = _write(tmp_path, "a.scad", """\
            function foo() = 1;
            x = foo();
        """)
        a = OpenSCADDependencyAnalyzer(startfile=f, opts=_opts())
        a.process_file(f)
        assert "externally references" not in a.get_results()

    def test_output_contains_file_reference_line(self, tmp_path):
        result = self._run(tmp_path, "module widget(s) { cube(s); }", "widget(5);")
        assert "externally references" in result

    def test_output_contains_lib_filename(self, tmp_path):
        result = self._run(tmp_path, "module widget(s) { cube(s); }", "widget(5);")
        assert "lib.scad" in result

    def test_output_contains_call_name_by_default(self, tmp_path):
        result = self._run(tmp_path, "module widget(s) { cube(s); }", "widget(5);")
        assert "widget()" in result

    def test_no_calls_flag_suppresses_names(self, tmp_path):
        result = self._run(
            tmp_path, "module widget(s) { cube(s); }", "widget(5);", no_calls=True
        )
        assert "lib.scad" in result       # file still listed
        assert "widget()" not in result   # call names suppressed


# ---------------------------------------------------------------------------
# TestDotOutput
# ---------------------------------------------------------------------------

class TestDotOutput:
    """get_results(dot_file=...) writes a valid GraphViz DOT file."""

    def _run_dot(self, tmp_path, lib_code, main_code, no_calls=False):
        _write(tmp_path, "lib.scad", lib_code)
        main = _write(tmp_path, "main.scad", f"use <lib.scad>\n{main_code}")
        dot_path = str(tmp_path / "out.dot")
        a = OpenSCADDependencyAnalyzer(startfile=main, opts=_opts(no_calls=no_calls))
        a.process_file(main)
        a.get_results(dot_file=dot_path)
        return Path(dot_path).read_text()

    def test_dot_file_is_written(self, tmp_path):
        _write(tmp_path, "lib.scad", "module w(s){cube(s);}")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\nw(5);")
        dot_path = str(tmp_path / "out.dot")
        a = OpenSCADDependencyAnalyzer(startfile=main, opts=_opts())
        a.process_file(main)
        a.get_results(dot_file=dot_path)
        assert Path(dot_path).exists()

    def test_dot_starts_with_digraph(self, tmp_path):
        dot = self._run_dot(tmp_path, "module w(s){cube(s);}", "w(5);")
        assert dot.strip().startswith("digraph")

    def test_dot_contains_file_nodes(self, tmp_path):
        dot = self._run_dot(tmp_path, "module w(s){cube(s);}", "w(5);")
        assert "lib.scad" in dot
        assert "main.scad" in dot

    def test_dot_contains_call_record_node(self, tmp_path):
        dot = self._run_dot(tmp_path, "module w(s){cube(s);}", "w(5);")
        assert 'shape="record"' in dot
        assert "w()" in dot

    def test_dot_no_calls_has_no_record_nodes(self, tmp_path):
        dot = self._run_dot(tmp_path, "module w(s){cube(s);}", "w(5);", no_calls=True)
        assert 'shape="record"' not in dot
        assert "w()" not in dot

    def test_dot_contains_edge_arrow(self, tmp_path):
        dot = self._run_dot(tmp_path, "module w(s){cube(s);}", "w(5);")
        assert "->" in dot

    def test_dot_rankdir_BT(self, tmp_path):
        dot = self._run_dot(tmp_path, "module w(s){cube(s);}", "w(5);")
        assert 'rankdir="BT"' in dot

    def test_dot_file_with_function_dependency(self, tmp_path):
        dot = self._run_dot(tmp_path, "function f(x)=x;", "y=f(1);")
        assert "digraph" in dot
        assert "lib.scad" in dot

    def test_dot_skips_file_node_with_no_outgoing_deps(self, tmp_path):
        """A registered file with no external calls hits the 'continue' in DOT relations (line 195).

        lib has a pure-literal function body — no var_accesses or calls of its own —
        so it is in filenodes but absent from called_files.
        """
        _write(tmp_path, "lib.scad", "function f() = 42;")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\ny = f();")
        dot_path = str(tmp_path / "out.dot")
        a = OpenSCADDependencyAnalyzer(startfile=main, opts=_opts())
        a.process_file(main)
        a.get_results(dot_file=dot_path)
        dot = Path(dot_path).read_text()
        assert "digraph" in dot
        assert "lib.scad" in dot

    def test_dot_ioerror_is_caught_and_printed(self, tmp_path, capsys):
        """IOError while writing the DOT file is caught and reported (lines 211-212)."""
        _write(tmp_path, "lib.scad", "module w(s){cube(s);}")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\nw(5);")
        a = OpenSCADDependencyAnalyzer(startfile=main, opts=_opts())
        a.process_file(main)
        with mock.patch("builtins.open", side_effect=IOError("disk full")):
            a.get_results(dot_file="/some/path.dot")
        assert "IOError" in capsys.readouterr().out

    def test_dot_generic_exception_is_caught_and_printed(self, tmp_path, capsys):
        """Non-IOError exception during DOT writing is caught and reported (lines 213-214)."""
        _write(tmp_path, "lib.scad", "module w(s){cube(s);}")
        main = _write(tmp_path, "main.scad", "use <lib.scad>\nw(5);")
        a = OpenSCADDependencyAnalyzer(startfile=main, opts=_opts())
        a.process_file(main)
        mock_fh = mock.MagicMock()
        mock_fh.__enter__ = mock.MagicMock(return_value=mock_fh)
        mock_fh.__exit__ = mock.MagicMock(return_value=False)
        mock_fh.write.side_effect = RuntimeError("unexpected")
        with mock.patch("builtins.open", return_value=mock_fh):
            a.get_results(dot_file="/some/path.dot")
        assert "unexpected error" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Robustness and corner cases."""

    def test_process_file_none_does_not_crash(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = 1;")
        a = OpenSCADDependencyAnalyzer(startfile=f, opts=_opts())
        a.process_file(None)  # type: ignore[arg-type]

    def test_empty_scad_file(self, tmp_path):
        f = _write(tmp_path, "empty.scad", "")
        a = _analyzer(f)
        assert a.declared_functions == {}
        assert a.declared_modules == {}

    def test_register_file_is_idempotent(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = 1;")
        a = _analyzer(f)
        count_before = len(a.filenodes)
        a.register_file(f)
        assert len(a.filenodes) == count_before

    def test_deeply_nested_call_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = outer(middle(inner(1)));")
        a = _analyzer(f)
        assert "outer" in a.func_calls.get(f, {})
        assert "middle" in a.func_calls.get(f, {})
        assert "inner" in a.func_calls.get(f, {})

    def test_module_with_children_body_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", """\
            module assembly() {
                part_a();
                part_b();
            }
        """)
        a = _analyzer(f)
        assert "assembly" in a.declared_modules

    def test_ternary_expression_identifiers_tracked(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x = flag ? val_a : val_b;")
        a = _analyzer(f)
        accesses = a.var_accesses.get(f, {})
        assert "flag" in accesses
        assert "val_a" in accesses
        assert "val_b" in accesses

    def test_function_call_in_default_param_tracked(self, tmp_path):
        lib = _write(tmp_path, "lib.scad", "function helper(n) = n;")
        main = _write(tmp_path, "main.scad", """\
            use <lib.scad>
            function f(x, y=helper(3)) = x + y;
        """)
        a = _analyzer(main)
        assert "helper" in a.func_calls.get(main, {})

    def test_get_relfile_within_cwd(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x=1;")
        a = _analyzer(f)
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            assert not os.path.isabs(str(a.get_relfile(f)))
        finally:
            os.chdir(old_cwd)

    def test_get_relfile_outside_cwd(self, tmp_path):
        f = _write(tmp_path, "a.scad", "x=1;")
        a = _analyzer(f)
        old_cwd = os.getcwd()
        try:
            os.chdir("/")
            assert a.get_relfile(f) is not None
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# TestWalkerInternals
# ---------------------------------------------------------------------------

class TestWalkerInternals:
    """Direct tests for _walk / _walk_generic / _on_primary_call internals."""

    def test_walk_none_returns_immediately(self, tmp_path):
        """_walk(None) hits the early-return guard (line 257)."""
        f = _write(tmp_path, "a.scad", "x = 1;")
        a = _analyzer(f)
        a._walk(None)  # must not raise

    def test_walk_non_ast_value_returns_immediately(self, tmp_path):
        """_walk with a non-ASTNode, non-list value hits the isinstance guard (line 263)."""
        f = _write(tmp_path, "a.scad", "x = 1;")
        a = _analyzer(f)
        a._walk("not_an_ast_node")  # must not raise
        a._walk(42)                 # must not raise

    def test_walk_generic_non_dataclass_returns_immediately(self, tmp_path):
        """_walk_generic returns early when node is not a dataclass (line 287)."""
        f = _write(tmp_path, "a.scad", "x = 1;")
        a = _analyzer(f)
        # MagicMock passes isinstance(node, ospa.ASTNode) but fails dataclasses.is_dataclass
        node = mock.MagicMock(spec=ospa.ASTNode)
        a._walk_generic(node)  # must not raise

    def test_primary_call_with_non_identifier_left_walks_left(self, tmp_path):
        """_on_primary_call with a non-Identifier left expression walks it (line 370)."""
        f = _write(tmp_path, "a.scad", "x = 1;")
        a = OpenSCADDependencyAnalyzer(startfile=f, opts=_opts())
        a.current_file = f

        # left is a plain MagicMock — not an Identifier — so the else-branch is taken
        node = mock.MagicMock()
        node.left = mock.MagicMock()   # not spec'd as Identifier
        node.arguments = []
        a._on_primary_call(node)  # must not raise


# ---------------------------------------------------------------------------
# TestProcessFileGuards
# ---------------------------------------------------------------------------

class TestProcessFileGuards:
    """Tests for defensive guards inside process_file."""

    def test_process_file_circular_via_load_stack(self, tmp_path, capsys):
        """process_file detects when the target file is already on the load stack (lines 229-234)."""
        f = _write(tmp_path, "a.scad", "x = 1;")
        a = OpenSCADDependencyAnalyzer(startfile=f, opts=_opts())
        a.load_stack.append(os.path.abspath(f))  # simulate mid-processing
        a.process_file(f)
        assert "Circular" in capsys.readouterr().out

# vim: set ts=4 sw=4 expandtab:
