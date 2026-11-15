# Code review

`/code-review` has a second agent read the uncommitted changes in the workspace, while you keep the conversation. It
reuses a reviewer that is already running for this workspace, so a later round knows what the earlier one found.

```text
/code-review
/code-review the error handling in src/api.py
```

Text after the command is the focus. With none, it looks for anything that would make the change wrong or hard to keep.
The transcript shows what you typed, not the brief the model writes.

## What happens

1. The model collects the change with `git status --short`, `git diff HEAD`, and reads any untracked file that belongs
   to it.
2. It finds a reviewer for this workspace or starts one with `zettcode daemon spawn --name code-review`.
3. It sends the reviewer the request with `send_message`. The reviewer reports findings as `file:line`: correctness,
   error handling, tests, naming, what to change and why.
4. You make the fixes. The model sends the new state to the same reviewer, and they go round until it has nothing left.
5. Every request tells the reviewer to answer. If a round gets no answer, the request is sent once more; then the model
   reads the reviewer's last message from its stored conversation, reports it, and stops the reviewer.

The reviewer is told to read, not change: no edits, no writes, no commits. That is an instruction, not a sandbox.

## Which shell level the reviewer gets

The reviewer runs at your shell level, or at `safe` when yours is `ask`, because a background process has nobody to ask.

| Your level | The reviewer |
| --- | --- |
| `full` | `full` |
| `safe` | `safe` |
| `ask` | `safe` |
| `deny` | Not started; the model reads the files and says which ones |

## When not to use it

- The workspace is not a Git checkout, or has nothing uncommitted: there is no change to collect.
- You want a review of a branch or a commit, not the working tree.
- You do not want a second session spending tokens. A review uses a daemon until you stop it.

The reviewer is an ordinary stored session, listed by `zettcode daemon list` until it is stopped. See
[Background agents](/guide/daemons).
