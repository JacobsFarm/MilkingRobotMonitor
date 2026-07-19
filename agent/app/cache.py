"""Local copy of a vault collection.

The implementation moved to core/record_cache.py so the chatbot can share it
(same reason core/vault_client.py is shared: the eVault's paging and
rate-limiting quirks should be handled in exactly one place). This module
stays as the agent's import point.
"""

from core.record_cache import RecordCache, load_records

__all__ = ["RecordCache", "load_records"]
