"""What the shell catches from a command, and tells the reader in words."""

from __future__ import annotations

from zettcode.sdk.errors import ZettCodeError

__all__ = ["COMMAND_ERRORS"]

#: What a command may fail with and have the reader told in words: a bad argument (``ValueError``), or the SDK saying
#: the session is locked, busy or missing. Anything else is a bug and is reported as one. This is the shell's catch
#: clause and not part of what a plugin imports: a command raises, and the shell decides what a reader is told.
COMMAND_ERRORS = (ValueError, ZettCodeError)
