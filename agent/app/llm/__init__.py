"""Registry of available LLM backends.

Explicit imports (no dynamic discovery), mirroring app/sources in the uploader.
Add a hosted backend here when you want one; the rest of the agent is unaware
of which model it is talking to.
"""

from app.llm.base import LLMClient, LLMError
from app.llm.ollama import OllamaClient

LLM_TYPES = {"ollama": OllamaClient}


def create_llm_client(llm_config):
    provider = llm_config.get("provider", "ollama")
    if provider not in LLM_TYPES:
        known = ", ".join(sorted(LLM_TYPES))
        raise ValueError(f"Unknown LLM provider '{provider}' (registered: {known})")
    if provider == "ollama":
        return OllamaClient(
            host=llm_config.get("host", "http://localhost:11434"),
            model=llm_config.get("model", "gemma3"),
            temperature=llm_config.get("temperature", 0.2),
            timeout_seconds=llm_config.get("timeout_seconds", 180),
            num_ctx=llm_config.get("num_ctx", 16384),
            num_predict=llm_config.get("num_predict"),
        )
    raise ValueError(f"No constructor wired for provider '{provider}'")


__all__ = ["LLMClient", "LLMError", "OllamaClient", "create_llm_client", "LLM_TYPES"]
