"""One interface over free / open-weight model back-ends, with JSON validation, retry and fallback.

Back-ends (all free at run time):
  * llamacpp  - a local GGUF file (default: Qwen2.5-3B-Instruct Q4_K_M, Apache-2.0) via llama-cpp-python
  * ollama    - a local Ollama server (default model qwen2.5:7b-instruct)
  * gemini    - Google Gemini API free tier, OpenAI-compatible endpoint
  * groq      - Groq free tier, OpenAI-compatible endpoint
  * fake      - deterministic stand-in used by the tests
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Type

from pydantic import BaseModel, ValidationError

SEED = 42


@dataclass
class Call:
    stage: str
    backend: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    ok: bool
    attempt: int
    error: str = ""


@dataclass
class Ledger:
    calls: list[Call] = field(default_factory=list)

    def add(self, c: Call) -> None:
        self.calls.append(c)

    def totals(self) -> dict:
        return {
            "calls": len(self.calls),
            "failed_calls": sum(1 for c in self.calls if not c.ok),
            "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "completion_tokens": sum(c.completion_tokens for c in self.calls),
            "seconds": round(sum(c.seconds for c in self.calls), 1),
            "backends": sorted({f"{c.backend}:{c.model}" for c in self.calls if c.ok}),
        }


class Backend:
    name = "base"
    model = ""

    def chat(self, system: str, user: str, schema: dict) -> tuple[str, int, int]:
        """Return (text, prompt_tokens, completion_tokens)."""
        raise NotImplementedError


class LlamaCppBackend(Backend):
    name = "llamacpp"

    def __init__(self, model_path: str, n_ctx: int = 8192, threads: Optional[int] = None):
        from llama_cpp import Llama  # imported lazily so tests do not need it

        self.model = os.path.basename(model_path)
        self._llm = Llama(model_path=model_path, n_ctx=n_ctx, seed=SEED, verbose=False,
                          n_threads=threads or os.cpu_count())

    def chat(self, system, user, schema):
        out = self._llm.create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0, seed=SEED, max_tokens=1500,
            response_format={"type": "json_object", "schema": schema},
        )
        u = out.get("usage", {})
        return out["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


class OllamaBackend(Backend):
    name = "ollama"

    def __init__(self, model: str = "qwen2.5:7b-instruct", url: str = "http://localhost:11434"):
        self.model, self.url = model, url.rstrip("/")

    def chat(self, system, user, schema):
        import requests

        r = requests.post(f"{self.url}/api/chat", timeout=600, json={
            "model": self.model, "stream": False, "format": schema,
            "options": {"temperature": 0, "seed": SEED},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        r.raise_for_status()
        j = r.json()
        return j["message"]["content"], j.get("prompt_eval_count", 0), j.get("eval_count", 0)


class OpenAICompatBackend(Backend):
    """Gemini free tier and Groq free tier both expose an OpenAI-compatible chat endpoint."""

    PRESETS = {
        "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.0-flash"),
        "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.1-8b-instant"),
    }

    def __init__(self, preset: str, model: Optional[str] = None):
        base, env, default = self.PRESETS[preset]
        self.name, self.base, self.env = preset, base, env
        self.model = model or default
        if not os.environ.get(env):
            raise RuntimeError(f"{env} is not set")

    def chat(self, system, user, schema):
        import requests

        r = requests.post(f"{self.base}/chat/completions", timeout=120,
                          headers={"Authorization": f"Bearer {os.environ[self.env]}"},
                          json={"model": self.model, "temperature": 0, "seed": SEED,
                                "response_format": {"type": "json_object"},
                                "messages": [{"role": "system", "content": system + "\nReply with JSON only."},
                                             {"role": "user", "content": user}]})
        r.raise_for_status()
        j = r.json()
        u = j.get("usage", {})
        return j["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


class FakeBackend(Backend):
    """Answers from a Python function; used by tests and by the offline demo."""
    name = "fake"

    def __init__(self, fn: Callable[[str, str], str], model: str = "rules"):
        self.fn, self.model = fn, model

    def chat(self, system, user, schema):
        text = self.fn(system, user)
        return text, len(user) // 4, len(text) // 4


def _parse_json(text: str) -> object:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)


class Router:
    """Try back-ends in order; on each, retry once with the validation error fed back."""

    def __init__(self, backends: list[Backend], ledger: Optional[Ledger] = None, attempts: int = 2):
        if not backends:
            raise ValueError("no back-end available")
        self.backends, self.ledger, self.attempts = backends, ledger or Ledger(), attempts

    def json(self, stage: str, system: str, user: str, model_cls: Type[BaseModel],
             schema: Optional[dict] = None) -> BaseModel:
        schema = schema or model_cls.model_json_schema()
        last_err = ""
        for be in self.backends:
            prompt = user
            for attempt in range(1, self.attempts + 1):
                t0 = time.time()
                try:
                    text, pt, ct = be.chat(system, prompt, schema)
                except Exception as e:  # network down, model missing, quota -> next back-end
                    self.ledger.add(Call(stage, be.name, be.model, 0, 0, time.time() - t0, False, attempt, repr(e)[:200]))
                    last_err = repr(e)
                    break
                try:
                    obj = model_cls.model_validate(_parse_json(text))
                    self.ledger.add(Call(stage, be.name, be.model, pt, ct, time.time() - t0, True, attempt))
                    return obj
                except (ValidationError, ValueError) as e:
                    last_err = str(e)[:300]
                    self.ledger.add(Call(stage, be.name, be.model, pt, ct, time.time() - t0, False, attempt, last_err))
                    prompt = (user + "\n\nYour previous answer was rejected by the validator:\n" + last_err +
                              "\nReturn corrected JSON only.")
        raise RuntimeError(f"stage {stage}: every back-end failed; last error: {last_err}")


def build_router(order: Optional[str] = None, ledger: Optional[Ledger] = None) -> Router:
    """order: comma list such as 'llamacpp,gemini,groq,ollama'. Unavailable back-ends are skipped."""
    order = order or os.environ.get("IED_BACKENDS", "llamacpp,ollama,gemini,groq")
    backends: list[Backend] = []
    for name in [s.strip() for s in order.split(",") if s.strip()]:
        try:
            if name == "llamacpp":
                path = os.environ.get("IED_GGUF", "models/qwen2.5-3b-instruct-q4_k_m.gguf")
                if os.path.exists(path):
                    backends.append(LlamaCppBackend(path))
            elif name == "ollama":
                import requests
                url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
                requests.get(url, timeout=1)
                backends.append(OllamaBackend(os.environ.get("IED_OLLAMA_MODEL", "qwen2.5:7b-instruct"), url))
            elif name in OpenAICompatBackend.PRESETS:
                backends.append(OpenAICompatBackend(name))
        except Exception:
            continue
    return Router(backends, ledger)
