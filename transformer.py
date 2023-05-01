import ast
import copy
import re
from bisect import bisect
from collections.abc import Generator
from contextlib import contextmanager
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
    # Nodes types that do not need to be processed further, i.e. need
    # no recursion or unparsing.
    as_is_node_types: Final[tuple[type[ast.AST], ...]] = (
        ast.Constant,
        ast.Name,
        ast.Attribute,
    )

    def __init__(self, source: str, node: ast.AST | None = None) -> None:
        super().__init__()
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
        self._source: str = source
        self._rewriter: Rewriter = Rewriter(source)
        self.tree = node or ast.parse(source, filename="<string>", mode="exec")

    def transform(self) -> str:
        self.visit(self.tree)
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
        if any(name.name == "typing" for name in node.names):
            self._imports.add(node)
            return node
        return self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
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
                    if isinstance(node.slice, ast.Constant) and isinstance(
                        node.slice.value, str
                    ):
                        # Optional["T"].
                        self._keep_imports_for.add("Optional")
                    else:
                        # Optional[T].
                        if isinstance(node.slice, self.as_is_node_types):
                            sub_str = ast.get_source_segment(self._source, node.slice)
                        else:
                            with self.sub_transformer(node.slice) as sub_transformer:
                                sub_str = sub_transformer.transform()
                        self.substitute(node, f"{sub_str} | None")
                        return node
                elif lhs == "Union":
                    if isinstance(node.slice, ast.Tuple):
                        if any(
                            isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            for elt in node.slice.elts
                        ):
                            # Union[X, "Y"]
                            self._keep_imports_for.add("Union")
                        else:
                            # Union[X, Y]
                            sub_strs: list[str] = []
                            for name in node.slice.elts:
                                if isinstance(node.slice, self.as_is_node_types):
                                    sub_strs.append(
                                        ast.get_source_segment(self._source, name)
                                    )
                                else:
                                    with self.sub_transformer(name) as sub_transformer:
                                        sub_strs.append(sub_transformer.transform())
                            self.substitute(node, " | ".join(sub_strs))
                            return node
                    elif isinstance(node.slice, ast.Constant):
                        # Union["X"].
                        self._keep_imports_for.add("Union")
                    else:
                        # Union[X].
                        self.substitute(
                            node,
                            ast.get_source_segment(self._source, node.slice),
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

    @contextmanager
    def sub_transformer(self, node: ast.AST) -> Generator["Transformer", None, None]:
        sub_tree = copy.deepcopy(node)
        ast.increment_lineno(sub_tree, -sub_tree.lineno + 1)
        DedentTransformer().transform(sub_tree)
        source = ast.get_source_segment(self._source, node)
        assert source is not None, f"Could not determine source segment for {node}"
        transformer = Transformer(source, sub_tree)
        yield transformer
        self._import_froms.update(transformer._import_froms)
        self._imports.update(transformer._imports)
        self._keep_imports_for.update(transformer._keep_imports_for)
        self._other_attrs_encountered = (
            self._other_attrs_encountered or transformer._other_attrs_encountered
        )


class DedentTransformer(ast.NodeTransformer):
    """
    Transformer to move the col_offset of a node to the start of the
    line, moving nodes behind it up as well.
    """

    def transform(self, node: ast.AST) -> None:
        self._n: int = node.col_offset
        self._lineno: int = node.lineno
        self.visit(node)

    def visit(self, node: ast.AST) -> ast.AST:
        if (lineno := getattr(node, "lineno", None)) and lineno == self._lineno:
            node.col_offset -= self._n
        if (
            end_lineno := getattr(node, "end_lineno", None)
        ) and end_lineno == self._lineno:
            node.end_col_offset -= self._n
        return super().visit(node)
