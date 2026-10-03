# Token-based credit billing

How free-tier credits are held, metered from LLM token usage, and settled after each chat (or approval) turn.

## Why not flat “1 credit per question”?

A single `/chat` turn can run several LLM calls (classify → agent/tool loops → rolling summary). Cost varies by tokens, not by request count. Billing follows **provider-reported token usage** for that turn, which is the industry-standard meter (what vendors charge against).

**LangSmith is not used for charging.** Traces remain for debugging / audit only.

## Formula

```text
total_tokens = input_tokens + output_tokens
credits_charged = 0                          if turn failed with zero tokens
                = max(MIN_CREDITS_PER_TURN,
                      ceil(total_tokens / TOKENS_PER_CREDIT))
                  otherwise
```

Defaults (see `env-dev.example`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `FREE_QUESTION_CREDITS` | `30` | Credits granted on Gmail registration |
| `TOKENS_PER_CREDIT` | `1000` | Tokens that equal one credit |
| `CREDIT_HOLD_AMOUNT` | `1` | Credits reserved when a turn starts |
| `MIN_CREDITS_PER_TURN` | `1` | Floor when any tokens were used |

Examples with defaults:

| Tokens used | Credits charged |
|-------------|-----------------|
| 0 (failed, no LLM usage) | 0 (hold released) |
| 1 – 1000 | 1 |
| 1001 – 2000 | 2 |
| 2500 | 3 |

## Lifecycle: hold → meter → settle

```text
/chat or /approval/approve
        │
        ▼
 reserve_credits(CREDIT_HOLD_AMOUNT)     ← 402 if balance < hold
        │
        ▼
 stream graph + optional summary LLM
   (UsageCallbackHandler + usage_metadata)
        │
        ▼
 settle_usage(...)
   • charge credits_charged
   • refund unused hold, or deduct overage
   • insert usage_events row
        │
        ▼
 SSE event: credits  +  done
```

### 1. Hold

On `/chat` and `/approval/approve` (and the email-approval alias), the API creates a `run_id`, then:

```python
remaining = reserve_credits(user_id, CREDIT_HOLD_AMOUNT, run_id=run_id, session_id=...)
```

- Atomically deducts the hold from `users.credits` when `credits >= hold`.
- Inserts a `credit_holds` row with `status = 'held'`.
- Returns HTTP **402** if the user cannot cover the hold.
- Response header `X-Credits-Remaining` is the balance **after** the hold (pre-settle).

### 2. Meter

During the turn, token counts are accumulated in a `UsageAccumulator`:

| Source | Role |
|--------|------|
| `UsageCallbackHandler` on the LangGraph config | Primary — `on_llm_end` / provider `token_usage` |
| `AIMessage.usage_metadata` backfill | Fallback if callbacks missed tokens |
| Summary LLM in `db_operations` | Included in the same turn via `record_from_message(..., purpose="summary")` |

What is billed in one settle:

- Classifier + domain agents + tool-loop LLM calls (`purpose`: `chat` or `approve`)
- Rolling conversation summary call after a completed assistant message (`purpose`: `summary`, same accumulator)

Observability (LangSmith `run_id` / trace URL) is unchanged and independent of billing.

### 3. Settle

At the end of the SSE generator (`finally`):

1. Compute `credits_charged` from measured tokens.
2. Compare to the hold:
   - `due < held` → refund `held - due`
   - `due > held` → deduct up to `due - held` from remaining balance (never negative)
   - `due == held` → no further balance change
3. Mark the hold `settled` (or `released` if `due == 0`).
4. Insert one `usage_events` ledger row.
5. Emit SSE `credits` with the billing summary, then `done`.

Failed turns with **zero** measured tokens release the full hold (`credits_charged = 0`).

Approval **resume** is a separate turn: new hold, new meter, new settle (`purpose = approve`).

## Data model

Defined in `Agent/db/schema.sql` (apply with `python -m db.init_db` from `Agent/`).

### `credit_holds`

Per-turn reservation keyed by LangSmith/chat `run_id`.

| Column | Notes |
|--------|--------|
| `run_id` | PK; same id used for the graph config / trace |
| `user_id` | Owner |
| `session_id` | Stored as text (no FK — DB may use uuid or text for sessions) |
| `amount` | Held credits |
| `status` | `held` → `settled` or `released` |

### `usage_events`

Append-only ledger for audit (“why was I charged?”).

| Column | Notes |
|--------|--------|
| `input_tokens` / `output_tokens` / `total_tokens` | Provider usage |
| `credits_charged` | Settled credit amount |
| `purpose` | `chat`, `approve`, or `summary` (summary is rolled into the parent turn’s settle; the accumulator sums all purposes before settle) |
| `run_id` | Links to the hold / LangSmith run |

`users.credits` remains the live balance (integer, `CHECK (credits >= 0)`).

## API surface

| Endpoint | Billing behavior |
|----------|------------------|
| `GET/POST /chat` | Hold → stream → settle; `X-Credits-Remaining` after hold; SSE `credits` after settle |
| `POST /approval/approve` | Same (purpose `approve`) |
| `POST /email-approval/approve` | Alias of approval approve |
| `GET /me` | Balance + billing config (`tokens_per_credit`, `credit_hold_amount`, `min_credits_per_turn`) |
| `GET /credits` | Balance + same config fields |

### SSE `credits` payload

```json
{
  "credits": 27,
  "credits_charged": 2,
  "credits_held": 1,
  "input_tokens": 1200,
  "output_tokens": 400,
  "total_tokens": 1600
}
```

The Streamlit UI (`UI/app.py`) applies `credits` from this event (and still refreshes via `/me` after the turn).

## Code map

| Path | Responsibility |
|------|----------------|
| `Agent/utils/usage.py` | Accumulator, token→credit math, LangChain callback, metadata extractors |
| `Agent/db/user_operations.py` | `reserve_credits`, `settle_usage`, legacy `try_consume_credit` alias |
| `Agent/db/schema.sql` | `credit_holds`, `usage_events` |
| `Agent/db/db_operations.py` | Meters summary LLM calls into the bound accumulator |
| `Agent/main.py` | Hold on chat/approve; bind usage; settle in SSE `finally` |
| `UI/app.py` | Handles SSE `credits` events |

## Operational notes

1. **Restart the Agent API** after changing billing env vars (`TOKENS_PER_CREDIT`, etc.).
2. **Apply schema** on existing databases: from `Agent/`, run `python -m db.init_db` (idempotent `CREATE TABLE IF NOT EXISTS`).
3. **Overage**: if a turn costs more than the hold and the user has little balance left, we deduct what remains and still record the intended `credits_charged` in `usage_events` (balance never goes negative).
4. **Missing usage metadata**: if the provider returns no token counts, backfill may still find `usage_metadata` on messages; if everything is empty and the turn failed, the hold is released. If tokens are empty but the turn “succeeded,” `MIN_CREDITS_PER_TURN` does not apply (charge is 0) — prefer providers that report usage.
5. **Idempotent settle**: re-settling an already `settled`/`released` hold does not charge again.

## Tuning for production

- Raise `CREDIT_HOLD_AMOUNT` if typical turns often exceed 1 credit, to reduce mid-turn under-balance.
- Lower `TOKENS_PER_CREDIT` to charge more per token (or raise it for a more generous free tier).
- Keep LangSmith for reconciliation dashboards; do not block user responses on LangSmith reads.
