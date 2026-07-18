"""Local copy of a vault collection.

Reading a large collection from the real eVault is expensive: the server pages
at 100 records and rate-limits hard, so a full read of tens of thousands of
records takes minutes. An agent that re-reads everything on every run would
spend most of its time waiting and would compete with the uploader for the
same rate limit.

So the agent keeps a local copy and only does a full read when it has none (or
when told to refresh). This is the same "local read model" pattern the
dashboard uses in memory, persisted to disk here because the agent is a
short-lived scheduled process.
"""

import json
from pathlib import Path


class RecordCache:

    def __init__(self, file_path, fingerprint):
        self.path = Path(file_path)
        # Identifies which vault the cache belongs to; a different registry or
        # w3id invalidates it rather than silently mixing farms.
        self.fingerprint = fingerprint

    def load(self):
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if data.get("fingerprint") != self.fingerprint:
            return None
        return data.get("records")

    def save(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fingerprint": self.fingerprint, "records": records}
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        temp_path.replace(self.path)  # atomic: never leaves a half-written file


def load_records(vault, collection, cache, refresh, logger):
    """Return the collection's records, re-reading the vault only when needed.

    The vault offers no way to fetch just the new records (see
    core.vault_client.count), so the choice is all-or-nothing. Comparing the
    vault's record count against the cache costs one request and decides it:
    unchanged means the cache is still exact, and a minutes-long read is
    skipped entirely.
    """
    cached = None if refresh else cache.load()
    if cached is not None:
        try:
            live_count = vault.count(collection)
        except (RuntimeError, OSError) as error:
            logger.warning(
                "Could not check '%s' for new records (%s); using the cached "
                "copy, which may be out of date.",
                collection,
                error,
            )
            return cached
        if live_count == len(cached):
            logger.info(
                "Cache for '%s' is current (%d records) -- no vault read needed.",
                collection,
                live_count,
            )
            return cached
        logger.info(
            "Vault holds %d records for '%s', cache has %d -- re-reading.",
            live_count,
            collection,
            len(cached),
        )

    logger.info(
        "Reading '%s' from the vault -- on the real eVault this pages at 100 "
        "records at a time and can take minutes.",
        collection,
    )
    records = vault.fetch_all(collection)
    cache.save(records)
    logger.info("Read and cached %d records", len(records))
    return records
