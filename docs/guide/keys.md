# Keys and mouse

The composer is a Readline prompt. A key belongs to what has focus: `Enter` in a panel chooses a row instead of
sending a draft, and `Esc` closes the panel first. Each panel prints its own keys.

## Sending

| Key | What it does |
| --- | --- |
| <kbd>Enter</kbd> | Send the draft, or run a slash command. |
| <kbd>Alt</kbd>+<kbd>Enter</kbd>, <kbd>Shift</kbd>+<kbd>Enter</kbd> | Insert a newline. `Alt-Enter` works everywhere; `Shift-Enter` needs a terminal that reports it. |
| <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> | Complete the slash command. |

## Editing

| Key | What it does |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>A</kbd> / <kbd>Ctrl</kbd>+<kbd>E</kbd>, <kbd>Home</kbd> / <kbd>End</kbd> | Start or end of the line. |
| <kbd>Ctrl</kbd>+<kbd>B</kbd> / <kbd>Ctrl</kbd>+<kbd>F</kbd>, <kbd>Left</kbd> / <kbd>Right</kbd> | One character. |
| <kbd>Alt</kbd>+<kbd>B</kbd> / <kbd>Alt</kbd>+<kbd>F</kbd>, <kbd>Ctrl</kbd>+<kbd>Left</kbd> / <kbd>Ctrl</kbd>+<kbd>Right</kbd> | One word. |
| <kbd>Ctrl</kbd>+<kbd>Home</kbd> / <kbd>Ctrl</kbd>+<kbd>End</kbd>, <kbd>Alt</kbd>+<kbd>&lt;</kbd> / <kbd>Alt</kbd>+<kbd>&gt;</kbd> | Start or end of the whole draft. |
| <kbd>Ctrl</kbd>+<kbd>U</kbd> / <kbd>Ctrl</kbd>+<kbd>K</kbd> | Delete to the start or end of the line. |
| <kbd>Ctrl</kbd>+<kbd>W</kbd> / <kbd>Alt</kbd>+<kbd>Backspace</kbd>, <kbd>Alt</kbd>+<kbd>D</kbd> | Delete the previous or next word. |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>_</kbd> | Undo the latest edit. |
| <kbd>Up</kbd> / <kbd>Down</kbd> | Move between draft lines, then through submitted input. |
| <kbd>Ctrl</kbd>+<kbd>P</kbd> / <kbd>Ctrl</kbd>+<kbd>N</kbd> | Submitted input, directly. |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> | Search backward through submitted input. |

## The shell

| Key | What it does |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>C</kbd> | Copy the selection and clear it; with nothing selected, stop the request; on an empty draft, clear it. |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> | Delete forward, or exit when the composer is empty and nothing runs. |
| <kbd>Ctrl</kbd>+<kbd>L</kbd> | Redraw the screen, for a terminal that lost its contents. |
| <kbd>Ctrl</kbd>+<kbd>T</kbd> | Expand or collapse the newest thinking block. |
| <kbd>Ctrl</kbd>+<kbd>V</kbd> | Attach an image from the clipboard. A text paste uses the terminal's own key. |
| <kbd>Page Up</kbd> / <kbd>Page Down</kbd> | Scroll the conversation, keeping the composer focused. |
| <kbd>Alt</kbd>+<kbd>Up</kbd> / <kbd>Alt</kbd>+<kbd>Down</kbd> (also <kbd>Ctrl</kbd>+<kbd>Up</kbd> / <kbd>Ctrl</kbd>+<kbd>Down</kbd>) | Jump to your previous or next message, at the top of the view; while follow-ups wait, walk that list. |
| <kbd>Esc</kbd> | Stop the request; or first, return to the newest line, close a panel or the menu, or let go of a highlighted follow-up. |
| <kbd>Tab</kbd> | Accept the highlighted row in a panel or the command menu. |

## While a request runs

Typing during a request asks whether it steers the task or follows up. `Option` is the `⌥` key on a Mac and `Alt`
elsewhere.

| Key | What it does |
| --- | --- |
| <kbd>Enter</kbd> | Ask what the message is; in the question, take the highlighted row. |
| <kbd>F</kbd> / <kbd>S</kbd> | In the question: **f**ollow up or **s**teer directly. `Esc` keeps the draft. |
| <kbd>Option</kbd>+<kbd>Up</kbd> / <kbd>Option</kbd>+<kbd>Down</kbd> | With nothing highlighted: walk into the follow-up list. With a message highlighted: **move it** one place. |
| <kbd>Up</kbd> / <kbd>Down</kbd> | With a follow-up highlighted: move the highlight; `Down` past the last row returns to the composer. |
| <kbd>Enter</kbd> | With a follow-up highlighted: take it into the composer; sending puts it back in its place. |
| <kbd>Delete</kbd> / <kbd>Backspace</kbd> | With a follow-up highlighted: remove it. |
| <kbd>Esc</kbd> | With a follow-up highlighted: let go. Without: stop the request; the follow-ups stay, held until your next reply. |

A steering message cannot be changed once sent. [Typing while a request runs](/guide/interface#typing-while-a-request-runs)
has the rest.

## Answering a question

| Key | What it does |
| --- | --- |
| <kbd>Up</kbd> / <kbd>Down</kbd> | Move through the choices the model offered. |
| <kbd>Enter</kbd> | Act on the highlighted row: choose, tick or untick, or finish a multiple-choice answer. When you have typed, it sends that. |
| Anything you type | Edits the answer line; the choices fold away while you type, and `Up`/`Down` bring them back. |
| <kbd>Esc</kbd>, <kbd>Ctrl</kbd>+<kbd>C</kbd> | Decline: the model is told the question was cancelled. |

## Mouse

| Action | What it does |
| --- | --- |
| Wheel | Scroll the conversation. |
| Click a Thinking or Tool row | Expand or collapse it. |
| Drag in the transcript | Select text; it is copied on release, and a pill confirms it. Dragging past the edge keeps extending. |
| Drag on a panel, the header, or the status line | Copy the text painted there. |
| Double-click | Select the whole row. |
| <kbd>Shift</kbd>+click | Extend the current selection. |

Hold the terminal's own modifier key (usually <kbd>Shift</kbd> or <kbd>Alt</kbd>) for its selection instead.
