"""The format-neutral input every statement extraction receives.

Loaders turn raw uploads into a ``SourceDocument``: PDFs and images keep
their raw bytes (Claude reads them directly -- no text/OCR extraction
layer); spreadsheet and CSV exports become ``TABLE`` documents with one
tuple of cell strings per row. Extraction never touches raw upload bytes or
file formats, only this structure.
"""

from dataclasses import dataclass, field
from enum import Enum


class DocumentKind(str, Enum):
    """How the document's content is represented."""

    PDF = "PDF"
    IMAGE = "IMAGE"
    TABLE = "TABLE"


@dataclass(frozen=True)
class SourceDocument:
    """Content of one uploaded statement file, ready for extraction.

    ``PDF``/``IMAGE`` documents carry their raw bytes plus a media type, for
    direct inclusion in a Claude request as a document/image content block.
    ``TABLE`` documents carry rows instead, and no bytes -- cells are
    stringified as displayed in the source, so extraction owns all date and
    amount interpretation.
    """

    filename: str
    kind: DocumentKind
    data: bytes = b""
    media_type: str = ""
    rows: tuple[tuple[str, ...], ...] = field(default=())

    def __post_init__(self) -> None:
        if self.kind in (DocumentKind.PDF, DocumentKind.IMAGE):
            if not self.data:
                raise ValueError(f"{self.kind.value} documents must have data")
            if not self.media_type:
                raise ValueError(f"{self.kind.value} documents must have a media_type")
            if self.rows:
                raise ValueError(f"{self.kind.value} documents must not have rows")
        elif self.kind is DocumentKind.TABLE:
            if not self.rows:
                raise ValueError("TABLE documents must have rows")
            if self.data:
                raise ValueError("TABLE documents must not have data")
