---
title: HTTP API reference
---

# HTTP API reference

Every endpoint answers JSON unless it says otherwise, and every failure uses the same shape:

```json
{"error": "busy", "message": "A run is already in progress; wait for it or cancel it"}
```

| `error` | Status | When |
| --- | --- | --- |
| `invalid` | 400 / 422 | A setting names something that does not exist; a body fails validation; a command holds a shell character. |
| `unauthorized` | 401 | The token is missing or wrong. |
| `not_found` | 404 | No such session, or no such plugin command. |
| `busy` | 409 | A run is in progress and this needs the conversation. |
| `locked` | 409 | Another process has the session open. |
| `nothing_to_do` | 409 | There is no interrupted request to continue. |
| `no_model` | 409 | No model is configured yet, so there is no agent to run a prompt with. Add one with `POST /models`. |
| `timeout` | 504 | The run's deadline passed. |
| `run` | 502 | The provider, or the run, failed. |
| `internal` | 500 | Anything else; the message is the SDK's. |

Except on `/health`, every endpoint requires `Authorization: Bearer <token>` when the server was started with one.

## Health

| Method | Path | Answers |
| --- | --- | --- |
| `GET` | `/health` | `{"status","version","workspace","ready","session","models","busy"}`; the only endpoint a token does not guard. `ready` is false until a model is configured, and `session` is null then. |
| `GET` | `/` | The name, version and the paths of the docs and health endpoints. |

## Models and settings

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| `GET` | `/models` | — | `{"models": [{"name","model","context_window","multimodal","efforts","active","compact_percent","web_search","web_search_name","display_model","base_url","api","temperature","can_search","search_name","provider","token_env"}], "current"}`. The file's models come first, then the ones plugins offer; `provider` names the plugin host, and is null for a file entry. `token_env` names the variable a provided model wanted but did not have set, and is null otherwise. Works before a model is configured, where `current` is null. |
| `POST` | `/models` | `{"model", "token"?, "display_model"?, "base_url"?, "anthropic"?, "responses_api"?, "chat"?, "multimodal"?, "temperature"?, "web_search"?, "web_search_name"?, "context_window"?, "compact_percent"?, "reasoning_efforts"?}` | 201 with the new list. The first model makes the server ready; later ones are available for `PATCH /settings`. Written to the configuration file, with the keys the terminal's `/config add` uses. `web_search` lets the provider search the web for the model; for a DeepSeek model it is refused unless `anthropic` is set, and a misspelt key is a `422`. |
| `PATCH` | `/models/{name}` | Any of the fields `POST /models` takes | The new list. A key left out stays as it is; the token is kept unless a new one is given. A key sent as `null` is removed from the entry (all but `model` and `token`): `"temperature": null` goes back to the provider's own, and `"anthropic": null` takes the flag out of the file instead of leaving `anthropic = false`. |
| `DELETE` | `/models/{name}` | — | The remaining models. The last model in the file cannot be removed (`400 invalid`) unless a plugin offers one; a model a plugin offers is not in the file and is not removed here. |
| `GET` | `/settings` | — | `{"model","effort","efforts","permission","permissions","harness"}`; after a `PATCH` that moved the compaction point it also has `"unsaved"` (see below). |
| `PATCH` | `/settings` | `{"model"?, "effort"?, "permission"?, "harness"?, "compact_percent"?}` | The same as `GET /settings`, after the change. At least one field. `permission` is `deny`, `ask`, `safe` or `full` (`auto` is the old name of `full` and is answered as `full`); `harness` turns the just-in-time tool harness on or off from the next prompt. `compact_percent` is above 0 and at most 100, applies from the next request and is written to the configuration file; when the file cannot be written the answer carries `"unsaved": "<why>"` and the change holds for this run only. Moving `compact_percent` is refused with `409` while a run is in progress; the other fields are not. |
| `GET` | `/plugins` | — | `{"loaded": [...], "failures": [...], "entries": [{"name","origin","required","enabled","failure","setting","switchable","why"}], "triggers": [{"name","scope","state","detail"}]}`: the names, the messages for what failed, every plugin a panel shows — which includes rows a switch cannot move (a plugin the program requires, everything under `[plugins] enabled = false`); `switchable` and `why` are those rows. `origin` is the plugin's entry-point name and the one a switch is written with; `enabled` says whether the **next start** does its work; `required` means the program cannot run without it; `setting` is the configuration key that decides the plugin (`"skills.enabled"`), empty for one that `[plugins] disable` holds. Every plugin is listed, loaded or not. `triggers` is where each trigger the loaded plugins registered is now, once the runtime has started: `scope` is `process` or `machine`, `state` is `pending`, `standby`, `running`, `skipped`, `finished`, `failed` or `stopped`, and `detail` is why for `standby`, `skipped` and `failed` — empty otherwise. |
| `PUT` | `/plugins/{name}` | `{"enabled": true\|false}` | That plugin, as the list now shows it. Nothing loads or unloads in the running server: a switch is read when a process starts, so a client that wants it now restarts the server. A plugin with a setting is recorded in that key of the server's configuration file, any other in `[plugins] disable` there; a name the installation does not have is refused (`400 invalid`). |
| `GET` | `/commands` | — | `{"commands": [{"name", "summary", "when_busy", "subcommands", "needs_more"}]}`; `subcommands` are the words a command takes first, and `needs_more` the ones a menu fills in and waits on rather than runs |
| `POST` | `/commands/{name}` | `{"argument"}` | `{"message", "notification", "prompt", "shown", "markdown", "cache"}` — a `prompt` is sent as the next `POST /prompts`, with `shown` as its line and `cache` as its mode; a `markdown` document is shown in a view of its own. A `when_busy="refuse"` command is answered `409 busy` while a run is in progress |
| `GET` | `/mentions?query=&limit=50` | — | `{"mentions": [{"token","kind","name","description"}]}`: the files, skills and plugin resources an `@` can reference. |
| `POST` | `/doctor` | `{"timeout"?: 30}` | `{"checks": [{"model","model_id","ok","seconds","detail","input_tokens","output_tokens"}]}`: every configured model asked one short question. |

```bash
curl -X PATCH http://127.0.0.1:3290/settings \
  -H 'content-type: application/json' \
  -d '{"model": "fast", "effort": "low", "permission": "safe"}'
```

A model is named as `/models` lists it (its display name when it has one). The token of a model is never returned.

A server starts its agent from the configuration file: the first `POST /models` entry is what makes it ready and
loads the plugins, so a model a plugin offers appears in `GET /models` after that and can be chosen with
`PATCH /settings`. A workspace with no file entry answers every request that needs a model with `409 no_model`
and the `POST /models` instruction.

## Harness library

The user-level library of named harnesses (`zettcode harness` in a shell), shared by every workspace. It needs no
model: these answer before one is configured. A download must be seen before it is kept, so installing and updating are
two calls. The preview downloads and inspects (nothing is imported or kept); the call that keeps sends back the
`commit` and `digest` it reported, downloads that commit again and keeps it only when it is what was shown (else
`400 invalid`). A body with a field the endpoint does not take is a `422`.

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| `GET` | `/harnesses` | — | `{"harnesses": [{"name","origin","commit","state","in_use","repositories": [{"name","version","description","tools","files","error","file_count"}]}]}`. `state` is `ok`, `changed`, `missing` or `damaged`; `in_use` is whether `[harness] use` names it, read at the time of the request from the configuration file the server was given (`--config`, else the default one). The list is cheap: `files` is empty (it carries `file_count`) and `state` is empty too, because answering it reads every byte of the harness; `GET /harnesses/{name}` has both. |
| `GET` | `/harnesses/{name}` | — | One harness, with its `files`. A name the library does not have is `400 invalid` and names the ones it has. |
| `POST` | `/harnesses/preview` | `{"source", "name"?}` | `{"action","name","source","commit","digest","version","description","tools","banned","files","size","changes","up_to_date","caution","links"}`. `source` is `owner/repo`, `owner/repo@ref` or a GitHub URL; `links` is each symbolic link in `files` and where it points. A network call that can take minutes; downloads run one at a time for the whole server, and one started while another runs is `400 invalid` ("try again when it is done"). |
| `POST` | `/harnesses` | `{"source", "name"?, "commit", "digest"}` | 201 with the harness. `commit` is the 40 and `digest` the 64 hexadecimal digits a preview reported. |
| `POST` | `/harnesses/{name}/preview` | `{"force"?}` | The same shape, for an update: `changes` says what would differ and `up_to_date` whether it is already at `commit`. A harness changed since it was installed is refused (`400 invalid`) unless `force` is true. |
| `PUT` | `/harnesses/{name}` | `{"commit", "digest", "force"?}` | The harness after the update. `409 busy` while a run is in progress in any conversation, checked before the download and again just before the files change. |
| `POST` | `/harnesses/{name}/fork` | `{"name"}` | 201 with the copy, which has no upstream. |
| `DELETE` | `/harnesses/{name}` | — | The remaining harnesses. Refused (`400 invalid`) while it is the one every session works in or an update is running; `409 busy` while a run is in progress. |

`/harness use` and `/harness save` act on the running conversation and are commands (`POST /commands/harness`).

## Sessions

The *current* session is the conversation the next prompt continues. A server starts on a fresh one.

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| `GET` | `/sessions?limit=20` | — | `{"sessions": [{"id","title","created_at","updated_at","current","running"}]}`, most recently active first. `running` is true for a session a run is going in now, the current one or one put aside. |
| `POST` | `/sessions` | `{"title"?}` | 201 with the new session, which becomes current. A run in the conversation being left goes on there. |
| `GET` | `/sessions/current` | — | `{"id","title","locked","usage"}` |
| `POST` | `/sessions/{id}/open` | — | The opened session, now current. 404 when it does not exist. A run in the conversation being left goes on there; opening a conversation that is running brings it back as it is. |
| `POST` | `/sessions/current/send` | `{"to","text","mode"?}` | `{"to","disposition"}`: a message to another ZettCode session (its handle or id), as the reader's own words. `mode` is `steer` (the default: hand it to the request that session is running) or `followup` (wait until that request ends); `disposition` is `started`, `steered`, `queued`, or `delivered` (a chat window kept it without starting a turn). 404 `unreachable` when nobody could take it. |
| `POST` | `/sessions/current/rename` | `{"title"}` | The session, renamed. |
| `POST` | `/sessions/current/name` | — | The model names the conversation and the new name is returned. |
| `POST` | `/sessions/current/fork` | — | The new session, which continues this conversation's context. |
| `POST` | `/sessions/current/compact` | — | `{"applied","summary","compressed","kept"}`; `applied:false` when there was nothing to fold. |
| `GET` | `/sessions/current/context` | — | `{"window","used","measured_by","shares","partial","from_provider"}`, or `null` before a request is measured. |
| `GET` | `/sessions/current/history` | `?full=true` (optional) | `{"messages": [{"role","text","tool_calls","ok","images"}]}`: the messages the model works with, or with `full=true` the whole conversation, each compaction's summary (role `summary`) where it was made. |
| `GET` | `/sessions/current/export` | — | The conversation as a standalone HTML page (`text/html`, as a download). |
| `POST` | `/sessions/current/ask` | `{"question","timeout"?}` | `{"answer"}`; answered beside the conversation, never added to it. 409 while a run is going. |
| `POST` | `/sessions/current/ask/stream` | `{"question","timeout"?}` | The same side question with the answer streamed, in the frames `/prompts` uses: `text_delta` events, then `result` (or `error`, or `cancelled` when `/runs/cancel` stops it). The question holds the run slot while it is answered. 409 while a run is going. |
| `GET` | `/sessions/current/stats` | — | `{"id","entries","requests","input_tokens","output_tokens","cache_read_tokens","reasoning_tokens","total_tokens","cache_share","cache_reported"}`, or `null` before anything is stored: one row of `/resume`. |
| `GET` | `/sessions/stats?ids=a,b` | — | `{"stats": [...]}` for the named sessions, same shape; at most 200 ids. |
| `GET` | `/sessions/current/self-compaction` | — | `{"choice": true\|false\|null, "effective": bool}` |
| `PUT` | `/sessions/current/self-compaction` | `{"choice": true\|false\|null}` | The same, after the choice is saved in the session; applies from the next request. |
| `GET` | `/usage` | — | This session's totals. |
| `GET` | `/usage/ledger` | — | `{"sessions", "models", "days", "total"}`: what the workspace spent, as the terminal's `/usage` page shows it. |

`usage` is the session's totals:

```json
{"input_tokens": 1200, "output_tokens": 340, "cache_read_tokens": 800, "cache_write_tokens": 0,
 "reasoning_tokens": 0, "seconds": 4.2, "requests": 3, "context_tokens": 1540, "cache_reported": true}
```

`cache_share` is `null` when there is no input yet or when the provider reported no cache read; `cache_reported` tells
the two apart, and is `false` in the second case. A client that divides the counters itself should stop when it is
`false`, the way the terminal leaves the item out.

## Running

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| `POST` | `/prompts` | `PromptRequest` | `text/event-stream`: the events of the run, then `result`, `error` or `cancelled`. `cache` is `read_write` (the default), `read` or `off`. |
| `POST` | `/runs/resume` | `RunOptions` | The same stream, continuing the interrupted request. |
| `GET` | `/runs/current` | — | `{"running", "pending"}`: whether a run is going in the current conversation and what it waits on. |
| `GET` | `/messages` | — | `{"messages": [{"id","sender_id","sender","text","via","hops"}]}`: what other sessions sent to the current conversation that is not answered yet, oldest first. A message that asked to steer a run that was going is in that run's stream instead, not here; if the run ended without reading it, it appears here. |
| `POST` | `/messages/{id}` | — | `text/event-stream`, the frames `/prompts` uses: answers that message as a turn. 404 when it is not waiting. |
| `GET` | `/runs/resumable` | — | `{"resumable","kind","description"}` |
| `POST` | `/runs/approvals` | `{"call_id","approve","remember"?}` | `{"resolved"}`, whether the run was waiting on that call. |
| `POST` | `/runs/questions` | `{"call_id","answer"}` | `{"resolved"}`; `"answer": null` declines the question. |
| `POST` | `/runs/steer` | `{"text", "images"?, "mentions"?}` | `{"steered", "text"}`: `steered` is false when nothing is running to take it; `text` is what the `steered` event that follows carries (a message with a picture or a mention is reported by the text it was built into), null when not taken. |
| `POST` | `/runs/cancel` | — | `{"cancelled"}`, whether there was a run to stop. |

`RunOptions`:

```json
{
  "approvals": {"mode": "deny", "commands": []},
  "questions": "decline",
  "timeout": null,
  "answer_timeout": 300,
  "keep_events": false
}
```

| Field | Meaning |
| --- | --- |
| `approvals.mode` | `deny` (default) refuses every shell command, `auto` approves every one, `commands` approves the ones in `commands` and denies the rest, `ask` sends each one to the client. |
| `approvals.commands` | Commands such as `"git status"` or `"pytest"`. A command matches when it is one or continues one with arguments; one holding `;`, `|`, `&`, `$`, a newline and the like never matches, so `git status; rm -rf ~` is not `git status`. |
| `questions` | `decline` (default) tells the model the reader is not there; `ask` sends the question down the stream and waits for the answer, however long it takes. |
| `timeout` | Seconds the whole run may take, or `null`. |
| `answer_timeout` | Seconds an `ask` approval waits for the client before the safe default (deny) is applied. A question waits for its answer instead. |
| `keep_events` | Include every event in the final `result` too. |

`PromptRequest` adds:

| Field | Meaning |
| --- | --- |
| `text` | The prompt; required and not blank. |
| `images` | `[{"data": "<base64>", "media_type": "image/png"}]` for a model that takes images. |
| `mentions` | Resolve `@path` references in the text, as the terminal does; true by default. |

::: tip A refused prompt is a status code
A body that cannot run — a command the rule would refuse to match, an image that is not base64 — is answered with 400
before the stream opens. What fails once events have started is an `error` frame: by then the status line has gone.
:::
