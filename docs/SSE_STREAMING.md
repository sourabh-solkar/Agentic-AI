# SSE chat streaming (UI + backend)

How chat and approval responses stream live graph progress from FastAPI to Streamlit.

## The problem

`/chat` already returned `StreamingResponse` with `media_type="text/event-stream"`, and the Streamlit UI already read the body line-by-line. It still felt non-streaming because the backend did this:

1. Call `graph.ainvoke(...)` and **wait for the whole LangGraph run**.
2. Yield a single payload (final answer or `[APPROVAL REQUIRED]`).
3. Yield `event: done`.

So the HTTP stream was open, but nothing useful was sent until the graph finished. Intermediate steps (classify, tools, booking, etc.) never appeared while they were running.

A second issue appeared after switching to real streaming: on **Python 3.10**, LangGraph `interrupt()` fails under async `astream` / `ainvoke` with:

`Called get_config outside of a runnable context`

Async runners below 3.11 drop the runnable config `contextvars` that `interrupt()` needs. Sync `graph.stream()` keeps that context.

## The solution (backend)

### Typed SSE events

`_sse_event(event, text)` emits named events (not only bare `data:` lines):

| Event | Meaning | Persisted? |
|-------|---------|------------|
| `status` | Live step label while a node is working | No |
| `message` | Final assistant text (or approval prompt / `[error] …`) | Yes (assistant text only) |
| `trace` | JSON with `trace_id`, `trace_url`, `message_id` for this turn | Yes (`trace_*` on the assistant row) |
| `done` | Stream finished (`data: [DONE]`) | No |

Example wire format:

```text
event: status
data: Classifying your request

event: status
data: Checking availability

event: message
data: Here are the open villas…

event: trace
data: {"trace_id":"…","trace_url":"https://smith.langchain.com/…","message_id":42}

event: done
data: [DONE]
```

Headers (disable buffering / keep the connection open):

```python
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
```

### Stream graph parts, not a one-shot invoke

`_stream_graph_parts` yields LangGraph `(mode, data)` chunks with:

```python
stream_mode = ["tasks", "updates"]
```

- **`tasks`** (no `result` key): node is about to run → map `data["name"]` through `_NODE_STATUS` → yield `event: status`.
- **`updates`**: collect new messages; if `__interrupt__` is present, yield status “Waiting for your approval” and build the approval payload.

`_iter_graph_sse` orchestrates that loop, then yields one `event: message` (approval text or latest assistant text) and persists only the assistant answer.

### Python 3.10 vs 3.11+

| Runtime | How the graph is streamed |
|---------|---------------------------|
| Python ≥ 3.11 | `async for part in graph.astream(...)` |
| Python &lt; 3.11 | Sync `graph.stream(...)` in a worker thread; chunks pushed onto an `asyncio.Queue` via `loop.call_soon_threadsafe` |

The worker-thread path keeps `interrupt()` working and still works with `AsyncPostgresSaver` (sync checkpointer calls bridge back to the event loop). FastAPI remains async and can yield SSE chunks as each queue item arrives.

### Endpoints that stream

| Endpoint | Generator |
|----------|-----------|
| `GET`/`POST` `/chat` | `event_generator` → `_iter_graph_sse` |
| `POST` `/approval/approve` | `_approval_event_generator` → `_iter_graph_sse` with `Command(resume={"approved": True})` |
| `POST` `/email-approval/approve` | Same as approval |

Auth / “no pending approval” checks run in `_pending_approval_context` **before** any SSE bytes are sent, so HTTP errors stay normal JSON/status responses.

## The solution (UI)

Shared reader: `_read_sse(resp, on_status, on_message)` in `UI/app.py`.

- Parses `event:` / `data:` lines.
- On `status`: calls `on_status` (updates `st.status` label and writes the step).
- On `message`: accumulates text and calls `on_message` (assistant bubble with a caret).
- On `done` / `[DONE]`: stops.
- Returns the full message text only (status lines are never appended to chat history).

Used by:

1. **Chat** — after the user sends a prompt.
2. **Approve** — after Approve / Approve Send Email; approval endpoints now return the same SSE stream instead of a one-shot JSON body.

## Data flow

```text
User prompt (Streamlit)
    → GET /chat?message=…&session_id=…  (Bearer token)
        → _iter_graph_sse
            → _stream_graph_parts  (tasks + updates)
            → yield status / message / done
    → _read_sse
        → st.status (live steps)
        → chat bubble (final message only)
```

Approval resume is the same path with `Command(resume=…)` instead of a new user message.

## What is intentionally not streamed

- Token-by-token LLM tokens (only node-level status + final message).
- Status labels are not saved to the DB or to `st.session_state.messages`.
- Only the final `message` event content is persisted via `append_assistant_message`.

## Key code

- Backend: `Agent/main.py` — `_sse_event`, `_stream_graph_parts`, `_iter_graph_sse`, `_approval_event_generator`, `_SSE_HEADERS`
- UI: `UI/app.py` — `_read_sse`, chat + approve call sites

## Quick verify

1. Start API (`Agent/main.py`) and Streamlit (`UI/app.py`).
2. Send a chat that hits several nodes (e.g. availability). You should see the status box step through labels before the answer appears.
3. Trigger a human-approval path: status should show “Waiting for your approval”, then Approve should stream resume steps the same way (no `get_config outside of a runnable context` on Python 3.10).
