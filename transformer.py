import ast
from typing import Final, Literal

RemovedTyping = Literal["Union", "Optional"]


class Transformer(ast.NodeTransformer):
    """
    NodeTransformer to replace all `Union[X, Y]` with `X | Y` and
    `Optional[X]` with `X | None`.
    """

    deprecated_types: Final[set[RemovedTyping]] = {"Union", "Optional"}

    def transform(self, source: str) -> str:
        while True:
            self._lines: list[str] = source.split("\n")
            self._lineno: int = 0
            self._char_delta: int = 0
            self._imports: list[ast.ImportFrom] = []
            self._keep_imports_for: set[RemovedTyping] = set()
            self.has_changes: bool = False

            tree = ast.parse(source, filename="<string>", type_comments=True)
            self.visit(tree)
            for import_node in self._imports:
                old_names = import_node.names
                import_node.names = [
                    alias
                    for alias in import_node.names
                    if alias.name not in self.deprecated_types
                    or alias.name in self._keep_imports_for
                ]
                if len(old_names) != len(import_node.names):
                    if not import_node.names:
                        self.substitute(import_node, "")
                    else:
                        self.substitute(import_node, ast.unparse(import_node))
            source = "\n".join(self._lines)

            if not self.has_changes:
                break

        return source

    def substitute(self, node: ast.AST, text: str) -> None:
        self.has_changes = True
        if node.lineno != self._lineno:
            self._char_delta = 0
        self._lineno = node.end_lineno
        line = self._lines[node.lineno - 1]
        self._lines[node.lineno - 1] = line[: node.col_offset + self._char_delta] + text
        if node.lineno == node.end_lineno:
            self._lines[node.lineno - 1] += line[
                node.end_col_offset + self._char_delta :
            ]
            delta = len(text) - (node.end_col_offset - node.col_offset)
        else:
            self._lines[node.lineno - 1] += "\\"
            self._lines[node.end_lineno - 1] = self._lines[node.end_lineno - 1][
                node.end_col_offset :
            ]
            self._char_delta = 0
            delta = -node.end_col_offset
        for lineno in range(node.lineno + 1, node.end_lineno):
            self._lines[lineno - 1] = "\\"
        self._char_delta += delta

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        if node.module == "typing":
            if any(alias.name in self.deprecated_types for alias in node.names):
                self._imports.append(node)
                return node
        return self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        if (
            isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.deprecated_types
        ):
            if node.value.id == "Optional":
                if isinstance(node.slice, ast.Constant):
                    # Optional["T"].
                    self._keep_imports_for.add("Optional")
                else:
                    # Optional[T].
                    self.substitute(node, f"{ast.unparse(node.slice)} | None")
                return node
            elif node.value.id == "Union":
                if isinstance(node.slice, ast.Tuple):
                    if any(isinstance(elt, ast.Constant) for elt in node.slice.elts):
                        # Union[X, "Y"]
                        self._keep_imports_for.add("Union")
                    else:
                        # Union[X, Y]
                        self.substitute(
                            node,
                            " | ".join([ast.unparse(name) for name in node.slice.elts]),
                        )
                elif isinstance(node.slice, ast.Constant):
                    # Union["X"].
                    self._keep_imports_for.add("Union")
                else:
                    # Union[X].
                    self.substitute(
                        node,
                        ast.unparse(node.slice),
                    )
                return node
        return self.generic_visit(node)
