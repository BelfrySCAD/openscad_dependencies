from typing import Dict, List, Optional, Any, Set
import os
import os.path
import argparse
import dataclasses
from pathlib import Path

import openscad_parser.ast as ospa


class ItemDecl():
    def __init__(self, name: str, file: Optional[str]) -> None:
        self.name = name
        self.file = file


class OpenSCADDependencyAnalyzer:
    def __init__(self, startfile: str, opts: Any = None) -> None:
        self.load_stack: List[str] = []
        self.opts = opts
        self.current_file: Optional[str] = None
        self.declared_functions: Dict[str, ItemDecl] = {}
        self.declared_modules: Dict[str, ItemDecl] = {}
        self.declared_variables: Dict[str, ItemDecl] = {}
        self.func_calls: Dict[str, Dict[str, ItemDecl]] = {}
        self.mod_calls: Dict[str, Dict[str, ItemDecl]] = {}
        self.var_accesses: Dict[str, Dict[str, ItemDecl]] = {}
        self.include_calls: Dict[str, List[str]] = {}
        self.use_calls: Dict[str, List[str]] = {}
        self.use_files: Set[str] = set()
        self.file_nodes: Dict[str, str] = {}
        self.node_files: Dict[str, str] = {}
        self.node_num: int = 1
        self.filenodes: List[str] = []
        self.ext_calls_in_file: Dict[str, Dict[str, List[str]]] = {}
        self.called_files: Dict[str, Dict[str, List[str]]] = {}

        # Built-in functions
        self.builtin_functions: Set[str] = {
            "concat", "lookup", "str", "chr", "ord", "search", "version",
            "version_num", "parent_module", "abs", "sign", "sin", "cos",
            "tan", "acos", "asin", "atan", "atan2", "floor", "round",
            "ceil", "ln", "len", "let", "log", "pow", "sqrt", "exp",
            "rands", "min", "max", "norm", "cross", "is_undef",
            "is_bool", "is_num", "is_string", "is_list", "is_function",
            "text_metrics",
        }

        # Built-in modules
        self.builtin_modules: Set[str] = {
            "render", "children", "circle", "square", "polygon", "text",
            "import", "projection", "sphere", "cube", "cylinder",
            "polyhedron", "linear_extrude", "rotate_extrude", "surface",
            "roof", "translate", "rotate", "scale", "resize", "mirror",
            "multmatrix", "color", "offset", "hull", "minkowski", "union",
            "difference", "intersection",
        }

    def get_relfile(self, filename: str) -> Path:
        try:
            cwpath = Path(os.getcwd())
            abspath = Path(filename)
            relpath = abspath.relative_to(cwpath)
        except ValueError:
            relpath = Path(filename)
        return relpath

    def register_file(self, filename: str) -> None:
        if filename not in self.file_nodes:
            node_name = f"file{self.node_num}"
            self.file_nodes[filename] = node_name
            self.node_files[node_name] = filename
            self.filenodes.append(node_name)
            self.node_num += 1

    def dot_node(self, name: str, indent: int = 4, **kwargs) -> str:
        out = " " * indent + name
        if kwargs:
            attr_str = ", ".join(
                '{}="{}"'.format(key, val.replace('\\', '\\\\').replace('"', '\\"'))
                for key, val in kwargs.items()
            )
            out += f" [{attr_str}]"
        out += "\n"
        return out

    def dot_edge(self, nodes: List[str], indent: int = 4, **kwargs) -> str:
        out = " " * indent
        out += " -> ".join(nodes)
        out += self.dot_node("", indent=0, **kwargs)
        return out

    def analyze_external_calls(self) -> None:
        files = sorted(list(set(
            list(self.func_calls.keys()) +
            list(self.mod_calls.keys()) +
            list(self.var_accesses.keys())
        )))
        self.ext_calls_in_file = {}
        for calling_file in files:
            ext_funcs = []
            if calling_file in self.func_calls:
                for called_func in self.func_calls[calling_file]:
                    item = self.declared_functions.get(called_func)
                    if item is None or item.file != calling_file:
                        ext_funcs.append(called_func)
            ext_funcs = sorted(list(set(ext_funcs)))

            ext_mods = []
            if calling_file in self.mod_calls:
                for name in self.mod_calls[calling_file]:
                    item = self.declared_modules.get(name)
                    if item is None or item.file != calling_file:
                        ext_mods.append(name)
            ext_mods = sorted(list(set(ext_mods)))

            ext_vars = []
            if calling_file in self.var_accesses:
                for var_name in self.var_accesses[calling_file]:
                    item = self.declared_variables.get(var_name)
                    if item is None or item.file != calling_file or item.file in self.use_files:
                        ext_vars.append(var_name)
            ext_vars = sorted(list(set(ext_vars)))

            self.ext_calls_in_file[calling_file] = {
                "func_calls": ext_funcs,
                "mod_calls": ext_mods,
                "var_accesses": ext_vars,
            }

        self.called_files = {}
        for calling_file in files:
            if calling_file not in self.ext_calls_in_file:
                continue

            if calling_file not in self.called_files:
                self.called_files[calling_file] = {}

            for called_function in self.ext_calls_in_file[calling_file]["func_calls"]:
                item = self.declared_functions.get(called_function)
                called_file = "UNDECLARED" if item is None else (item.file or "UNDECLARED")
                self.called_files[calling_file].setdefault(called_file, []).append(called_function)

            for called_module in self.ext_calls_in_file[calling_file]["mod_calls"]:
                item = self.declared_modules.get(called_module)
                called_file = "UNDECLARED" if item is None else (item.file or "UNDECLARED")
                self.called_files[calling_file].setdefault(called_file, []).append(called_module)

            for called_var in self.ext_calls_in_file[calling_file]["var_accesses"]:
                item = self.declared_variables.get(called_var)
                called_file = "UNDECLARED" if item is None else (item.file or "UNDECLARED")
                self.called_files[calling_file].setdefault(called_file, []).append(called_var)

    def get_results(self, dot_file: Optional[str] = None) -> str:
        out = "\n"

        self.analyze_external_calls()

        for filenode in self.filenodes:
            calling_file = self.node_files[filenode]
            if calling_file not in self.ext_calls_in_file:
                continue
            if not self.called_files.get(calling_file):
                continue

            relfile = self.get_relfile(calling_file)
            out += f"File '{relfile}' externally references:\n"

            for called_file in self.called_files[calling_file]:
                relfile = self.get_relfile(called_file)
                out += f"    {relfile}\n"
                if not self.opts.no_calls:
                    called_names = sorted(list(set(self.called_files[calling_file][called_file])))
                    calls = ", ".join(f"{n}()" for n in called_names)
                    out += f"        {calls}\n"

        if dot_file:
            try:
                with open(dot_file, "w") as f:
                    f.write('digraph Dependencies {\n')
                    f.write('    rankdir="BT"\n')
                    f.write('\n')
                    f.write('    // File nodes\n')
                    for filenode in self.filenodes:
                        calling_file = self.node_files[filenode]
                        relfile = str(self.get_relfile(calling_file)).replace('"', r'\"')
                        f.write(self.dot_node(filenode, label=relfile))

                    f.write('\n')
                    f.write('    // Relations\n')
                    callnode_num = 1
                    for filenode in self.filenodes:
                        calling_file = self.node_files[filenode]
                        if calling_file not in self.called_files:
                            continue
                        for called_file in self.called_files[calling_file]:
                            nodelist = [filenode]
                            if not self.opts.no_calls:
                                called_names = sorted(list(set(self.called_files[calling_file][called_file])))
                                calls = " | ".join(f"{n}()" for n in called_names)
                                callnode = f"calls{callnode_num}"
                                callnode_num += 1
                                f.write(self.dot_node(callnode, shape="record", label=f"{{{calls}}}"))
                                nodelist.append(callnode)
                            to_node = self.file_nodes.get(called_file)
                            if to_node is not None:
                                nodelist.append(to_node)
                            f.write(self.dot_edge(nodelist))

                    f.write("}\n")
            except IOError as e:
                print(f"An IOError occurred: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")

        return out

    def _print_syntax_error(self, file: str, error: Exception) -> None:
        print(f"Error processing {file}: {error}")

    def process_file(self, filepath: str) -> None:
        """Parse and walk a top-level file, tracking its declarations and calls."""
        if filepath is None:
            return

        abs_filepath = os.path.abspath(filepath)

        if abs_filepath in self.load_stack:
            print("Circular include/use detected:")
            start_at = self.load_stack.index(abs_filepath)
            for stackfile in self.load_stack[start_at:]:
                print(f"  {stackfile}")
            print()
            return

        self.load_stack.append(abs_filepath)
        old_file = self.current_file
        self.current_file = abs_filepath

        try:
            ast = ospa.getASTfromFile(abs_filepath)
            self.register_file(abs_filepath)
            self._walk(ast)
        except Exception as e:
            self._print_syntax_error(abs_filepath, e)
        finally:
            self.current_file = old_file
            self.load_stack.pop()

    # -------------------------------------------------------------------------
    # Typed AST Walker
    # -------------------------------------------------------------------------

    def _walk(self, node: Any) -> None:
        """Recursively walk an AST node or list of nodes, dispatching by type."""
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                self._walk(item)
            return
        if not isinstance(node, ospa.ASTNode):
            return

        if isinstance(node, ospa.FunctionDeclaration):
            self._on_function_decl(node)
        elif isinstance(node, ospa.ModuleDeclaration):
            self._on_module_decl(node)
        elif isinstance(node, ospa.Assignment):
            self._on_assignment(node)
        elif isinstance(node, ospa.IncludeStatement):
            self._on_include(node)
        elif isinstance(node, ospa.UseStatement):
            self._on_use(node)
        elif isinstance(node, ospa.ModularCall):
            self._on_modular_call(node)
        elif isinstance(node, ospa.PrimaryCall):
            self._on_primary_call(node)
        elif isinstance(node, ospa.Identifier):
            self._on_identifier(node)
        else:
            self._walk_generic(node)

    def _walk_generic(self, node: ospa.ASTNode) -> None:
        """Walk all ASTNode-typed dataclass fields of a node generically."""
        if not dataclasses.is_dataclass(node):
            return
        for field in dataclasses.fields(node):
            if field.name == 'position':
                continue
            val = getattr(node, field.name, None)
            if isinstance(val, ospa.ASTNode):
                self._walk(val)
            elif isinstance(val, list):
                for item in val:
                    if item is not None:
                        self._walk(item)

    def _walk_args(self, arguments: List[ospa.Argument]) -> None:
        """Walk only the value expressions of a list of Argument nodes.

        Named argument labels (the `name` Identifier) are skipped because they
        are parameter references, not variable accesses.
        """
        for arg in arguments:
            if isinstance(arg, ospa.PositionalArgument):
                self._walk(arg.expr)
            elif isinstance(arg, ospa.NamedArgument):
                self._walk(arg.expr)

    def _walk_params(self, parameters: List[ospa.ParameterDeclaration]) -> None:
        """Walk only the default-value expressions of parameter declarations.

        Parameter names are definitions, not variable accesses, so they are skipped.
        """
        for param in parameters:
            if param.default is not None:
                self._walk(param.default)

    # -------------------------------------------------------------------------
    # Declaration handlers
    # -------------------------------------------------------------------------

    def _on_function_decl(self, node: ospa.FunctionDeclaration) -> None:
        """Record a function declaration and walk its default values and body."""
        name = node.name.name
        self.declared_functions[name] = ItemDecl(name, self.current_file)
        self._walk_params(node.parameters)
        self._walk(node.expr)

    def _on_module_decl(self, node: ospa.ModuleDeclaration) -> None:
        """Record a module declaration and walk its default values and body."""
        name = node.name.name
        self.declared_modules[name] = ItemDecl(name, self.current_file)
        self._walk_params(node.parameters)
        self._walk(node.children)

    def _on_assignment(self, node: ospa.Assignment) -> None:
        """Record a variable assignment and walk its value expression."""
        name = node.name.name
        self.declared_variables[name] = ItemDecl(name, self.current_file)
        self._walk(node.expr)

    # -------------------------------------------------------------------------
    # Call handlers
    # -------------------------------------------------------------------------

    def _on_modular_call(self, node: ospa.ModularCall) -> None:
        """Record a non-builtin module call and walk its arguments and children."""
        name = node.name.name
        if name not in self.builtin_modules and self.current_file:
            self.mod_calls.setdefault(self.current_file, {})[name] = ItemDecl(name, self.current_file)
        self._walk_args(node.arguments)
        self._walk(node.children)

    def _on_primary_call(self, node: ospa.PrimaryCall) -> None:
        """Record a non-builtin function call and walk its arguments.

        When `left` is a bare Identifier the call is a direct named function
        call (e.g. ``foo(x)``).  For anything more complex (member access,
        chained call, etc.) we walk `left` normally so any identifiers inside
        it are still visited.
        """
        if isinstance(node.left, ospa.Identifier):
            name = node.left.name
            if name not in self.builtin_functions and self.current_file:
                self.func_calls.setdefault(self.current_file, {})[name] = ItemDecl(name, self.current_file)
        else:
            # e.g. obj.method(args) — walk the left-hand expression
            self._walk(node.left)
        self._walk_args(node.arguments)

    # -------------------------------------------------------------------------
    # Identifier (variable access) handler
    # -------------------------------------------------------------------------

    def _on_identifier(self, node: ospa.Identifier) -> None:
        """Record a variable reference.

        Identifiers that are part of declarations or call targets are never
        passed to this handler — they are consumed by the specific handlers
        above without recursing into the name field.
        """
        if self.current_file:
            name = node.name
            self.var_accesses.setdefault(self.current_file, {})[name] = ItemDecl(name, self.current_file)

    # -------------------------------------------------------------------------
    # include<> / use<> handlers
    # -------------------------------------------------------------------------

    def _on_include(self, node: ospa.IncludeStatement) -> None:
        """Handle an include<> statement."""
        if self.current_file is None:
            return
        self._process_library_file(self.current_file, node.filepath.val, is_use=False)

    def _on_use(self, node: ospa.UseStatement) -> None:
        """Handle a use<> statement."""
        if self.current_file is None:
            return
        self._process_library_file(self.current_file, node.filepath.val, is_use=True)

    def _process_library_file(self, caller_file: str, filepath: str, is_use: bool) -> None:
        """Resolve, register, and walk a library file from include<> or use<>.

        Declarations found inside the library are attributed to the library
        file itself (not to the caller), so that dependency edges correctly
        show which file defines each symbol.
        """
        try:
            ast, lib_file = ospa.getASTfromLibraryFile(caller_file, filepath)
        except FileNotFoundError:
            print(f"Warning: library file '{filepath}' not found.")
            return
        except Exception as e:
            self._print_syntax_error(caller_file, e)
            return

        lib_file = os.path.abspath(lib_file)
        verb = "Using" if is_use else "Including"
        print(f"{verb} {self.get_relfile(lib_file)}")

        if is_use:
            self.use_calls.setdefault(caller_file, []).append(lib_file)
            self.use_files.add(lib_file)
        else:
            self.include_calls.setdefault(caller_file, []).append(lib_file)

        self.register_file(lib_file)

        # Guard against circular includes
        if lib_file in self.load_stack:
            print("Circular include/use detected:")
            start_at = self.load_stack.index(lib_file)
            for stackfile in self.load_stack[start_at:]:
                print(f"  {stackfile}")
            print()
            return

        self.load_stack.append(lib_file)
        old_file = self.current_file
        self.current_file = lib_file
        try:
            self._walk(ast)
        finally:
            self.current_file = old_file
            self.load_stack.pop()


def main() -> None:
    arg_parser = argparse.ArgumentParser(prog='openscad_depends')
    arg_parser.add_argument('-d', '--dot-file', default=None,
                        help='Write a GraphViz style DOT digraph chart to the given file.')
    arg_parser.add_argument('-c', '--no-calls', action="store_true",
                        help="Suppress listing of called functions and module names.")
    arg_parser.add_argument('file', help='Input file.')

    opts = arg_parser.parse_args()

    visitor = OpenSCADDependencyAnalyzer(
        startfile=opts.file,
        opts=opts,
    )

    try:
        visitor.process_file(opts.file)
    except Exception as e:
        visitor._print_syntax_error(opts.file, e)

    print(visitor.get_results(dot_file=opts.dot_file))


if __name__ == "__main__":
    main()

# vim: set ts=4 sw=4 expandtab:
