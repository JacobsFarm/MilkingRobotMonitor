# Uploader

Independent background program (the "writer"). It reads raw input files, normalizes them into vault records, and pushes them to the MetaState eVault. It never talks to the dashboard directly — the eVault is the only shared channel, documented in [`VAULT_SCHEMA.json`](../VAULT_SCHEMA.json) at the repo root.

## Pipeline

1. **Parse** — each configured [data source](#data-sources) reads its own raw input (e.g. `MilkingRobotSource` reads FULLSENSE `*.txt` files, `sep=,` header lines skipped).
2. **Transform** — the source normalizes every raw row into a versioned record (`schema_version`, a globally unique `id`, `source`, and its raw measured values — never derived ones; see `record_schema` on the source class, or the generated `VAULT_SCHEMA.json`).
3. **Deduplicate** — records are deduplicated by `id` before storing (the real eVault creates a new envelope on every store; there is no overwrite-on-id). A local sync-state file (`state/<collection>.json`, evault mode only) tracks which ids already made it in, so a normal run doesn't need to re-crawl the whole eVault — see `app/state.py`.
4. **Store** — local mode writes to `<collection>/<subject>/<id>`; evault mode bulk-stores each record as a MetaEnvelope via `bulkCreateMetaEnvelopes`, chunked to stay under the eVault's rate limit.

## Data sources

Everything the uploader reads is a `DataSource` (`app/sources/base.py`): it knows how to `parse()` its raw input, `transform()` one raw row into a record, and which vault `collection` it belongs to.

| Source type | Input | Collection |
|---|---|---|
| `milking_robot` | FULLSENSE `*.txt` milking control files | `milking_controle_data` |
| `feed_distribution` | `Voerdistributie-rapport*.csv` (feed per milking visit) | `feed_distribution_data` |
| `production_report` | `Productie-rapport*.csv` — **the report date must be in the file name** (e.g. `Productie-rapport_5-7-2026.csv`); dateless files are skipped | `milking_production_data` |

Sources may report overlapping quantities measured by different parties (the robot and CRV both track lactation). Writers never merge or overwrite: each source stores its own records with its own `source` tag, and `field_authority` in [`VAULT_SCHEMA.json`](../VAULT_SCHEMA.json) tells readers which source to prefer per quantity.

Adding a new kind of data (health events, a third-party sensor, ...) means adding one new source, **not** touching the pipeline, vault clients, dedup state, or dashboard:

1. Subclass `DataSource` in a new module under `app/sources/`.
2. Declare `record_schema` and `path_pattern` on it (self-documenting — see `milking_robot.py` for the pattern).
3. Register the class in `app/sources/__init__.py`.
4. Add a `sources` entry with its settings in `config/settings.json`.
5. Run `python generate_vault_schema.py` **from the repo root** to refresh `VAULT_SCHEMA.json`, so readers (the dashboard, the agent, ...) know the new collection exists without reading this source's code.

## Folder layout

```
uploader/
├── run.py                     Entry point
├── test_evault.py             Standalone live-eVault store+fetch self-test
├── config/
│   └── settings.json          All settings (sources, vault mode, registry)
├── state/                     Local sync state per collection (evault mode; gitignored)
├── app/                       Backend
│   ├── config.py               Loads settings, resolves paths, legacy-config migration
│   ├── sources/
│   │   ├── base.py             DataSource contract (see "Data sources" above)
│   │   └── milking_robot.py    FULLSENSE milking-robot files
│   ├── state.py                Local sync state (SyncState) — see "Pipeline" step 3
│   ├── pipeline.py             Orchestrates source.records() -> dedup -> vault.store_many()
│   └── vault_client.py         Vault backends (local + MetaState eVault)
└── reference/scheme.json      Original FULLSENSE column reference (raw robot export)
```

## Usage

First create your local settings from the template (the real `settings.json` is gitignored):

```
copy config\settings.example.json config\settings.json
```

Then run from inside the `uploader/` folder:

```
python run.py                  # single run
python run.py --watch          # keep running, re-scan every watch_interval_seconds
python run.py --rebuild-state  # discard local sync state and re-crawl the vault once
```

Standard library only — no `pip install` needed.

## Settings (`config/settings.json`)

Paths are relative to the `uploader/` folder.

- `sources` — array of data source configs, each `{"type": ..., "collection": ..., ...source-specific keys}`. For `milking_robot`: `data_directory`, `file_pattern`. (Legacy top-level `data_directory` / `file_pattern` / `base_path` still works and is converted automatically to a single `milking_robot` source.)
- `vault.mode` — `local` (file-based vault for development/testing) or `evault` (real MetaState W3DS eVault over GraphQL).
- `vault.local_path` — where the local test vault is written (local mode).
- `vault.registry_url` — base URL of the W3DS Registry (evault mode): `https://registry.w3ds.metastate.foundation` in production. Used to resolve the eVault endpoint (`GET /resolve?w3id=...`) and to obtain a platform token (`POST /platforms/certification`).
- `vault.w3id` — the w3id (eName) whose eVault the records are stored in; also sent as the `X-ENAME` header on every GraphQL call.
- `vault.platform` — platform name sent when requesting a certification token (any name works, no pre-registration needed).
- `vault.schema_ids` — optional map of collection name → registered Ontology W3ID. Without an entry, the collection name itself is used as the ontology id (works fine for store/fetch); only needed for cross-platform interop.

The GraphQL operations in [`core/vault_client.py`](../core/vault_client.py) are verified against the live production eVault (schema introspection, see the project root memory / commit history) — `storeMetaEnvelope` / `bulkCreateMetaEnvelopes` to write, paginated `metaEnvelopes` filtered by `ontologyId` to read. All vault access goes through the `VaultClient` interface, so adding another backend only requires a new implementation of that class.

## What's actually in the vault

Don't guess field names from this README or from reading `app/sources/*.py` — read [`VAULT_SCHEMA.json`](../VAULT_SCHEMA.json) at the repo root. It's generated (not hand-written) from each source's declared `record_schema`, so it can't drift from the code the way prose docs do. Regenerate it after any source change with `python generate_vault_schema.py` from the repo root.

The eVault transport moved from `app/vault_client.py` to [`core/vault_client.py`](../core/vault_client.py) when the agent was added, so the rate-limiting, retry and pagination logic is shared between the Python programs instead of duplicated.
