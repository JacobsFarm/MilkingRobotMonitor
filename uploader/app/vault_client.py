import json
import threading
import time
import urllib.error
import urllib.parse
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
    """Client for the real MetaState W3DS eVault.

    Flow (verified against docs.w3ds.metastate.foundation and the prototype
    repo's web3-adapter EVaultClient, 2026-07):

    1. Resolve the eVault endpoint of the configured w3id via the Registry:
       GET {registry_url}/resolve?w3id=@... -> eVault URI; GraphQL lives at /graphql.
    2. Obtain a platform token: POST {registry_url}/platforms/certification
       with {"platform": ...} -> {"token", "expiresAt"}. Refreshed near expiry.
    3. Every GraphQL call carries both "Authorization: Bearer <token>" and
       "X-ENAME: <w3id>" headers.
    4. Store via storeMetaEnvelope; the "ontology" is the W3ID (schemaId) of a
       JSON Schema pre-registered in the Ontology service, mapped per logical
       collection in settings under vault.schema_ids.
    5. Fetch via the cursor-paginated metaEnvelopes query filtered by ontology.

    Note: storeMetaEnvelope creates a new envelope on every call (not idempotent
    on our record id), so callers must deduplicate before storing — see pipeline.
    """

    TOKEN_REFRESH_MARGIN_SECONDS = 5 * 60
    PAGE_SIZE = 500

    STORE_MUTATION = """
        mutation StoreMetaEnvelope($input: MetaEnvelopeInput!) {
            storeMetaEnvelope(input: $input) {
                metaEnvelope { id ontology parsed }
            }
        }
    """

    FETCH_QUERY = """
        query MetaEnvelopes($filter: MetaEnvelopeFilterInput, $first: Int, $after: String) {
            metaEnvelopes(filter: $filter, first: $first, after: $after) {
                edges { node { parsed } }
                pageInfo { hasNextPage endCursor }
            }
        }
    """

    def __init__(self, registry_url, w3id, platform, schema_ids):
        self.registry_url = registry_url.rstrip("/")
        self.w3id = w3id
        self.platform = platform
        self.schema_ids = schema_ids or {}
        self._endpoint = None
        self._token = None
        self._token_expires_at = None  # seconds since epoch, or None

    # -- HTTP plumbing -----------------------------------------------------

    @staticmethod
    def _http_json(url, payload=None, headers=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def _resolve_endpoint(self):
        if self._endpoint:
            return self._endpoint
        url = f"{self.registry_url}/resolve?w3id={urllib.parse.quote(self.w3id)}"
        body = self._http_json(url)
        # TODO(evault): verify the exact response shape of /resolve against a
        # test registry; the adapter reads the eVault URI from it.
        uri = body.get("uri") or body.get("evault") or body.get("endpoint")
        if not uri:
            raise RuntimeError(f"Registry resolve returned no eVault URI for {self.w3id}: {body}")
        uri = uri.rstrip("/")
        self._endpoint = uri if uri.endswith("/graphql") else f"{uri}/graphql"
        return self._endpoint

    def _get_token(self):
        now = time.time()
        if self._token and (
            self._token_expires_at is None
            or now < self._token_expires_at - self.TOKEN_REFRESH_MARGIN_SECONDS
        ):
            return self._token
        body = self._http_json(
            f"{self.registry_url}/platforms/certification", {"platform": self.platform}
        )
        self._token = body["token"]
        expires_at = body.get("expiresAt")
        if expires_at:
            expires_at = float(expires_at)
            # The adapter treats expiresAt as a Unix timestamp; normalize
            # milliseconds to seconds if needed.
            if expires_at > 1e12:
                expires_at /= 1000.0
        self._token_expires_at = expires_at or None
        return self._token

    def _graphql(self, query, variables):
        endpoint = self._resolve_endpoint()
        for attempt in (1, 2):
            headers = {
                "Authorization": f"Bearer {self._get_token()}",
                "X-ENAME": self.w3id,
            }
            try:
                body = self._http_json(endpoint, {"query": query, "variables": variables}, headers)
            except urllib.error.HTTPError as error:
                if error.code in (401, 403) and attempt == 1:
                    self._token = None  # token expired or revoked: fetch a fresh one
                    continue
                raise
            if body.get("errors"):
                raise RuntimeError(body["errors"])
            return body["data"]

    def _schema_for(self, path):
        logical = path.split("/", 1)[0]
        schema_id = self.schema_ids.get(logical)
        if not schema_id:
            raise RuntimeError(
                f"No schema id configured for '{logical}'. Register the JSON Schema in the "
                "Ontology service and add its W3ID under vault.schema_ids in settings.json."
            )
        return schema_id

    # -- VaultClient interface ---------------------------------------------

    def store(self, path, record):
        self._graphql(
            self.STORE_MUTATION,
            {
                "input": {
                    "ontology": self._schema_for(path),
                    "payload": record,
                    "acl": ["*"],
                }
            },
        )

    def fetch_all(self, prefix):
        schema_id = self._schema_for(prefix)
        records = []
        after = None
        while True:
            data = self._graphql(
                self.FETCH_QUERY,
                {
                    # TODO(evault): verify the filter field name (ontologyId vs
                    # ontology) against the deployed eVault schema.
                    "filter": {"ontologyId": schema_id},
                    "first": self.PAGE_SIZE,
                    "after": after,
                },
            )
            connection = data["metaEnvelopes"]
            records.extend(edge["node"]["parsed"] for edge in connection["edges"])
            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                return records
            after = page_info.get("endCursor")

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
            vault_config["registry_url"],
            vault_config["w3id"],
            vault_config.get("platform", "melkmonitor"),
            vault_config.get("schema_ids", {}),
        )
    return LocalVaultClient(vault_config["local_path"])
