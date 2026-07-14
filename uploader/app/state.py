"""Local sync state: which record ids are already in the eVault, per collection.

The real eVault has no overwrite-on-id, so the uploader must deduplicate before
storing. Crawling the whole eVault for existing ids on every run is expensive
(the server pages at 100 records and rate-limits), so we keep the set of
uploaded ids in a local JSON file and only rebuild it from the vault when the
file is missing, unreadable, or belongs to a different vault (fingerprint
mismatch — e.g. the registry URL or w3id changed).

State is updated after every successfully stored chunk, so an interrupted run
never re-uploads what already landed.
"""

import json
from pathlib import Path


class SyncState:

    def __init__(self, file_path, fingerprint):
        self.path = Path(file_path)
        self.fingerprint = fingerprint
        #: set of known-uploaded ids, or None when the state must be rebuilt
        #: from the vault first.
        self.known = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            if data.get("fingerprint") == fingerprint:
                self.known = set(data.get("ids", []))

    def replace(self, ids):
        self.known = set(ids)
        self._save()

    def add(self, ids):
        if self.known is None:
            self.known = set()
        self.known.update(ids)
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fingerprint": self.fingerprint, "ids": sorted(self.known)}
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        temp_path.replace(self.path)  # atomic: never leaves a half-written file
