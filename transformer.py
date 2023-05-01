import ast
import re
from bisect import bisect
from dataclasses import dataclass
from typing import Final, Literal

RemovedTyping = Literal["Union", "Optional"]


@dataclass
class DeleteLine:
    lineno: int


@dataclass
class Substitution:
    lineno: int
    end_lineno: int
    col_offset: int
    end_col_offset: int
    text: str


class ConflictingOperationsException(Exception):
    def __init__(self, a: Substitution, b: Substitution) -> None:
        super().__init__(f"Conflicting operations; {a} and {b} overlap")


FULL_LINE: Final[int] = -1


class Rewriter:
    """
    Allow the rewriting of the source file without having to keep track
    of line and column numbers and without having to perform operations
    in order.
    """

    def __init__(self, source: str) -> None:
        self.source: str = source
        self.operations: list[Substitution] = []

    @staticmethod
    def _sort_key(op: Substitution) -> tuple[int, int]:
        return op.lineno, op.col_offset

    def _check_overlaps(self, a: Substitution, b: Substitution):
        """
        Check for overlap between `a` and `b`, where `a` precedes `b in
        the sort order.
        """
        if a.end_lineno > b.lineno:
            raise ConflictingOperationsException(a, b)
        elif a.end_lineno == b.lineno and a.end_col_offset > b.col_offset:
            raise ConflictingOperationsException(a, b)

    def substitute(
        self,
        lineno: int,
        end_lineno: int,
        col_offset: int,
        end_col_offset: int,
        text: str,
    ):
        op = Substitution(
            lineno=lineno,
            end_lineno=end_lineno,
            col_offset=col_offset,
            end_col_offset=end_col_offset,
            text=text,
        )
        idx = bisect(self.operations, self._sort_key(op), key=self._sort_key)
        if idx > 0:
            self._check_overlaps(self.operations[idx - 1], op)
        if idx < len(self.operations):
            self._check_overlaps(op, self.operations[idx])
        self.operations.insert(idx, op)

    def get_result(self) -> str:
        lines = self.source.split("\n")
        for op in reversed(self.operations):
            if (
                not op.text
                and op.lineno == op.end_lineno
                and op.col_offset == 0
                and op.end_col_offset == len(lines[op.lineno - 1])
            ):
                del lines[op.lineno - 1]
            else:
                lines[op.lineno - 1] = (
                    lines[op.lineno - 1][: op.col_offset]
                    + op.text
                    + lines[op.end_lineno - 1][op.end_col_offset :]
                )
                for lineno in range(op.end_lineno, op.lineno, -1):
                    del lines[lineno - 1]
        return "\n".join(lines)


class Transformer(ast.NodeTransformer):
    """
    NodeTransformer to replace all `Union[X, Y]` with `X | Y` and
    `Optional[X]` with `X | None`.
    """

    rewritable_types: Final[set[RemovedTyping]] = {"Union", "Optional"}

    def transform(self, source: str) -> str:
        # List of typing imports encountered during the `visit` pass
        # that may need to be rewritten.
        self._import_froms: set[ast.ImportFrom] = set()
        self._imports: set[ast.Import] = set()
        # Whether an attribute was accessed on typing that was not
        # one of the replaceable, meaning the import can't be
        # removed.
        self._other_attrs_encountered = False
        # Keeps track of types that were used in such a way that it
        # couldn't be rewritten, meaning we can't remove the import.
        self._keep_imports_for: set[RemovedTyping] = set()
        self._first_pass = True
        while True:
            self._has_changes: bool = False
            self._rewriter: Rewriter = Rewriter(source)

            tree = ast.parse(source, filename="<string>", mode="exec")
            self.visit(tree)

            source = self._rewriter.get_result()
            self._first_pass = False

            if not self._has_changes:
                # Rather than making changes recursively, we're doing
                # multiple passes until no further changes can be made.
                break
        self.rewrite_imports()
        source = self._rewriter.get_result()
        return re.sub("^\n+", "", source)

    def rewrite_imports(self):
        """
        During the `visit` pass, imports and their uses are tracked, but
        for imports, the source is not changed until the entire file has
        been processed.
        """
        if not self._other_attrs_encountered:
            for import_node in self._imports:
                import_node.names = [
                    alias for alias in import_node.names if alias.name != "typing"
                ]
                if not import_node.names:
                    self.substitute(import_node, "")
                else:
                    self.substitute(import_node, ast.unparse(import_node))
        for import_from_node in self._import_froms:
            old_names = import_from_node.names
            import_from_node.names = [
                alias
                for alias in import_from_node.names
                if alias.name not in self.rewritable_types
                or alias.name in self._keep_imports_for
            ]
            if len(old_names) != len(import_from_node.names):
                if not import_from_node.names:
                    self.substitute(import_from_node, "")
                else:
                    self.substitute(import_from_node, ast.unparse(import_from_node))

    def substitute(self, node: ast.AST, text: str) -> None:
        self._has_changes = True
        self._rewriter.substitute(
            node.lineno, node.end_lineno, node.col_offset, node.end_col_offset, text
        )

    def visit_Import(self, node: ast.Import) -> ast.AST:
        if not self._first_pass:
            return node
        if any(name.name == "typing" for name in node.names):
            self._imports.add(node)
            return node
        return self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
        if not self._first_pass:
            return node
        if node.module == "typing":
            if any(alias.name in self.rewritable_types for alias in node.names):
                self._import_froms.add(node)
                return node
        return self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        if isinstance(node.ctx, ast.Load):
            lhs = ""
            if isinstance(node.value, ast.Name):
                lhs = node.value.id
            elif (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "typing"
            ):
                lhs = node.value.attr
            if lhs and lhs in self.rewritable_types:
                if lhs == "Optional":
                    if isinstance(node.slice, ast.Constant):
                        # Optional["T"].
                        self._keep_imports_for.add("Optional")
                    else:
                        # Optional[T].
                        self.substitute(node, f"{ast.unparse(node.slice)} | None")
                        return node
                elif lhs == "Union":
                    if isinstance(node.slice, ast.Tuple):
                        if any(
                            isinstance(elt, ast.Constant) for elt in node.slice.elts
                        ):
                            # Union[X, "Y"]
                            self._keep_imports_for.add("Union")
                        else:
                            # Union[X, Y]
                            self.substitute(
                                node,
                                " | ".join(
                                    [ast.unparse(name) for name in node.slice.elts]
                                ),
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

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "typing"
            and node.attr not in self.rewritable_types
        ):
            self._other_attrs_encountered = True
        return self.generic_visit(node)
