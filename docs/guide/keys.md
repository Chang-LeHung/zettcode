# Keys and mouse

The composer behaves like a Readline prompt, because that is what people
already know. The shell adds the keys that need the whole screen.

## A few workflows to try

- **Write a multi-line request:** type the first line, press `Alt-Enter` or
  `Shift-Enter`, add the next line, then `Enter` to send the whole draft. Some
  terminals do not distinguish `Shift-Enter`; use `Alt-Enter` in that case.
- **Fix the start of a line:** `Ctrl-A` moves to its start; edit it, then
  `Ctrl-E` returns to its end. This is line navigation, not select-all.
- **Reuse a request:** from an empty draft, press `Up` or `Ctrl-P` to recall a
  submitted input, edit it, then `Enter` to send a new request. `Ctrl-R` searches
  that input history; it does not search the assistant's answers.
- **Read an earlier answer:** scroll with the wheel or `Page Up`. `Esc` returns
  to the bottom without changing your draft.
- **Paste text or a picture:** use your terminal's usual paste shortcut for
  text (`Cmd-V` on many macOS terminals, `Ctrl-Shift-V` on many others).
  `Ctrl-V` inside ZettCode is specifically for image attachment, not text paste.

Shortcuts depend on what has focus: `Enter` in a picker selects a row rather
than sending a draft, and `Esc` closes that panel first. For interactive
approval and question panels, read the hint printed at the bottom.

## Sending

| Key | What it does |
| --- | --- |
| <kbd>Enter</kbd> | Send the draft, or run a slash command. |
| <kbd>Alt</kbd>+<kbd>Enter</kbd>, <kbd>Shift</kbd>+<kbd>Enter</kbd> | Insert a newline. |
| <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> | Complete the slash command being typed. |

## Editing

| Key | What it does |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>A</kbd> / <kbd>Ctrl</kbd>+<kbd>E</kbd>, <kbd>Home</kbd> / <kbd>End</kbd> | Start or end of the line. |
| <kbd>Ctrl</kbd>+<kbd>B</kbd> / <kbd>Ctrl</kbd>+<kbd>F</kbd>, <kbd>Left</kbd> / <kbd>Right</kbd> | One character. |
| <kbd>Alt</kbd>+<kbd>B</kbd> / <kbd>Alt</kbd>+<kbd>F</kbd>, <kbd>Ctrl</kbd>+<kbd>Left</kbd> / <kbd>Ctrl</kbd>+<kbd>Right</kbd> | One word. |
| <kbd>Ctrl</kbd>+<kbd>Home</kbd> / <kbd>Ctrl</kbd>+<kbd>End</kbd>, <kbd>Alt</kbd>+<kbd>&lt;</kbd> / <kbd>Alt</kbd>+<kbd>&gt;</kbd> | Start or end of the whole draft. |
| <kbd>Ctrl</kbd>+<kbd>U</kbd> / <kbd>Ctrl</kbd>+<kbd>K</kbd> | Delete to the start or end of the line. |
| <kbd>Ctrl</kbd>+<kbd>W</kbd> / <kbd>Alt</kbd>+<kbd>Backspace</kbd>, <kbd>Alt</kbd>+<kbd>D</kbd> | Delete the previous or next word. |
| <kbd>Ctrl</kbd>+<kbd>Y</kbd> | Paste the last text removed with a line or word deletion. |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>_</kbd> | Undo the latest edit. |
| <kbd>Up</kbd> / <kbd>Down</kbd> | Move between draft lines, then through submitted input. |
| <kbd>Ctrl</kbd>+<kbd>P</kbd> / <kbd>Ctrl</kbd>+<kbd>N</kbd> | Submitted input, directly. |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> | Search backward through submitted input. |

## The shell

| Key | What it does |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>C</kbd> | Copy the selection and clear it; with nothing selected, stop the running request; on an empty request, clear the draft. |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> | Delete forward — or exit, when the composer is empty and nothing is running. |
| <kbd>Ctrl</kbd>+<kbd>L</kbd> | Redraw the screen, for a terminal that lost its contents. |
| <kbd>Ctrl</kbd>+<kbd>T</kbd> | Expand or collapse the newest thinking block. |
| <kbd>Ctrl</kbd>+<kbd>V</kbd> | Attach an image from the clipboard. |
| <kbd>Page Up</kbd> / <kbd>Page Down</kbd> | Scroll the conversation, keeping the composer focused. |
| <kbd>Esc</kbd> | Jump back to the newest line when scrolled up; close a panel; close the command menu. |
| <kbd>Tab</kbd> | Accept the highlighted row in a panel or the command menu. |

## Answering a question

While the model waits on a question, these belong to its panel:

| Key | What it does |
| --- | --- |
| <kbd>Up</kbd> / <kbd>Down</kbd> | Move through the choices the model offered. |
| <kbd>Enter</kbd> | Act on the highlighted row: choose it (a one-answer question sends it), tick or untick it, or — on the `send` row — finish a multiple-choice answer. When you have typed instead, it sends what you typed. |
| Anything you type | Edits the answer line, which is what the model receives; the choices fold away for as long as you type, and `Up`/`Down` bring them back. |
| <kbd>Esc</kbd>, <kbd>Ctrl</kbd>+<kbd>C</kbd> | Decline: the model is told the question was cancelled. |

## Mouse

| Action | What it does |
| --- | --- |
| Wheel | Scroll the conversation. |
| Click a Thinking or Tool row | Expand or collapse it. |
| Drag in the transcript | Select text; the selection is copied on release, and dragging past the edge keeps extending it. |
| Drag on a panel, the header, or the status line | Copy the text painted there, which those surfaces never offered before. |
| Double-click | Select the whole row. |
| <kbd>Shift</kbd>+click | Extend the current selection. |

Hold your terminal's own modifier key (usually <kbd>Shift</kbd> or
<kbd>Alt</kbd>) if you want the terminal emulator's selection instead of
ZettCode's.
