"""Model adapters (Phase 0.4): one interface over the models a task can run on.

An adapter takes a system prompt, a message list and the JSON Schema the
reply must match, and returns the reply text with its token usage and cost.
Adapters ask the backend for schema-constrained decoding where it has it, but
the runner still validates every reply, so an adapter without it also works.

* ``FakeAdapter``: scripted replies, for tests and dry runs.
* ``OpenAICompatAdapter``: any server with an OpenAI-style chat completions
  endpoint. This covers the open-weight candidates served by Ollama, vLLM,
  llama.cpp server or a hosted inference provider.
* ``AnthropicAdapter``: Claude models through the official ``anthropic`` SDK,
  used for the LLM baseline that the SLM cost target is measured against.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

Message = dict[str, str]


class ModelError(RuntimeError):
    """The backend failed, timed out or declined. The runner records MODEL_ERROR."""


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: float | None = None
    model: str | None = None
    stop_reason: str | None = None


class Adapter(Protocol):
    name: str

    def complete(
        self, system: str, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> Completion: ...


@dataclass
class FakeAdapter:
    """Returns scripted replies in order. A reply may be a string, a dict (sent as
    JSON), an exception (raised) or a callable taking (system, messages)."""

    replies: Iterable[Any]
    name: str = "fake"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._it = iter(self.replies)

    def complete(self, system: str, messages: list[Message], schema: dict[str, Any], schema_name: str) -> Completion:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "schema_name": schema_name})
        try:
            r = next(self._it)
        except StopIteration as e:
            raise ModelError("fake adapter has no more replies") from e
        if callable(r):
            r = r(system, messages)
        if isinstance(r, BaseException):
            raise r
        text = r if isinstance(r, str) else json.dumps(r)
        return Completion(text=text, input_tokens=0, output_tokens=0, cost_usd=0.0, latency_ms=0.0, model=self.name)


@dataclass
class OpenAICompatAdapter:
    """Chat completions over HTTP, with ``response_format`` set to the JSON Schema.

    ``price_in`` and ``price_out`` are USD per million tokens. For a self-hosted
    model, set them from the hosting cost so runs report a comparable cost.
    """

    base_url: str
    model: str
    api_key: str | None = None
    price_in: float = 0.0
    price_out: float = 0.0
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout_s: float = 120.0
    name: str = ""

    def __post_init__(self) -> None:
        self.name = self.name or f"openai-compat:{self.model}"

    def complete(self, system: str, messages: list[Message], schema: dict[str, Any], schema_name: str) -> Completion:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise ModelError(f"{self.name}: {e}") from e
        ms = (time.perf_counter() - t0) * 1000
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ModelError(f"{self.name}: unexpected reply shape") from e
        usage = data.get("usage") or {}
        tin, tout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        return Completion(
            text=text,
            input_tokens=tin,
            output_tokens=tout,
            cost_usd=(tin * self.price_in + tout * self.price_out) / 1e6,
            latency_ms=ms,
            model=data.get("model", self.model),
            stop_reason=choice.get("finish_reason"),
        )


# USD per million tokens: input, output, cache read, 5-minute cache write.
ANTHROPIC_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
# Models that take the server-side refusal fallback. Haiku 5.5 has none.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class AnthropicAdapter:
    """Claude through the official SDK, with structured outputs.

    The system prompt is cached, because every case of a task shares it. The
    client is created lazily so the package imports without ``anthropic``
    installed (it is in the ``models`` extra).
    """

    model: str
    max_tokens: int = 16000
    effort: str | None = None
    client: Any = None
    name: str = ""

    def __post_init__(self) -> None:
        self.name = self.name or f"anthropic:{self.model}"

    def _client(self) -> Any:
        if self.client is None:
            import anthropic  # noqa: PLC0415 (optional dependency)

            self.client = anthropic.Anthropic()
        return self.client

    def cost(self, usage: Any) -> float | None:
        price = ANTHROPIC_PRICES.get(self.model)
        if price is None:
            return None
        pin, pout, pread, pwrite = price
        get = lambda k: int(getattr(usage, k, 0) or 0)  # noqa: E731
        return (
            get("input_tokens") * pin
            + get("output_tokens") * pout
            + get("cache_read_input_tokens") * pread
            + get("cache_creation_input_tokens") * pwrite
        ) / 1e6

    def complete(self, system: str, messages: list[Message], schema: dict[str, Any], schema_name: str) -> Completion:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort:
            output_config["effort"] = self.effort
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
            "output_config": output_config,
        }
        client = self._client()
        t0 = time.perf_counter()
        try:
            if self.model in _FALLBACK_MODELS:
                resp = client.beta.messages.create(betas=[_FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                resp = client.messages.create(**kwargs)
        except Exception as e:  # the SDK's typed errors all mean the call failed
            raise ModelError(f"{self.name}: {type(e).__name__}: {e}") from e
        ms = (time.perf_counter() - t0) * 1000
        if resp.stop_reason == "refusal":
            raise ModelError(f"{self.name}: refused")
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
        return Completion(
            text=text,
            input_tokens=int(resp.usage.input_tokens or 0),
            output_tokens=int(resp.usage.output_tokens or 0),
            cost_usd=self.cost(resp.usage),
            latency_ms=ms,
            model=getattr(resp, "model", self.model),
            stop_reason=resp.stop_reason,
        )


def from_spec(spec: str) -> Adapter:
    """Build an adapter from a CLI spec.

    ``anthropic:<model>``, ``ollama:<model>`` (http://localhost:11434/v1), or
    ``openai-compat:<model>@<base_url>``. Prices for openai-compat come from
    DETERMINAGENT_PRICE_IN and DETERMINAGENT_PRICE_OUT, the key from
    DETERMINAGENT_API_KEY.
    """
    kind, _, rest = spec.partition(":")
    if kind == "anthropic" and rest:
        return AnthropicAdapter(model=rest)
    env = os.environ
    prices = {
        "price_in": float(env.get("DETERMINAGENT_PRICE_IN", 0)),
        "price_out": float(env.get("DETERMINAGENT_PRICE_OUT", 0)),
    }
    if kind == "ollama" and rest:
        return OpenAICompatAdapter("http://localhost:11434/v1", rest, name=f"ollama:{rest}", **prices)
    if kind == "openai-compat" and "@" in rest:
        model, _, url = rest.partition("@")
        return OpenAICompatAdapter(url, model, api_key=env.get("DETERMINAGENT_API_KEY"), **prices)
    raise ValueError(f"Unknown model spec {spec!r}")
