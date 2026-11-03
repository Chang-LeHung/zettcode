"""What a context budget is made of: the vocabulary the engine measures with and the views draw with.

A leaf with no imports, shared like :mod:`zettcode.statusline` and :mod:`zettcode.providers`, so the engine that counts
the request and the page that shows the count agree on the names without either importing the other.
"""

from __future__ import annotations

__all__ = ["CHARS_PER_TOKEN", "SOURCES"]

#: Characters per token when no tokenizer is available. The rule of thumb is close for English prose and low for CJK,
#: which is why a report names the estimate it used instead of presenting it as exact.
CHARS_PER_TOKEN = 4

#: One row per source, in the order the request is assembled.
SOURCES = (
    "System prompt",
    "Environment notes",
    "Tool schemas",
    "User messages",
    "Assistant messages",
    "Tool output",
    "Compaction summary",
)
