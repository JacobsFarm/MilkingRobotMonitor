"""Ollama backend — local processing, no API key, works offline.

Runs against an `ollama serve` instance (default http://localhost:11434).
Standard library only, like the rest of the Python code in this project.

Model choice: any chat model works for interpreting the numbers this agent
computes. Gemma is a good fit here because the agent never asks the model to
call tools -- it only asks it to interpret findings that Python already
calculated. (For agentic tool-calling loops, models trained for it such as
Qwen 2.5 or Llama 3.1+ are the safer pick.)
"""

import json
import urllib.error
import urllib.request

from app.llm.base import LLMClient, LLMError


class OllamaClient(LLMClient):

    def __init__(self, host, model, temperature=0.2, timeout_seconds=180):
        self.host = host.rstrip("/")
        self.model = model
        # Low temperature: this is analysis, not creative writing -- we want
        # the same numbers to yield the same conclusions.
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds

    def name(self):
        return f"ollama:{self.model}"

    def available(self):
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def complete_json(self, system_prompt, user_prompt):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            # Ollama constrains decoding to valid JSON, so we don't have to
            # scrape a code block out of prose.
            "format": "json",
            "options": {"temperature": self.temperature},
        }
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise LLMError(f"Ollama returned HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, OSError) as error:
            raise LLMError(
                f"Cannot reach Ollama at {self.host} ({error}). "
                "Is `ollama serve` running?"
            ) from error

        content = (body.get("message") or {}).get("content", "")
        if not content.strip():
            raise LLMError("Ollama returned an empty response")
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            raise LLMError(f"Model reply was not valid JSON: {content[:300]}") from error
