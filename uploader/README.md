# Uploader

Independent background program (the "writer"). It reads raw milking control files, cleans and transforms them, and pushes the records to the MetaState eVault. It never talks to the dashboard directly — the eVault is the only shared channel.

## Pipeline

1. **Parse** — reads every `*.txt` file in the configured data directory (FULLSENSE column layout, `sep=,` header lines are skipped).
2. **Transform** — keeps the yield **raw** (`yield_raw`, exactly as the robot reported it) so the stored data stays machine-readable for a future AI layer; converting to liters is the job of the dashboards at display time. Drops `systemCode`, `frameNumber` and `bottleNumber`, normalizes the status to `OK` / `!` / `#`, and stamps each record with a `schema_version` and `source`. Records whose `animalNumber` is not exactly 4 digits are ignored.
3. **Deduplicate** — builds a unique id `animalNumber_YYYY-MM-DDTHH-MM-SS`, then fetches the ids already present in the vault and only uploads new records (the real eVault creates a new envelope per store, so overwrite-on-id is not available there).
4. **Store** — local mode writes to `milking_controle_data/[animalNumber]/[unique_id]`; evault mode stores each record as a MetaEnvelope whose ontology is the registered schema id.

## Folder layout

```
uploader/
├── run.py               Entry point
├── config/
│   └── settings.json    All settings (data path, vault mode, registry)
├── app/                 Backend
│   ├── config.py        Loads settings and resolves paths
│   ├── parser.py        Reads the raw FULLSENSE files
│   ├── transformer.py   Cleans and transforms records
│   ├── pipeline.py      Orchestrates parse -> transform -> store
│   └── vault_client.py  Vault backends (local + MetaState eVault)
└── reference/scheme.json
```

## Usage

First create your local settings from the template (the real `settings.json` is gitignored):

```
copy config\settings.example.json config\settings.json
```

Then run from inside the `uploader/` folder:

```
python run.py            # single run
python run.py --watch    # keep running, re-scan every watch_interval_seconds
```

Standard library only — no `pip install` needed.

## Settings (`config/settings.json`)

Paths are relative to the `uploader/` folder.

- `data_directory` — folder with the raw milking control files.
- `vault.mode` — `local` (file-based vault for development/testing) or `evault` (real MetaState W3DS eVault over GraphQL).
- `vault.local_path` — where the local test vault is written (local mode).
- `vault.registry_url` — base URL of the W3DS Registry (evault mode). Used to resolve the eVault endpoint (`GET /resolve?w3id=...`) and to obtain a platform token (`POST /platforms/certification`).
- `vault.w3id` — the w3id (eName) whose eVault the records are stored in; also sent as the `X-ENAME` header on every GraphQL call.
- `vault.platform` — platform name sent when requesting a certification token.
- `vault.schema_ids` — map of logical collection name → W3ID (schemaId) of the JSON Schema registered in the Ontology service. The schema **must be registered before the first upload**; the schemaId is what goes into the MetaEnvelope `ontology` field.

The GraphQL operations in `app/vault_client.py` (`storeMetaEnvelope`, paginated `metaEnvelopes`) match the MetaState prototype's eVault core API (see the web3-adapter `EVaultClient`). Two details are marked `TODO(evault)` in the code and should be verified against your deployed eVault: the exact `/resolve` response shape and the filter field name (`ontologyId` vs `ontology`). All vault access goes through the `VaultClient` interface, so adding another backend or data source only requires a new implementation of that class.
