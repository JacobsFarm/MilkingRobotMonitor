"""Ollama backend — local processing, no API key, works offline.

Runs against an `ollama serve` instance (default http://localhost:11434).
Standard library only, like the rest of the Python code in this project.

Model choice: any chat model works for interpreting the numbers this agent
computes. Gemma is a good fit here because the agent never asks the model to
call tools -- it only asks it to interpret findings that Python already
calculated. (For agentic tool-calling loops, models trained for it such as
Qwen 2.5 or Llama 3.1+ are the safer pick.)

One caveat when running a reasoning model such as qwen3: its thinking tokens are
generated inside the same window and before the JSON, so with `format: json` it
can spend the budget reasoning and return a truncated object. Either use an
instruct variant, disable thinking, or give it a generous num_ctx.
"""

import json
import logging
import urllib.error
import urllib.request

from app.llm.base import LLMClient, LLMError

logger = logging.getLogger("agent.llm")

# Rough characters-per-token ratio, only used to warn before a prompt silently
# overflows the context window. Deliberately pessimistic: JSON with many digits
# and field names tokenizes worse than prose.
CHARS_PER_TOKEN = 3
# Leave room for the reply inside num_ctx -- Ollama counts prompt and response
# against the same window.
RESPONSE_HEADROOM_TOKENS = 1024


class OllamaClient(LLMClient):

    def __init__(
        self,
        host,
        model,
        temperature=0.2,
        timeout_seconds=180,
        num_ctx=16384,
        num_predict=None,
    ):
        self.host = host.rstrip("/")
        self.model = model
        # Low temperature: this is analysis, not creative writing -- we want
        # the same numbers to yield the same conclusions.
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        # Ollama's own default context window is small (4k on current builds)
        # and it truncates the prompt to fit WITHOUT reporting it. With a few
        # dozen findings that silently drops the tail of the batch: the model
        # answers about the findings it still saw, the rest fall back to their
        # machine-written summary, and nothing anywhere says why. So we always
        # send an explicit value rather than inheriting the default.
        self.num_ctx = num_ctx
        self.num_predict = num_predict

    def name(self):
        return f"ollama:{self.model}"

    def available(self):
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def _warn_if_prompt_is_large(self, system_prompt, user_prompt):
        estimated = (len(system_prompt) + len(user_prompt)) // CHARS_PER_TOKEN
        if estimated + RESPONSE_HEADROOM_TOKENS > self.num_ctx:
            logger.warning(
                "Prompt is roughly %d tokens against num_ctx=%d -- Ollama will "
                "truncate it silently and the last findings in this batch will "
                "lose their wording. Raise llm.num_ctx or lower "
                "llm.max_findings_per_request in config/settings.json.",
                estimated,
                self.num_ctx,
            )

    def complete_json(self, system_prompt, user_prompt):
        self._warn_if_prompt_is_large(system_prompt, user_prompt)
        options = {"temperature": self.temperature, "num_ctx": self.num_ctx}
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
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
            "options": options,
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
