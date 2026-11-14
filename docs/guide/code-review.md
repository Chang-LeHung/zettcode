# Code review

`/code-review` asks the model to review the uncommitted changes in the workspace, using a second session as the
reviewer. The command writes a brief and runs it as a turn of your conversation, as if you had typed it. Everything after
that is the model's work, guided by the brief.

```text
/code-review
/code-review the error handling in src/api.py
```

Whatever you type after the command is the focus. With nothing, the focus is "anything that would make this change wrong
or hard to keep". The transcript shows the command you typed, not the brief.

## What happens, step by step

1. **Collect the change.** The brief tells the model to run `git status --short` for what changed, `git diff HEAD` for the
   patch, and to read any untracked file that belongs to the change.
2. **Find or start a reviewer.** The model looks at `<daemon> list` for a reviewer of this workspace. The command names it
   `code-review`, and it reuses one if it is there: a reviewer that has read the earlier rounds already knows the change.
   Only when there is none does it run `<daemon> spawn --name code-review`. A reviewer started by a terminal on the same
   workspace is the one reused, because the name and the workspace are what `list` shows.
3. **Send the request.** The model sends the reviewer what to read with `send_message` and reports the answer when it
   arrives as a message. The brief asks for findings named as `file:line`: correctness, error handling, tests, naming, what
   to change and why, without restating the diff.
4. **Make the fixes, then go round again.** The reviewer stays up while the main agent changes what it found. The agent then
   sends it the new state of the change, and they repeat until the reviewer has nothing left to say.
5. **Every message says the reviewer must answer.** It sends findings back, or says in a word that there is nothing to
   change. A reviewer that goes quiet cannot be told apart from one whose review found nothing.
6. **When a round gets no answer.** The request is sent once more. If that is also unanswered, the model reads the
   reviewer's own conversation, `~/.zettcode/sessions/*/<session id>/data.jsonl`, where the last assistant message is its
   review. It reports that, then stops the reviewer with `<daemon> kill <session id>` so that it is not left running.
   `<daemon> list` shows what is running.
7. **If no daemon can be started,** the model says why and does the review itself.

`<daemon>` is the command of the installation the terminal itself runs on, `python -m zettcode.daemon` under the same
interpreter, not a `zettcode` looked up on the `PATH`. A checkout or a virtualenv that nothing else can see still
starts a reviewer.

## Which shell level the reviewer gets

The reviewer runs at **your own shell level**, never above it.

| Your level | The reviewer |
| --- | --- |
| `full` | Started at `full` |
| `safe` | Started at `safe` |
| `ask` | Started at `safe`: `ask` means "ask the reader", which a background process cannot do |
| `deny` | Not started: there is no shell to collect a diff with, so the model reviews by reading the files and says which ones |

The reviewer is told that it reads and does not change: no edits, no writes, no commits, no command that modifies the
workspace. The edits are the main agent's, made after the findings are in. That is an instruction, not a sandbox: a
reviewer at `full` could change things if it chose to.

## When not to use it

- The workspace is not a Git repository, or has nothing uncommitted: the brief collects the change with `git status` and
  `git diff HEAD`, so there is nothing for it to read.
- You want a review of a branch against another branch, or of a commit already made. The command reviews the uncommitted
  changes; give a focus that names what you want, or ask in ordinary words.
- You do not want a background session started. Each review uses a daemon and spends model tokens on the reviewer's turns
  as well as yours.

Each daemon is an ordinary stored session, so a reviewer that is left running stays listed in `zettcode daemon list` until
you stop it. See [Background agents](/guide/daemons) for starting, stopping and reading one.
