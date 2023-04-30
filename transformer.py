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
            # The latest line no processed and the line that `_char_delta` applies to.
            self._lineno: int = 0
            # The number of characters nodes on this line will have shifted by.
            self._char_delta: int = 0
            # The number of lines that nodes will have moved since parsing.
            self._line_delta: int = 0
            # Set of typing imports encountered during the `visit` path that may need to be rewritten.
            self._imports: list[ast.ImportFrom] = []
            # Encounter deprecated types that should not be removed, since a special case was encountered.
            self._keep_imports_for: set[RemovedTyping] = set()
            self._has_changes: bool = False

            tree = ast.parse(source, filename="<string>", mode="exec")
            self.visit(tree)

            self.rewrite_imports()
            source = "\n".join(self._lines)

            if not self._has_changes:
                # Rather than making changes recursively, we're doing
                # multiple passes until no further changes are made.
                break
        while len(self._lines) and not self._lines[0]:
            del self._lines[0]
        source = "\n".join(self._lines)
        return source

    def rewrite_imports(self):
        """
        During the `visit` pass, import and usage is collected, but the
        source is not changed, as some uses of Optional and Union cannot
        be converted.
        """
        self._lineno = 0
        self._char_delta = 0
        self._line_delta = 0
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

    def substitute(self, node: ast.AST, text: str) -> None:
        self._has_changes = True
        if node.lineno + self._line_delta != self._lineno:
            self._char_delta = 0

        self._lineno = node.end_lineno + self._line_delta
        if (
            not text
            and node.lineno == node.end_lineno
            and node.col_offset == 0
            and node.end_col_offset
            == len(self._lines[node.lineno - 1 + self._line_delta])
        ):
            # Line deletion
            del self._lines[node.lineno - 1 + self._line_delta]
            return

        line = self._lines[node.lineno - 1 + self._line_delta]
        self._lines[node.lineno - 1 + self._line_delta] = (
            line[: node.col_offset + self._char_delta]
            + text
            + self._lines[node.end_lineno - 1 + self._line_delta][
                node.end_col_offset + self._char_delta :
            ]
        )
        if node.lineno == node.end_lineno:
            # Inline edit
            delta = len(text) - (node.end_col_offset - node.col_offset)
            self._char_delta += delta
        else:
            # Multi-line edit
            self._char_delta = node.col_offset + len(text) - node.end_lineno
            self._lineno = node.lineno + self._line_delta
            for lineno in range(node.end_lineno, node.lineno, -1):
                del self._lines[lineno - 1 + self._line_delta]
            self._line_delta -= node.end_lineno - node.lineno

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        if node.module == "typing":
            if any(alias.name in self.deprecated_types for alias in node.names):
                node.lineno += self._line_delta
                node.end_lineno += self._line_delta
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
                        return node
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
