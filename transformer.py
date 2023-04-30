import ast
from typing import Final


class Transformer(ast.NodeTransformer):
    """
    NodeTransformer to replace all `Union[X, Y]` with `X | Y` and
    `Optional[X]` with `X | None`.
    """

    deprecated_types: Final[set[str]] = {"Union", "Optional"}

    def transform(self, source: str, filename: str) -> str:
        self._lines = source.split("\n")
        self._lineno = 0
        self._char_delta = 0
        self.has_changes = False
        tree = ast.parse(source, filename=filename, type_comments=True)
        self.visit(tree)
        return self._source

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
                node.names = [
                    alias
                    for alias in node.names
                    if alias.name not in self.deprecated_types
                ]
                if not node.names:
                    self.substitute(node, "")
                    return None
                self.substitute(node, ast.unparse(node))
                return node
        return self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        if (
            isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.deprecated_types
        ):
            if node.value.id == "Optional":
                self.substitute(node, f"{ast.unparse(node.slice)} | None")
                return node
            elif node.value.id == "Union":
                self.substitute(
                    node,
                    " | ".join([ast.unparse(name) for name in node.slice.elts]),
                )
                return node
        return self.generic_visit(node)

    @property
    def _source(self) -> str:
        return "\n".join(self._lines)
