"""Recognising the image files ``read`` hands to a model: by their first bytes, never by their name."""

from __future__ import annotations

#: The largest image file ``read`` returns.
MAX_IMAGE_BYTES = 10_000_000

#: Bytes needed to recognise every signature below.
SIGNATURE_BYTES = 12


def image_media_type(header: bytes) -> str | None:
    """Return the media type of a PNG, JPEG, GIF or WebP from the first bytes of a file, or ``None`` for anything else.

    A file's name says what its author meant; its first bytes say what it is, and a model rejects a picture
    announced as the wrong type. A file that is not one of the four is text as far as ``read`` is concerned.

    Args:
        header: At least :data:`SIGNATURE_BYTES` bytes from the start of the file (fewer for a short file).
    """
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    return None


__all__ = ["MAX_IMAGE_BYTES", "SIGNATURE_BYTES", "image_media_type"]
