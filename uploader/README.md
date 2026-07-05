# Uploader

Independent background program (the "writer"). It reads raw milking control files, cleans and transforms them, and pushes the records to the MetaState eVault. It never talks to the dashboard directly — the eVault is the only shared channel.

## Pipeline

1. **Parse** — reads every `*.txt` file in the configured data directory (FULLSENSE column layout, `sep=,` header lines are skipped).
2. **Transform** — keeps the yield **raw** (`yield_raw`, exactly as the robot reported it) so the stored data stays machine-readable for a future AI layer; converting to liters is the job of the dashboards at display time. Drops `systemCode`, `frameNumber` and `bottleNumber`, normalizes the status to `OK` / `!` / `#`, and stamps each record with a `schema_version` and `source`. Records whose `animalNumber` is not exactly 4 digits are ignored.
3. **Deduplicate** — builds a unique id `animalNumber_YYYY-MM-DDTHH-MM-SS`; a re-upload overwrites the same record instead of creating a duplicate.
4. **Store** — writes each record to the vault path `milking_controle_data/[animalNumber]/[unique_id]`.

## Folder layout

```
uploader/
├── run.py               Entry point
├── config/
│   ├── settings.json    All settings (data path, vault mode, endpoint)
│   └── epassport.example.json
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
- `vault.mode` — `local` (file-based vault for development/testing) or `evault` (real MetaState eVault over GraphQL).
- `vault.local_path` — where the local test vault is written.
- `vault.endpoint` — GraphQL endpoint of the eVault (used in `evault` mode).
- `vault.epassport_path` — JSON file with the farm ePassport credential. Copy `config/epassport.example.json` to `config/epassport.json` and fill it in. Never commit the real file.

The GraphQL operations in `app/vault_client.py` (`login`, `storeMetaEnvelope`, `findMetaEnvelopesBySearchTerm`) follow the MetaState eVault core API conceptually; verify the exact schema of your deployed eVault and adjust the queries in `MetaStateEVaultClient` if needed. All vault access goes through the `VaultClient` interface, so adding another backend or data source only requires a new implementation of that class.
