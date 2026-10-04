"""The glyphs the interface is written in.

One home for every non-ASCII character that carries meaning, so a piece of
punctuation can be changed once and a reader can look up what a shape is for.
A name says what the glyph *means*; the character is in the comment beside it.

Art a single widget owns stays with that widget: the welcome mark's box, the
plan panel's frame, a Markdown table's rules, the gallery's samples. This module
is the vocabulary, not the drawing.
"""

from __future__ import annotations

#: Between the parts of a status line, footer, or announcement: "\u00b7".
SEPARATOR = "\u00b7"

#: Where text was cut: "\u2026", one cell where "..." would take three.
ELLIPSIS = "\u2026"

#: The composer's prompt, and the mark in front of a user message: "\u203a".
PROMPT = "\u203a"

#: In front of the highlighted row of a list, of the step a plan is running,
#: and of a closed disclosure: "\u25b8".
MARKER = "\u25b8"

#: In front of an open disclosure, its closed form being :data:`MARKER`:
#: "\u25be".
EXPANDED = "\u25be"

#: In front of a plan step that has not started yet, where the dot stands for
#: the work rather than separating two things: "\u00b7".
PENDING = "\u00b7"

#: In front of a step that finished: "\u2713".
DONE = "\u2713"

#: In front of a row that failed: "\u00d7".
FAILED = "\u00d7"

#: In front of a step that was skipped: "\u2013", an en dash.
SKIPPED = "\u2013"

#: The idle status dot, and the fallback marker of a row whose state is
#: unknown: "\u25cf".
STATUS = "\u25cf"

#: Tokens the request spent and tokens the model generated, as in the status
#: line's counters: "\u2191" and "\u2193". The transcript's "back to bottom"
#: badge uses the same down arrow.
ARROW_UP = "\u2191"
ARROW_DOWN = "\u2193"

#: In front of the application name in the header: "\u25c8".
HEADER = "\u25c8"

#: What :class:`~zettcode.tui.widgets.text.Rule` repeats into a line: "\u2500".
RULE = "\u2500"

#: A determinate bar's filled and empty cells: "\u2588" and "\u2591".
BAR_FULL = "\u2588"
BAR_EMPTY = "\u2591"

#: The braille frames :class:`~zettcode.tui.widgets.progress.Spinner` cycles
#: through, from an empty to a nearly full run.
SPINNER = ("\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f")

#: The two states every running marker blinks between, in step: "\u2726" and
#: the plain dot.
RUNNING = ("\u2726", "\u00b7")
