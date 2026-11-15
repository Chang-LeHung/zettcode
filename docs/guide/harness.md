# The JIT harness

With the harness on, the model can write a small Python tool for the task in front of you, load it, and call it in the
same turn. It is on by default.

## What happens

1. The model writes a tool into `~/.zettcode/harness/<workspace>/<session id>/`.
2. It loads the tool with `repo_load`. The code is imported in a child process, so a crash or a hang stays out of your
   session.
3. It calls the tool like any other. Each step is a row you can expand.

A session keeps one repository and reuses it.

## Turn it on or off

| How | Effect |
| --- | --- |
| `[harness] jit = false` | Start every run with the harness off. |
| `/plugins` | Switch it for the next start. |
| `/harness gen [description]` | Turn it on for this run and ask the model to build one tool for this workspace. |
| `/harness reset` | Turn it off for this run. Nothing is deleted. |

```toml
# ~/.zettcode/config.toml
[harness]
jit = false
```

```text
/harness gen list the TODO comments in this repository, grouped by file
```

`gen` passes your description to the model as the requirement. It also tells the model to keep its writes in the
harness folder and not to edit your project — an instruction, not a sandbox. It is refused while a request is running.

`/harness` opens a read-only table of every harness on the machine. `Tab` switches between harnesses, tools and files;
`Enter` lends another session's harness to this conversation.

## Where the code runs

| Shell level | Harness code runs |
| --- | --- |
| `full` | With your own access. |
| `safe`, `ask` | Inside the `safe` sandbox. |
| `deny` | Still runs, inside the `safe` sandbox: it is not a shell command. |

On a machine with no working sandbox, the harness says so once per session.

## The repository

A harness repository needs a `MANIFEST` beside `__init__.py`: a name, a version, a description and the tools it
declares. A `BAN_TOOLS` file lists tool names the repository may not define. `profile_tools` reports how each tool has
done — calls, success rate, time, input and output size, recent errors — read from the stored conversation, so it
survives a restart.

## Limits

- At `full` it is not a sandbox: the code has your access.
- `/harness reset` stops later requests from using the tools; it does not delete the files.
- A session open in another ZettCode process keeps its harness: `gen` there changes nothing.

Setting: [`harness.jit`](/guide/config#optional-settings-reference). Commands: [Commands](/guide/commands).
