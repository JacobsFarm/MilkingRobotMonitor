import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger("uploader.vault")


class VaultClient(ABC):

    @abstractmethod
    def store(self, path, record):
        raise NotImplementedError

    def store_many(self, items, on_stored=None):
        """Store many (path, record) pairs. Default: one store() per item.
        Backends with a native bulk API (the real eVault) override this to send
        chunked requests, which is both faster and avoids per-record rate limits.
        ``on_stored(records)`` is called after every successfully stored batch,
        so callers can persist sync state incrementally."""
        for path, record in items:
            self.store(path, record)
            if on_stored:
                on_stored([record])

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

    Flow (verified 2026-07 against the live production registry/eVault via
    GraphQL introspection, plus the prototype repo's web3-adapter EVaultClient):

    1. Resolve the eVault endpoint of the configured w3id via the Registry:
       GET {registry_url}/resolve?w3id=@... -> {"uri": ...}; the GraphQL endpoint
       is always /graphql on that URI's origin.
    2. Obtain a platform token: POST {registry_url}/platforms/certification
       with {"platform": ...} -> {"token"} (optional "expiresAt"). Any platform
       name is accepted; the token is refreshed near expiry / on 401.
    3. Every GraphQL call carries both "Authorization: Bearer <token>" and
       "X-ENAME: <w3id>" headers.
    4. Store via storeMetaEnvelope(input: {ontology, payload, acl}). The
       "ontology" is any stable schema identifier: a plain logical name works
       (the adapter itself stores ontology "reference"); registering it as a
       JSON Schema W3ID in the Ontology service is only needed so *other*
       platforms can interpret the data. Mapped per collection under
       vault.schema_ids.
    5. Fetch via the cursor-paginated metaEnvelopes query filtered by ontologyId.

    Note: storeMetaEnvelope creates a new envelope on every call (not idempotent
    on our record id), so callers must deduplicate before storing — see pipeline.
    """

    TOKEN_REFRESH_MARGIN_SECONDS = 5 * 60
    PAGE_SIZE = 500
    BULK_CHUNK_SIZE = 200  # records per bulkCreateMetaEnvelopes call
    MAX_RETRIES = 5
    MAX_BACKOFF_SECONDS = 30

    STORE_MUTATION = """
        mutation StoreMetaEnvelope($input: MetaEnvelopeInput!) {
            storeMetaEnvelope(input: $input) {
                metaEnvelope { id ontology parsed }
            }
        }
    """

    BULK_STORE_MUTATION = """
        mutation BulkCreate($inputs: [BulkMetaEnvelopeInput!]!) {
            bulkCreateMetaEnvelopes(inputs: $inputs) {
                successCount
                errorCount
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
        # Resolve response: {"ename", "uri", "evault", ...}; "uri" is the eVault
        # origin (e.g. "http://host:4000"). "evault" is an id, not a URL.
        uri = body.get("uri")
        if not uri:
            raise RuntimeError(f"Registry resolve returned no eVault URI for {self.w3id}: {body}")
        # GraphQL always lives at /graphql on the eVault's origin, ignoring any
        # path the resolved URI may carry (matches the web3-adapter EVaultClient).
        parts = urllib.parse.urlsplit(uri)
        self._endpoint = f"{parts.scheme}://{parts.netloc}/graphql"
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
        token_refreshed = False
        for attempt in range(self.MAX_RETRIES):
            headers = {
                "Authorization": f"Bearer {self._get_token()}",
                "X-ENAME": self.w3id,
            }
            try:
                body = self._http_json(endpoint, {"query": query, "variables": variables}, headers)
            except urllib.error.HTTPError as error:
                if error.code in (401, 403) and not token_refreshed:
                    self._token = None  # token expired or revoked: fetch a fresh one
                    token_refreshed = True
                    continue
                # 429 Too Many Requests / 5xx are transient: back off and retry.
                if (error.code == 429 or 500 <= error.code < 600) and attempt < self.MAX_RETRIES - 1:
                    self._sleep_backoff(error, attempt)
                    continue
                raise
            if body.get("errors"):
                raise RuntimeError(body["errors"])
            return body["data"]
        raise RuntimeError("GraphQL request failed after retries")

    def _sleep_backoff(self, error, attempt):
        retry_after = None
        headers = getattr(error, "headers", None)
        if headers is not None:
            value = headers.get("Retry-After")
            if value:
                try:
                    retry_after = float(value)
                except ValueError:
                    retry_after = None
        delay = retry_after if retry_after is not None else min(2 ** attempt, self.MAX_BACKOFF_SECONDS)
        time.sleep(delay)

    def _schema_for(self, path):
        # Without an explicit mapping the collection name itself is the
        # ontology id (a plain stable string works — store and fetch just have
        # to agree). Register a JSON Schema in the Ontology service and map its
        # W3ID under vault.schema_ids for cross-platform interop.
        logical = path.split("/", 1)[0]
        return self.schema_ids.get(logical, logical)

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

    def store_many(self, items, on_stored=None):
        # Group by ontology (derived from each path) and send each group as a
        # few bulk requests instead of one request per record — this is what
        # keeps large uploads under the eVault's per-request rate limit.
        groups = {}
        for path, record in items:
            groups.setdefault(self._schema_for(path), []).append(record)
        total = sum(len(records) for records in groups.values())
        done = 0
        for ontology, records in groups.items():
            for start in range(0, len(records), self.BULK_CHUNK_SIZE):
                chunk = records[start : start + self.BULK_CHUNK_SIZE]
                inputs = [
                    {"ontology": ontology, "payload": record, "acl": ["*"]}
                    for record in chunk
                ]
                data = self._graphql(self.BULK_STORE_MUTATION, {"inputs": inputs})
                result = data["bulkCreateMetaEnvelopes"]
                if result.get("errorCount"):
                    raise RuntimeError(
                        f"bulkCreateMetaEnvelopes: {result['errorCount']} of "
                        f"{len(chunk)} records failed for ontology '{ontology}'"
                    )
                if on_stored:
                    on_stored(chunk)
                done += len(chunk)
                logger.info("eVault upload progress: %d/%d records", done, total)

    def fetch_all(self, prefix):
        schema_id = self._schema_for(prefix)
        records = []
        after = None
        while True:
            data = self._graphql(
                self.FETCH_QUERY,
                {
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
