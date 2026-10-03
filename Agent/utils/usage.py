"""Token usage metering for credit billing.

Source of truth: provider-reported token counts on LLM responses
(usage_metadata / token_usage). LangSmith remains observability-only.
"""

from __future__ import annotations

import math
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


def tokens_per_credit() -> int:
    return max(1, int(os.getenv("TOKENS_PER_CREDIT", "1000")))


def credit_hold_amount() -> int:
    return max(1, int(os.getenv("CREDIT_HOLD_AMOUNT", "1")))


def min_credits_per_turn() -> int:
    """Floor charged when any LLM tokens were used (0 if no usage)."""
    return max(0, int(os.getenv("MIN_CREDITS_PER_TURN", "1")))


def tokens_to_credits(input_tokens: int, output_tokens: int) -> int:
    """Convert provider token counts into whole credits (industry-style ceil)."""
    total = max(0, int(input_tokens)) + max(0, int(output_tokens))
    if total <= 0:
        return 0
    due = math.ceil(total / tokens_per_credit())
    return max(min_credits_per_turn(), due)


@dataclass
class UsageCall:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    provider: str | None = None
    model: str | None = None
    purpose: str = "chat"


@dataclass
class UsageAccumulator:
    """Mutable rollup for one billable turn (chat or approval resume)."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: list[UsageCall] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        purpose: str = "chat",
    ) -> None:
        inp = max(0, int(input_tokens or 0))
        out = max(0, int(output_tokens or 0))
        if total_tokens is not None and inp == 0 and out == 0:
            total = max(0, int(total_tokens))
            # Prefer splitting unknown totals onto output so ceil billing still works.
            out = total
        self.input_tokens += inp
        self.output_tokens += out
        self.calls.append(
            UsageCall(
                input_tokens=inp,
                output_tokens=out,
                total_tokens=inp + out,
                provider=provider,
                model=model,
                purpose=purpose,
            )
        )


_current_usage: ContextVar[UsageAccumulator | None] = ContextVar(
    "current_usage_accumulator", default=None
)


@contextmanager
def bind_usage(accumulator: UsageAccumulator) -> Iterator[UsageAccumulator]:
    token = _current_usage.set(accumulator)
    try:
        yield accumulator
    finally:
        _current_usage.reset(token)


def current_usage() -> UsageAccumulator | None:
    return _current_usage.get()


def record_usage(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int | None = None,
    provider: str | None = None,
    model: str | None = None,
    purpose: str = "chat",
    accumulator: UsageAccumulator | None = None,
) -> None:
    acc = accumulator if accumulator is not None else current_usage()
    if acc is None:
        return
    if (
        not input_tokens
        and not output_tokens
        and (total_tokens is None or total_tokens <= 0)
    ):
        return
    acc.add(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        provider=provider,
        model=model,
        purpose=purpose,
    )


def extract_usage_from_message(message: Any) -> tuple[int, int, int]:
    """Return (input, output, total) from a LangChain message if present."""
    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, dict):
        inp = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or (inp + out))
        return inp, out, total

    meta = getattr(message, "response_metadata", None) or {}
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(token_usage, dict):
            inp = int(
                token_usage.get("prompt_tokens")
                or token_usage.get("input_tokens")
                or 0
            )
            out = int(
                token_usage.get("completion_tokens")
                or token_usage.get("output_tokens")
                or 0
            )
            total = int(token_usage.get("total_tokens") or (inp + out))
            return inp, out, total
    return 0, 0, 0


def extract_usage_from_llm_result(response: LLMResult) -> tuple[int, int, int]:
    llm_output = response.llm_output or {}
    if isinstance(llm_output, dict):
        token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        if isinstance(token_usage, dict) and token_usage:
            inp = int(
                token_usage.get("prompt_tokens")
                or token_usage.get("input_tokens")
                or 0
            )
            out = int(
                token_usage.get("completion_tokens")
                or token_usage.get("output_tokens")
                or 0
            )
            total = int(token_usage.get("total_tokens") or (inp + out))
            return inp, out, total

    for gen_list in response.generations or []:
        for gen in gen_list:
            message = getattr(gen, "message", None)
            if message is not None:
                inp, out, total = extract_usage_from_message(message)
                if inp or out or total:
                    return inp, out, total
    return 0, 0, 0


def record_from_message(
    message: Any,
    *,
    purpose: str = "chat",
    accumulator: UsageAccumulator | None = None,
) -> None:
    inp, out, total = extract_usage_from_message(message)
    model = None
    meta = getattr(message, "response_metadata", None) or {}
    if isinstance(meta, dict):
        model = meta.get("model_name") or meta.get("model")
    record_usage(
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        model=str(model) if model else None,
        purpose=purpose,
        accumulator=accumulator,
    )


def record_from_llm_result(
    response: LLMResult,
    *,
    purpose: str = "chat",
    accumulator: UsageAccumulator | None = None,
) -> None:
    inp, out, total = extract_usage_from_llm_result(response)
    model = None
    llm_output = response.llm_output or {}
    if isinstance(llm_output, dict):
        model = llm_output.get("model_name") or llm_output.get("model")
    record_usage(
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        model=str(model) if model else None,
        purpose=purpose,
        accumulator=accumulator,
    )


class UsageCallbackHandler(BaseCallbackHandler):
    """LangChain callback that meters provider token usage into an accumulator.

    Holds an explicit accumulator reference so metering still works when the
    graph runs in a worker thread (Python < 3.11 path) where ContextVars do not
    propagate automatically.
    """

    def __init__(self, accumulator: UsageAccumulator, purpose: str = "chat"):
        super().__init__()
        self.accumulator = accumulator
        self.purpose = purpose

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        record_from_llm_result(
            response,
            purpose=self.purpose,
            accumulator=self.accumulator,
        )
