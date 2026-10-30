"""Provider-agnostic LLM layer (BUILD_PLAN R5).

Talks to any OpenAI-compatible endpoint, configured by environment:
  LLM_BASE_URL   default http://localhost:8080/v1  (his Hyperspace node)
  LLM_API_KEY    optional; local endpoints need none
  LLM_MODEL      default "default"
  VRA_OFFLINE=1  force deterministic offline mode

CRITICAL DESIGN RULE: the pipeline must run end-to-end with no LLM at
all. `LLMClient.available()` probes the endpoint once (short timeout);
when it is unreachable, or offline mode is forced, every LLM stage
degrades to deterministic template/extractive behaviour and the run
stays fully reproducible. Failures are recorded in `self.errors`,
never silently swallowed (pattern from multi-agent-evidence/src/llm.py).
"""
from __future__ import annotations

import os
from typing import Optional

import requests


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None, timeout: float = 30.0):
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL")
                         or "http://localhost:8080/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY") or ""
        self.model = model or os.environ.get("LLM_MODEL") or "default"
        self.timeout = timeout
        self.forced_offline = os.environ.get("VRA_OFFLINE", "") == "1"
        self.calls: list[dict] = []
        self.errors: list[str] = []
        self._available: Optional[bool] = None

    def available(self) -> bool:
        """One-shot probe. Offline when forced or the endpoint is dead."""
        if self.forced_offline:
            if self._available is None:
                self.errors.append("offline mode forced by VRA_OFFLINE=1")
            self._available = False
            return False
        if self._available is None:
            try:
                r = requests.get(f"{self.base_url}/models", timeout=3,
                                 headers=self._headers())
                self._available = r.status_code < 500
                if not self._available:
                    self.errors.append(f"LLM probe: HTTP {r.status_code} from {self.base_url}")
            except requests.RequestException as e:
                self._available = False
                self.errors.append(f"LLM probe failed ({self.base_url}): {e}")
        return bool(self._available)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def chat(self, prompt: str, label: str = "", max_tokens: int = 700) -> str:
        """One chat completion. Raises LLMError when unavailable/failing;
        callers in the graph catch it and fall back to templates."""
        if not self.available():
            raise LLMError(f"LLM unavailable (offline) — stage '{label}' must degrade")
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                json={"model": self.model,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": max_tokens},
                headers=self._headers(), timeout=self.timeout)
            r.raise_for_status()
            out = r.json()
            content = out["choices"][0]["message"]["content"]
            usage = out.get("usage") or {}
            self.calls.append({"label": label,
                               "prompt_tokens": usage.get("prompt_tokens", 0),
                               "completion_tokens": usage.get("completion_tokens", 0)})
            return content
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            self.errors.append(f"LLM call failed ({label}): {e}")
            raise LLMError(str(e)) from e

    def usage(self) -> dict:
        return {"mode": "llm" if self.available() else "offline",
                "base_url": self.base_url, "model": self.model,
                "calls": len(self.calls),
                "prompt_tokens": sum(c["prompt_tokens"] for c in self.calls),
                "completion_tokens": sum(c["completion_tokens"] for c in self.calls),
                "errors": list(self.errors)}
