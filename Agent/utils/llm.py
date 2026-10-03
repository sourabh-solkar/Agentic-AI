"""Free-tier LLM providers with automatic fallback on quota / rate-limit failures.

Primary: Gemini. Optional fallbacks (when API keys are set): Groq, xAI Grok,
OpenRouter, Cerebras. Order can be overridden with FREE_LLM_ORDER.
"""

from __future__ import annotations

import os
from typing import Any, Sequence

from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()


class ProviderTransientError(RuntimeError):
    """Raised to trigger the next free-provider fallback."""


def _never_fallback_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [KeyboardInterrupt, SystemExit, GeneratorExit]
    try:
        from langgraph.errors import GraphBubbleUp, GraphInterrupt

        types.extend([GraphInterrupt, GraphBubbleUp])
    except ImportError:
        pass
    try:
        from langgraph.errors import NodeInterrupt

        types.append(NodeInterrupt)
    except ImportError:
        pass
    return tuple(types)


_NEVER_FALLBACK = _never_fallback_types()


def _specific_quota_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [TimeoutError, ConnectionError]
    try:
        from google.api_core import exceptions as gexc

        types.extend(
            [
                gexc.ResourceExhausted,
                gexc.TooManyRequests,
                gexc.ServiceUnavailable,
                gexc.DeadlineExceeded,
            ]
        )
    except ImportError:
        pass
    try:
        from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

        types.extend(
            [RateLimitError, APIConnectionError, APITimeoutError, InternalServerError]
        )
    except ImportError:
        pass
    return tuple(types)


_QUOTA_TYPES = _specific_quota_types()

_QUOTA_NEEDLES = (
    "resource exhausted",
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "quota",
    "429",
    "too many requests",
    "insufficient_quota",
    "model is overloaded",
    "capacity",
    "unavailable",
    "overloaded",
)


def _is_transient_provider_error(exc: BaseException) -> bool:
    if isinstance(exc, _NEVER_FALLBACK):
        return False
    if isinstance(exc, ProviderTransientError):
        return True
    if isinstance(exc, _QUOTA_TYPES):
        return True
    text = str(exc).lower()
    return any(needle in text for needle in _QUOTA_NEEDLES)


class _TransientErrorBridge(Runnable):
    """Convert quota-like failures into ProviderTransientError for with_fallbacks."""

    def __init__(self, inner: Runnable, provider_name: str = "provider"):
        self._inner = inner
        self._provider_name = provider_name

    def invoke(
        self,
        input: Any,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            return self._inner.invoke(input, config=config, **kwargs)
        except _NEVER_FALLBACK:
            raise
        except Exception as exc:
            if _is_transient_provider_error(exc):
                print(f"LLM provider '{self._provider_name}' failed transiently: {exc}")
                raise ProviderTransientError(str(exc)) from exc
            raise

    async def ainvoke(
        self,
        input: Any,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            return await self._inner.ainvoke(input, config=config, **kwargs)
        except _NEVER_FALLBACK:
            raise
        except Exception as exc:
            if _is_transient_provider_error(exc):
                print(f"LLM provider '{self._provider_name}' failed transiently: {exc}")
                raise ProviderTransientError(str(exc)) from exc
            raise


def _openai_compat(
    *,
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0,
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_retries=1,
    )


def _build_gemini() -> BaseChatModel | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        google_api_key=key,
        streaming=False,
    )


def _build_groq() -> BaseChatModel | None:
    """Groq cloud free tier (not xAI Grok)."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    return _openai_compat(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        api_key=key,
        base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    )


def _build_grok() -> BaseChatModel | None:
    """xAI Grok free credits."""
    key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
    if not key:
        return None
    return _openai_compat(
        model=os.getenv("GROK_MODEL", "grok-4-fast"),
        api_key=key,
        base_url=os.getenv("XAI_BASE_URL", "https://api.x.ai/v1"),
    )


def _build_openrouter() -> BaseChatModel | None:
    """OpenRouter free models (requires a key; pick free model ids)."""
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return None
    return _openai_compat(
        model=os.getenv("OPENROUTER_MODEL", "openrouter/free"),
        api_key=key,
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    )


def _build_cerebras() -> BaseChatModel | None:
    key = os.getenv("CEREBRAS_API_KEY")
    if not key:
        return None
    return _openai_compat(
        model=os.getenv("CEREBRAS_MODEL", "llama-3.3-70b"),
        api_key=key,
        base_url=os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"),
    )


_PROVIDER_BUILDERS = {
    "gemini": _build_gemini,
    "groq": _build_groq,
    "grok": _build_grok,
    "openrouter": _build_openrouter,
    "cerebras": _build_cerebras,
}

_DEFAULT_ORDER = ("gemini", "groq", "grok", "openrouter", "cerebras")


def _provider_order() -> list[str]:
    raw = os.getenv("FREE_LLM_ORDER", "").strip()
    if not raw:
        return list(_DEFAULT_ORDER)
    order = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return order or list(_DEFAULT_ORDER)


def build_provider_models() -> list[tuple[str, BaseChatModel]]:
    """Build concrete chat models for every configured free provider."""
    models: list[tuple[str, BaseChatModel]] = []
    for name in _provider_order():
        builder = _PROVIDER_BUILDERS.get(name)
        if builder is None:
            print(f"Unknown FREE_LLM provider '{name}', skipping")
            continue
        try:
            model = builder()
        except Exception as err:
            print(f"Failed to init LLM provider '{name}':", err)
            continue
        if model is not None:
            models.append((name, model))
    if not models:
        raise RuntimeError(
            "No free LLM providers configured. Set at least GEMINI_API_KEY "
            "(and optionally GROQ_API_KEY, XAI_API_KEY, OPENROUTER_API_KEY, CEREBRAS_API_KEY)."
        )
    return models


def with_provider_fallbacks(runnables: Sequence[Runnable], names: Sequence[str] | None = None) -> Runnable:
    """Chain runnables so transient provider failures try the next free LLM."""
    if not runnables:
        raise ValueError("Need at least one runnable")
    label_names = list(names) if names is not None else [f"provider-{i}" for i in range(len(runnables))]
    bridged = [
        _TransientErrorBridge(runnable, provider_name=label_names[i] if i < len(label_names) else f"provider-{i}")
        for i, runnable in enumerate(runnables)
    ]
    if len(bridged) == 1:
        return bridged[0]
    primary, *rest = bridged
    return primary.with_fallbacks(
        list(rest),
        exceptions_to_handle=(ProviderTransientError,),
    )


def apply_to_each_provider(
    models: Sequence[tuple[str, BaseChatModel]],
    transform,
) -> Runnable:
    """Apply the same transform (bind_tools / structured output) to each provider, then fallback-chain."""
    names = [name for name, _ in models]
    runnables = [transform(model) for _, model in models]
    return with_provider_fallbacks(runnables, names=names)


def get_chat_llm() -> Runnable:
    """Primary free LLM with fallbacks for plain invoke (summaries, etc.)."""
    models = build_provider_models()
    names = [name for name, _ in models]
    print(f"Free LLM chain: {' -> '.join(names)}")
    return with_provider_fallbacks([m for _, m in models], names=names)


def get_provider_models() -> list[tuple[str, BaseChatModel]]:
    """Expose the per-provider model list for agent / tool binding."""
    models = build_provider_models()
    print(f"Free LLM chain: {' -> '.join(name for name, _ in models)}")
    return models
