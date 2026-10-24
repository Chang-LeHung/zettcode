# One API, two languages

The Python SDK (`zettcode.sdk`) and the TypeScript client (`zettcode-client`, over `zettcode-server`) are the same
interface in two languages. A program that knows one should be able to guess the other. This page is the rule, and
`tests/test_client_parity.py` is what keeps it true.

## The rule

1. **Same operation, same name.** The TypeScript name is the Python name in camelCase: `check_models` is
   `checkModels`, `use_self_compaction` is `useSelfCompaction`, `name_it` is `nameIt`.
2. **Same grouping.** `client.sessions.list()` and `client.session.rename()` are spelled the same in both. Python's
   `Session` is the *current* conversation in TypeScript, because the server has exactly one.
3. **Keyword-only arguments are an options object.** `mentions(query, *, limit=50)` is `mentions(query, { limit })`;
   positional stay positional.
4. **Data keeps its field names.** A value the SDK returns has `snake_case` fields in Python, and the same fields on
   the wire and in TypeScript (`call_id`, `context_tokens`). Only methods and options are camelCase.
5. **Types have the same names**, and so do events: the wire `type` of an event is the snake_case of the Python class
   (`CompactionDelta` is `compaction_delta`).
6. **Errors keep their meaning.** Each SDK error is one HTTP status and one `code` (see below), and TypeScript raises
   one `ZettCodeError` carrying the `code`.

A difference is allowed only when the two languages cannot do the same thing, and it is written down in the two
lists at the top of `test_client_parity.py` with the reason. Adding a public method on either side that is neither
spelled the same nor listed fails the test.

## Where the languages must differ

| Python | TypeScript | Why |
| --- | --- | --- |
| `client.session` is a live `Session` (`id`, `title`, `usage`, `locked`, `path`, `current`) | `client.session.info()` returns that data | a property cannot be asynchronous |
| `await sessions.open(id)` returns a `Session` handle | returns the session's data; the server's current conversation changes | the server has one current session, so there is no handle per id |
| `join_sessions(callback)` | `messages()` lists what is waiting; `relay(id)` answers one | an HTTP client cannot be called back |
| `approve()` / `answer()` / `decline()` on the event | `run.approve(callId, …)` / `run.answer(callId, …)` | a remote event has no methods |
| `model`, `effort`, `permission`, `harness` properties | `settings()` returns all four; `use*` set one | one resource on the server |
| `add_model`, `update_model`, `remove_model` are functions of `zettcode.sdk` | methods of the client | they edit the server's configuration |
| `aclose()`, `closed`, `config`, `workspace` | — | the process, not the API |
| — | `health()`, `raw()`, `request()`, `runState()`, `cancelRun()` | the server's run registry and transport |

## Errors

| Python (`zettcode.sdk.errors`) | HTTP | `ZettCodeError.code` |
| --- | --- | --- |
| `SessionNotFoundError` | 404 | `not_found` |
| `SessionLockedError` | 409 | `locked` |
| `SessionBusyError` | 409 | `busy` |
| `NothingToDoError` | 409 | `nothing_to_do` |
| `ConfigurationError`, `ValueError` | 400 | `invalid` |
| `SendError` | 404 | `unreachable` |
| `RunTimeoutError` | 504 | `timeout` |
| `RunError` | 502 | `run` |
| anything else | 500 | `internal` |

`ClientClosedError` and `WorkspaceConflictError` are about a Python process and have no HTTP form.
