import json
import threading
import time
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path


class VaultClient(ABC):

    @abstractmethod
    def store(self, path, record):
        raise NotImplementedError

    @abstractmethod
    def fetch_all(self, prefix):
        raise NotImplementedError

    @abstractmethod
    def subscribe(self, prefix, callback, interval_seconds=5):
        raise NotImplementedError


class LocalVaultClient(VaultClient):
    """File-based stand-in for the eVault: one JSON file per subject (e.g. per animal),
    containing all its records keyed by unique id. Avoids one-file-per-record, which
    does not scale on a local filesystem once thousands of records accumulate."""

    def __init__(self, root_directory):
        self.root = Path(root_directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _subject_file(self, prefix, subject_id):
        directory = self.root.joinpath(*prefix.split("/"))
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{subject_id}.json"

    @staticmethod
    def _read_subject_file(file_path):
        if not file_path.exists():
            return {}
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def store(self, path, record):
        prefix, subject_id, unique_id = path.rsplit("/", 2)
        file_path = self._subject_file(prefix, subject_id)
        with self._lock:
            records = self._read_subject_file(file_path)
            records[unique_id] = record
            file_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    def fetch_all(self, prefix):
        directory = self.root.joinpath(*prefix.split("/"))
        if not directory.exists():
            return []
        records = []
        for file_path in sorted(directory.glob("*.json")):
            records.extend(self._read_subject_file(file_path).values())
        return records

    def subscribe(self, prefix, callback, interval_seconds=5):
        def poll():
            known_versions = {}
            directory = self.root.joinpath(*prefix.split("/"))
            while True:
                if directory.exists():
                    for file_path in directory.glob("*.json"):
                        modified = file_path.stat().st_mtime
                        if known_versions.get(file_path) != modified:
                            known_versions[file_path] = modified
                            for record in self._read_subject_file(file_path).values():
                                callback(record)
                time.sleep(interval_seconds)

        thread = threading.Thread(target=poll, daemon=True)
        thread.start()
        return thread


class MetaStateEVaultClient(VaultClient):

    def __init__(self, endpoint, epassport_path, ontology="milking_controle_data"):
        self.endpoint = endpoint
        self.ontology = ontology
        self.epassport = json.loads(Path(epassport_path).read_text(encoding="utf-8"))
        self.token = self._authenticate()

    def _authenticate(self):
        data = self._graphql(
            "mutation Login($ePassport: String!) { login(ePassport: $ePassport) { token } }",
            {"ePassport": self.epassport.get("credential", "")},
            authenticated=False,
        )
        return data["login"]["token"]

    def _graphql(self, query, variables, authenticated=True):
        payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        if authenticated:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request) as response:
            body = json.loads(response.read().decode("utf-8"))
        if body.get("errors"):
            raise RuntimeError(body["errors"])
        return body["data"]

    def store(self, path, record):
        self._graphql(
            """
            mutation Store($input: MetaEnvelopeInput!) {
                storeMetaEnvelope(input: $input) { metaEnvelope { id } }
            }
            """,
            {
                "input": {
                    "ontology": self.ontology,
                    "payload": {**record, "path": path},
                    "acl": ["*"],
                }
            },
        )

    def fetch_all(self, prefix):
        data = self._graphql(
            """
            query Fetch($ontology: String!, $term: String!) {
                findMetaEnvelopesBySearchTerm(ontology: $ontology, term: $term) { parsed }
            }
            """,
            {"ontology": self.ontology, "term": prefix},
        )
        return [envelope["parsed"] for envelope in data["findMetaEnvelopesBySearchTerm"]]

    def subscribe(self, prefix, callback, interval_seconds=5):
        def poll():
            known = set()
            while True:
                try:
                    for record in self.fetch_all(prefix):
                        key = record.get("id")
                        if key not in known:
                            known.add(key)
                            callback(record)
                except (RuntimeError, OSError):
                    pass
                time.sleep(interval_seconds)

        thread = threading.Thread(target=poll, daemon=True)
        thread.start()
        return thread


def create_vault_client(vault_config):
    mode = vault_config.get("mode", "local")
    if mode == "evault":
        return MetaStateEVaultClient(
            vault_config["endpoint"],
            vault_config["epassport_path"],
            vault_config.get("ontology", "milking_controle_data"),
        )
    return LocalVaultClient(vault_config["local_path"])
