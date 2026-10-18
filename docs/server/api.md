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
| `timeout` | 504 | The run's deadline passed. |
| `run` | 502 | The provider, or the run, failed. |
| `internal` | 500 | Anything else; the message is the SDK's. |

Except on `/health`, every endpoint requires `Authorization: Bearer <token>` when the server was started with one.

## Health

| Method | Path | Answers |
| --- | --- | --- |
| `GET` | `/health` | `{"status","version","workspace","session","busy"}`; the only endpoint a token does not guard. |
| `GET` | `/` | The name, version and the paths of the docs and health endpoints. |

## Models and settings

| Method | Path | Body | Answers |
| --- | --- | --- | --- |
| `GET` | `/models` | — | `{"models": [{"name","model","context_window","multimodal","efforts","active"}], "current"}` |
| `GET` | `/settings` | — | `{"model","effort","efforts","permission","permissions"}` |
| `PATCH` | `/settings` | `{"model"?, "effort"?, "permission"?}` | The same as `GET /settings`, after the change. At least one field. |
| `GET` | `/plugins` | — | `{"loaded": [...], "failures": [...]}` |

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
| `GET` | `/sessions?limit=20` | — | `{"sessions": [{"id","title","created_at","updated_at","current"}]}`, most recently active first. |
| `POST` | `/sessions` | `{"title"?}` | 201 with the new session, which becomes current. |
| `GET` | `/sessions/current` | — | `{"id","title","locked","usage"}` |
| `POST` | `/sessions/{id}/open` | — | The opened session, now current. 404 when it does not exist. |
| `POST` | `/sessions/current/rename` | `{"title"}` | The session, renamed. |
| `POST` | `/sessions/current/name` | — | The model names the conversation and the new name is returned. |
| `POST` | `/sessions/current/fork` | — | The new session, which continues this conversation's context. |
| `POST` | `/sessions/current/compact` | — | `{"applied","summary","compressed","kept"}`; `applied:false` when there was nothing to fold. |
| `GET` | `/sessions/current/context` | — | `{"window","used","measured_by","shares","partial","from_provider"}`, or `null` before a request is measured. |
| `GET` | `/sessions/current/history` | — | `{"messages": [{"role","text","tool_calls","ok","images"}]}` |
| `GET` | `/sessions/current/export` | — | The conversation as a standalone HTML page (`text/html`, as a download). |
| `POST` | `/sessions/current/ask` | `{"question","timeout"?}` | `{"answer"}`; answered beside the conversation, never added to it. 409 while a run is going. |

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
| `GET` | `/runs/current` | — | `{"running", "pending"}`: whether a run is going and what it waits on. |
| `GET` | `/runs/resumable` | — | `{"resumable","kind","description"}` |
| `POST` | `/runs/approvals` | `{"call_id","approve","remember"?}` | `{"resolved"}`, whether the run was waiting on that call. |
| `POST` | `/runs/questions` | `{"call_id","answer"}` | `{"resolved"}`; `"answer": null` declines the question. |
| `POST` | `/runs/steer` | `{"text"}` | `{"steered"}`, false when nothing is running to take it. |
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
| `questions` | `decline` (default) tells the model the reader is not there; `ask` sends the question down the stream and waits for the answer. |
| `timeout` | Seconds the whole run may take, or `null`. |
| `answer_timeout` | Seconds an `ask` approval or question waits for the client before the safe default (deny, decline) is applied. |
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
