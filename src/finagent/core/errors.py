"""Domain-specific exceptions. The API layer maps these to HTTP responses."""


class FinAgentError(Exception):
    """Base class for all finagent-raised errors."""


class UnsupportedStatementError(FinAgentError):
    """Raised when no registered parser can handle a given statement."""


class ParseError(FinAgentError):
    """Raised when a parser recognizes a statement but fails to parse it."""


class ExtractionError(FinAgentError):
    """Raised when text/data extraction from a source document fails."""
