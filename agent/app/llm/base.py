"""LLM backend contract.

Same idea as core.vault_client.VaultClient: one interface, swappable backends.
Today: Ollama (local, free, offline). Adding a hosted model later (Claude,
OpenAI, ...) means one new subclass plus a registry entry — no changes to the
analysis or storage code.
"""

from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """Raised when the model is unreachable or returns something unusable."""


class LLMClient(ABC):

    @abstractmethod
    def name(self):
        """Identifier of the model actually used, stored on every insight so
        you can tell later which model produced which conclusion."""
        raise NotImplementedError

    @abstractmethod
    def complete_json(self, system_prompt, user_prompt):
        """Send a prompt and return the parsed JSON object the model replied with.

        Implementations must ask the backend for JSON output and raise LLMError
        if the reply cannot be parsed — callers rely on getting a dict.
        """
        raise NotImplementedError

    def available(self):
        """Cheap reachability check, so a scheduled run can fail with a clear
        message instead of a stack trace. Backends should override."""
        return True
