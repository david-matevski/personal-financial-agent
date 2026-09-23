"""The format-neutral input every statement parser receives.

Loaders turn raw uploads into a ``SourceDocument``: PDFs (text layer or OCR)
become ``TEXT`` documents with one string per page; spreadsheet and CSV
exports become ``TABLE`` documents with one tuple of cell strings per row.
Parsers never touch raw bytes or file formats, only this structure.
"""

from dataclasses import dataclass
from enum import Enum


class DocumentKind(str, Enum):
    """How the document's content is represented."""

    TEXT = "TEXT"
    TABLE = "TABLE"


@dataclass(frozen=True)
class SourceDocument:
    """Extracted content of one uploaded statement file.

    Exactly one of ``pages`` (for ``TEXT``) or ``rows`` (for ``TABLE``) is
    populated. Table cells are stringified as displayed in the source, so
    parsers own all date and amount interpretation.
    """

    filename: str
    kind: DocumentKind
    pages: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if self.kind is DocumentKind.TEXT and self.rows:
            raise ValueError("TEXT documents must not have rows")
        if self.kind is DocumentKind.TABLE and self.pages:
            raise ValueError("TABLE documents must not have pages")
