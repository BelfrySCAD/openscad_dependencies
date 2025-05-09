import argparse

from openscad_parser import getOpenSCADParser
from arpeggio import PTNodeVisitor, visit_parse_tree, NoMatch
import os
import os.path
import platform


class ItemDecl():
    def __init__(self, name, args, file):
        self.name = name
        self.args = args
        self.file = file


class OpenSCADDependencyVisitor(PTNodeVisitor):
    def __init__(self, parser=None, defaults=True, debug=False):
        super().__init__(defaults=defaults, debug=debug)
        self.current_file = ""
        self.functions = {}
        self.modules = {}
        self.func_calls = {}
        self.mod_calls = {}
        self.parser = parser
        self.builtin_funcs = {}
        self.builtin_modules = {}
        for name in [
            "concat", "lookup", "str", "chr", "ord", "search", "version",
            "version_num", "parent_module", "abs", "sign", "sin", "cos",
            "tan", "acos", "asin", "atan", "atan2", "floor", "round",
            "ceil", "ln", "len", "let", "log", "pow", "sqrt", "exp",
            "rands", "min", "max", "norm", "cross", "is_undef",
            "is_bool", "is_num", "is_string", "is_list", "is_function",
            "text_metrics",
        ]:
            self.builtin_funcs[name] = 1
        for name in [
            "render", "children", "circle", "square", "polygon", "text",
            "import", "projection", "sphere", "cube", "cylinder",
            "polyhedron", "linear_extrude", "rotate_extrude", "surface",
            "roof", "translate", "rotate", "scale", "resize", "mirror",
            "multmatrix", "color", "offset", "hull", "minkowski", "union",
            "difference", "intersection",
        ]:
            self.builtin_modules[name] = 1

    def get_results(self):
        out = "External References:\n"
        files = sorted(
            list(set(
                list(self.func_calls.keys()) +
                list(self.mod_calls.keys())
            ))
        )
        for file in files:
            ext_funcs = []
            if file in self.func_calls:
                for name in self.func_calls[file].keys():
                    if name in self.functions:
                        item = self.functions[name]
                    else:
                        item = None
                    if item is None or item.file != file:
                        ext_funcs.append(name)
            ext_funcs = list(set(ext_funcs))
            ext_funcs.sort()
            ext_mods = []
            if file in self.mod_calls:
                for name in self.mod_calls[file]:
                    item = self.modules.get(name)
                    if item is None or item.file != file:
                        ext_mods.append(name)
            ext_mods = list(set(ext_mods))
            ext_mods.sort()
            if ext_funcs or ext_mods:
                out += "File: {}\n".format(file)
            if ext_funcs:
                out += "  Function Calls:\n"
                for name in ext_funcs:
                    item = self.functions.get(name, None)
                    if item is None:
                        out += "      {}() undefined\n".format(name)
                    else:
                        out += "      {}() defined in {}\n".format(
                            name, item.file)
            if ext_mods:
                out += "  Module Calls:\n"
                for name in ext_mods:
                    item = self.modules.get(name, None)
                    if item is None:
                        out += "      {}() undefined\n".format(name)
                    else:
                        out += "      {}() defined in {}\n".format(
                            name, item.file)
        return out

    def _find_libfile(self, currfile, libfile):
        dirs = []
        if currfile:
            dirs.append(os.path.dirname(currfile))
        pathsep = ":"
        dflt_path = ""
        if platform.system() == "Windows":
            dflt_path = r'My Documents\OpenSCAD\libraries'
            pathsep = ";"
        elif platform.system() == "Darwin":
            dflt_path = "$HOME/Documents/OpenSCAD/libraries"
        elif platform.system() == "Linux":
            dflt_path = "$HOME/.local/share/OpenSCAD/libraries"
        env = os.getenv("OPENSCADPATH", dflt_path)
        if env:
            for path in env.split(pathsep):
                dirs.append(path)
        for d in dirs:
            test_file = os.path.join(d, libfile)
            if os.path.isfile(test_file):
                return test_file
        return None

    def _print_syntax_error(self, file, e):
        snippet = e.parser.input[e.position-e.col+1:].split("\n")[0] + \
            "\n" + " "*(e.col-1) + "^"
        print("Syntax Error at {}, line {}, col {}:\n{}".format(
            file, e.line, e.col, snippet))

    def visit_use_stmt(self, node, children):
        oldfile = self.current_file
        self.current_file = self._find_libfile(oldfile, children[0])
        if self.current_file not in self.func_calls:
            self.func_calls[self.current_file] = {}
        if self.current_file not in self.mod_calls:
            self.mod_calls[self.current_file] = {}
        try:
            print("Using {}".format(self.current_file))
            with open(self.current_file, 'r') as f:
                parse_tree = self.parser.parse(f.read())
                visit_parse_tree(parse_tree, self)
        except NoMatch as e:
            self._print_syntax_error(self.current_file, e)
        self.current_file = oldfile
        return node

    def visit_include_stmt(self, node, children):
        oldfile = self.current_file
        self.current_file = self._find_libfile(oldfile, children[0])
        if self.current_file not in self.func_calls:
            self.func_calls[self.current_file] = {}
        if self.current_file not in self.mod_calls:
            self.mod_calls[self.current_file] = {}
        try:
            print("Including {}".format(self.current_file))
            with open(self.current_file, 'r') as f:
                parse_tree = self.parser.parse(f.read())
                visit_parse_tree(parse_tree, self)
        except NoMatch as e:
            self._print_syntax_error(self.current_file, e)
        self.current_file = oldfile
        return node

    def visit_module_def(self, node, children):
        name = children[0]
        args = None if len(children) < 2 else children[1]
        self.modules[name] = ItemDecl(name, args, self.current_file)
        return node

    def visit_function_def(self, node, children):
        name = children[0]
        args = None if len(children) < 2 else children[1]
        self.functions[name] = ItemDecl(name, args, self.current_file)
        return node

    def visit_modular_call(self, node, children):
        if len(children) > 1 and children[1][0] == '(':
            name = children[0]
            args = children[1]
            if name not in self.builtin_modules:
                if self.current_file not in self.mod_calls:
                    self.mod_calls[self.current_file] = {}
                self.mod_calls[self.current_file][name] = \
                    ItemDecl(name, args, self.current_file)
        return node

    def visit_prec_call(self, node, children):
        if len(children) > 1 and children[1][0] == '(':
            name = children[0]
            args = children[1]
            if name not in self.builtin_funcs:
                if self.current_file not in self.func_calls:
                    self.func_calls[self.current_file] = {}
                self.func_calls[self.current_file][name] = \
                    ItemDecl(name, args, self.current_file)
        return node

    def visit_parameter(self, node, children):
        name = children[0]
        dflt = children[1] if len(children) > 1 else None
        return (name, dflt)

    def visit_parameters(self, node, children):
        if len(children) < 1:
            return []
        return children

    def visit_TOK_COMMA(self, node, children):
        return None

    def visit_TOK_STRING(self, node, children):
        if len(children) < 1:
            return str("")
        return str(children[0])

    def visit_TOK_NUMBER(self, node, children):
        return float(node.value)

    def visit_lookup_expr(self, node, children):
        return None

    def visit_member_expr(self, node, children):
        return None

    def visit_call_expr(self, node, children):
        return node


def print_tree(node, level=0):
    indent = "  " * level
    if isinstance(node, list):
        print(indent + "[")
        for n in node:
            print_tree(n, level + 1)
        print(indent + "]")
    elif isinstance(node, tuple):
        print(indent + "(")
        for n in node:
            print_tree(n, level + 1)
        print(indent + ")")
    else:
        print(indent + "'" + str(node) + "'")
        if hasattr(node, ' value'):
            print(indent + "value: " + str(node.value))
        if hasattr(node, ' children'):
            print(indent + "children: ")
            for n in node.children:
                print_tree(n, level + 1)


def main():
    parser = argparse.ArgumentParser(prog='openscad_depends')
    parser.add_argument('file', help='Input file.')
    opts = parser.parse_args()

    parser = getOpenSCADParser(reduce_tree=True, debug=False)
    visitor = OpenSCADDependencyVisitor(debug=False, parser=parser)
    try:
        with open(opts.file, 'r') as f:
            visitor.current_file = opts.file
            parse_tree = parser.parse(f.read())
            # print_tree(parse_tree)
            visit_parse_tree(parse_tree, visitor)
    except NoMatch as e:
        visitor._print_syntax_error(opts.file, e)
    print(visitor.get_results())


if __name__ == "__main__":
    main()

# vim: set ts=4 sw=4 expandtab:
