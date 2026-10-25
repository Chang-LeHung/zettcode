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
| `not_found` | 404 | No such session. |
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
| `GET` | `/models` | — | `{"models": [{"name","model","context_window","multimodal","efforts","active","compact_percent","web_search","web_search_name","display_model","base_url","api","temperature","can_search","search_name"}], "current"}`; works before a model is configured, where `current` is null. |
| `POST` | `/models` | `{"model", "token"?, "display_model"?, "base_url"?, "anthropic"?, "responses_api"?, "chat"?, "multimodal"?, "temperature"?, "web_search"?, "web_search_name"?, "context_window"?, "compact_percent"?, "reasoning_efforts"?}` | 201 with the new list. The first model makes the server ready; later ones are available for `PATCH /settings`. Written to the configuration file, with the keys the terminal's `/config add` uses. `web_search` lets the provider search the web for the model; for a DeepSeek model it is refused unless `anthropic` is set, and a misspelt key is a `422`. |
| `PATCH` | `/models/{name}` | Any of the fields `POST /models` takes | The new list. A key left out stays as it is; the token is kept unless a new one is given. A key sent as `null` is removed from the entry (all but `model` and `token`): `"temperature": null` goes back to the provider's own, and `"anthropic": null` takes the flag out of the file instead of leaving `anthropic = false`. |
| `DELETE` | `/models/{name}` | — | The remaining models. The last one cannot be removed (`400 invalid`): a client needs one. |
| `GET` | `/settings` | — | `{"model","effort","efforts","permission","permissions","harness"}`; after a `PATCH` that moved the compaction point it also has `"unsaved"` (see below). |
| `PATCH` | `/settings` | `{"model"?, "effort"?, "permission"?, "harness"?, "compact_percent"?}` | The same as `GET /settings`, after the change. At least one field. `permission` is `deny`, `ask`, `safe` or `full` (`auto` is the old name of `full` and is answered as `full`); `harness` turns the just-in-time tool harness on or off from the next prompt. `compact_percent` is above 0 and at most 100, applies from the next request and is written to the configuration file; when the file cannot be written the answer carries `"unsaved": "<why>"` and the change holds for this run only. Moving `compact_percent` is refused with `409` while a run is in progress; the other fields are not. |
| `GET` | `/plugins` | — | `{"loaded": [...], "failures": [...]}` |
| `GET` | `/mentions?query=&limit=50` | — | `{"mentions": [{"token","kind","name","description"}]}`: the files, skills and plugin resources an `@` can reference. |
| `POST` | `/doctor` | `{"timeout"?: 30}` | `{"checks": [{"model","model_id","ok","seconds","detail","input_tokens","output_tokens"}]}`: every configured model asked one short question. |

```bash
curl -X PATCH http://127.0.0.1:3290/settings \
  -H 'content-type: application/json' \
  -d '{"model": "fast", "effort": "low", "permission": "safe"}'
```

A model is named as `/models` lists it (its display name when it has one). The token of a model is never returned.

## Sessions

The *current* session is the conversation the next prompt continues. A server starts on a fresh one.

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| `GET` | `/sessions?limit=20` | — | `{"sessions": [{"id","title","created_at","updated_at","current","running"}]}`, most recently active first. `running` is true for a session a run is going in now, the current one or one put aside. |
| `POST` | `/sessions` | `{"title"?}` | 201 with the new session, which becomes current. A run in the conversation being left goes on there. |
| `GET` | `/sessions/current` | — | `{"id","title","locked","usage"}` |
| `POST` | `/sessions/{id}/open` | — | The opened session, now current. 404 when it does not exist. A run in the conversation being left goes on there; opening a conversation that is running brings it back as it is. |
| `POST` | `/sessions/current/send` | `{"to","text"}` | `{"to","disposition"}`: a message to another ZettCode session (its handle or id), as the reader's own words; `disposition` is `started` or `queued`. 404 `unreachable` when nobody could take it. |
| `POST` | `/sessions/current/rename` | `{"title"}` | The session, renamed. |
| `POST` | `/sessions/current/name` | — | The model names the conversation and the new name is returned. |
| `POST` | `/sessions/current/fork` | — | The new session, which continues this conversation's context. |
| `POST` | `/sessions/current/compact` | — | `{"applied","summary","compressed","kept"}`; `applied:false` when there was nothing to fold. |
| `GET` | `/sessions/current/context` | — | `{"window","used","measured_by","shares","partial","from_provider"}`, or `null` before a request is measured. |
| `GET` | `/sessions/current/history` | `?full=true` (optional) | `{"messages": [{"role","text","tool_calls","ok","images"}]}`: the messages the model works with, or with `full=true` the whole conversation, each compaction's summary (role `summary`) where it was made. |
| `GET` | `/sessions/current/export` | — | The conversation as a standalone HTML page (`text/html`, as a download). |
| `POST` | `/sessions/current/ask` | `{"question","timeout"?}` | `{"answer"}`; answered beside the conversation, never added to it. 409 while a run is going. |
| `POST` | `/sessions/current/ask/stream` | `{"question","timeout"?}` | The same side question with the answer streamed, in the frames `/prompts` uses: `text_delta` events, then `result` (or `error`, or `cancelled` when `/runs/cancel` stops it). The question holds the run slot while it is answered. 409 while a run is going. |
| `GET` | `/sessions/current/stats` | — | `{"id","entries","requests","input_tokens","output_tokens","cache_read_tokens","reasoning_tokens","total_tokens","cache_share"}`, or `null` before anything is stored: one row of `/resume`. |
| `GET` | `/sessions/stats?ids=a,b` | — | `{"stats": [...]}` for the named sessions, same shape; at most 200 ids. |
| `GET` | `/sessions/current/self-compaction` | — | `{"choice": true\|false\|null, "effective": bool}` |
| `PUT` | `/sessions/current/self-compaction` | `{"choice": true\|false\|null}` | The same, after the choice is saved in the session; applies from the next request. |
| `GET` | `/usage` | — | This session's totals. |
| `GET` | `/usage/ledger` | — | `{"sessions", "models", "days", "total"}`: what the workspace spent, as the terminal's `/usage` page shows it. |

`usage` is the session's totals:

```json
{"input_tokens": 1200, "output_tokens": 340, "cache_read_tokens": 800, "cache_write_tokens": 0,
 "reasoning_tokens": 0, "seconds": 4.2, "requests": 3, "context_tokens": 1540}
```

## Running

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| `POST` | `/prompts` | `PromptRequest` | `text/event-stream`: the events of the run, then `result`, `error` or `cancelled`. |
| `POST` | `/runs/resume` | `RunOptions` | The same stream, continuing the interrupted request. |
| `GET` | `/runs/current` | — | `{"running", "pending"}`: whether a run is going in the current conversation and what it waits on. |
| `GET` | `/messages` | — | `{"messages": [{"id","sender_id","sender","text","via","hops"}]}`: what other sessions sent to the current conversation that is not answered yet, oldest first. |
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
