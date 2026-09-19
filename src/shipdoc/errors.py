"""M03 — exception types, and the mapping from an exception to an internal reason key.

`ReasonKey` itself is a data vocabulary and lives in `types.py`; it is re-exported here
so `from shipdoc.errors import ReasonKey` keeps working for callers that think of it as
part of the error surface.
"""
from __future__ import annotations

from shipdoc.types import ReasonKey


class ShipdocError(Exception): ...
class ConfigError(ShipdocError): ...            # startup, fatal
class IngestError(ShipdocError): ...
class ExtractionError(ShipdocError): ...
class DocumentTypeError(ShipdocError): ...
class MissingAttachmentError(ShipdocError): ...
class MissingValueError(ShipdocError): ...
class ClassificationConflict(ShipdocError): ...
class LLMUnavailable(ShipdocError): ...         # degraded mode, NOT fatal


_FOR_EXCEPTION: dict[type[BaseException], ReasonKey] = {
    MissingAttachmentError: ReasonKey.ERR_NO_ATTACHMENT,
    DocumentTypeError:      ReasonKey.ERR_BAD_DOC_TYPE,
    ExtractionError:        ReasonKey.ERR_UNREADABLE,
    IngestError:            ReasonKey.ERR_UNREADABLE,
    MissingValueError:      ReasonKey.ERR_NO_VALUE,
    ClassificationConflict: ReasonKey.ERR_CLASSIFY,
}


def reason_key(e: BaseException) -> ReasonKey:
    return _FOR_EXCEPTION.get(type(e), ReasonKey.ERR_UNHANDLED)


__all__ = [
    "ShipdocError", "ConfigError", "IngestError", "ExtractionError",
    "DocumentTypeError", "MissingAttachmentError", "MissingValueError",
    "ClassificationConflict", "LLMUnavailable", "ReasonKey", "reason_key",
]
