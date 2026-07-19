# Melkmonitor

A modular system for managing milking control data, using a MetaState eVault as the central, decentralized data store. It consists of fully independent programs that communicate only through the eVault — there is no direct API between them.

```
                 ┌────────────┐        ┌──────────────┐        ┌───────────────┐
   raw files ───▶│  Uploader  │ ─────▶ │    eVault     │ ─────▶ │  Dashboards   │
   (data/)       │  (writer)  │  store │ (data store)  │  read  │ (web/desktop) │
                 └────────────┘        └──────┬───────┘  live   └───────────────┘
                                              │  ▲
                        reads milking data    ▼  │  writes milking_insights
                                        ┌───────────┐
                                        │   Agent   │  local LLM (Ollama)
                                        └───────────┘
```

## Components

- **[uploader/](uploader/)** — Python program that reads raw input files, normalizes them, and writes JSON records to the eVault. Three data sources today: milking control files (`milking_controle_data`), feed distribution per milking (`feed_distribution_data`) and daily production snapshots (`milking_production_data`). Values stay **raw**; readers interpret at display time. Extensible: each kind of input is a `DataSource`.
- **[dashboard/](dashboard/)** — SvelteKit web dashboard, made to run on a Raspberry Pi and be viewed from any browser (phone, tablet, laptop). All statistics are computed server-side — including the cross-dataset joins (feed × milk efficiency, leftover-feed signals, milking speed vs production); the browser only draws them.
- **[agent/](agent/)** — AI post-platform. Reads the milking, feed and production data, works out what stands out **in Python** — problem cows *and* good news (recoveries, risers), including cows flagged by several analyses at once — and has a local language model (Ollama) put it into words. Writes the result back as `milking_insights`, which the dashboard reads. The model never sees raw records and never computes numbers — so every insight keeps the figures it was based on.
- **[agent_chatbot/](agent_chatbot/)** — AI post-platform: ask your eVault anything. An interactive chat where a local tool-calling model (Ollama, qwen3) translates a free-form farmer question into calls against a fixed set of Python computations over the raw collections, then words the result. Schema-driven: it learns what exists in the vault from `VAULT_SCHEMA.json`, so new collections are queryable without code changes. Runs in the terminal (`run.py`) or in the browser (`serve.py` plus a SvelteKit frontend), which streams each computation to the screen as it fires.
- **[core/](core/)** — shared building blocks for the Python programs; today the eVault transport (rate limiting, retries, pagination) and the local record cache, written and verified once instead of duplicated.
- **[data/](data/)** — folder where the raw milking control files (FULLSENSE format) go. Private and gitignored; only a placeholder README is committed.

Each program is self-contained and runs wherever you want: the uploader on the farm PC, the dashboard on a Pi, the agent on whatever machine has the GPU. **They share nothing but the eVault** — there is no direct API between them. Adding a fourth program works the same way: read the collections you need, write your own, and nothing else has to change.

## eVault modes

Both programs support two vault backends, switched with `vault.mode` in their `config/settings.json`:

- `local` — a file-based stand-in vault (folder `evault_local/`) for development and testing without any credentials. This is the default.
- `evault` — the real MetaState eVault over GraphQL. Authentication is automatic: the program fetches a short-lived platform token from the Registry (`POST /platforms/certification`); there is no password or key file to manage.

Switching from local testing to a real eVault is only a config change (`vault.mode`, `registry_url`, `w3id`); no application code changes. See **Going live on the real eVault** below.

## Going live on the real eVault

The GraphQL clients (`uploader/app/vault_client.py`, `dashboard/src/lib/server/vault.js`) are verified against the live MetaState W3DS production API (registry/eVault schema introspected 2026-07). To switch a program from `local` to the real eVault, set in its `config/settings.json`:

```json
"vault": {
    "mode": "evault",
    "registry_url": "https://registry.w3ds.metastate.foundation",
    "w3id": "@your-farm-ename",
    "platform": "melkmonitor-uploader",
    "schema_ids": { "milking_controle_data": "milking_controle_data" }
}
```

Production services: Registry `https://registry.w3ds.metastate.foundation`, Ontology `https://ontology.w3ds.metastate.foundation`, Provisioner `https://provisioner.w3ds.metastate.foundation`.

Two things you must supply:

1. **`w3id`** — the farm's own eName, i.e. a provisioned eVault. Create it once with the eID Wallet (or the Provisioner's `POST /provision` flow). This is the eVault all programs read from and write to.
2. **`schema_ids`** — the ontology id per collection. A plain stable string (as above) works out of the box: store and fetch just have to agree on it. Registering the record as a JSON Schema in the Ontology service and using its W3ID here is only needed later, so that *other* W3DS platforms can interpret the data.

`platform` can be any name; the Registry issues a token for it with no pre-registration.

## Quick start (local test)

Two terminals, both from the repo root. Use the Anaconda Prompt on Windows.

First create your local settings from the templates (the real `settings.json` and `epassport.json` are gitignored):

```
copy uploader\config\settings.example.json uploader\config\settings.json
copy dashboard\config\settings.example.json dashboard\config\settings.json
```

```
# 1. Upload the example data to the local test vault (Python)
cd uploader
python run.py

# 2. Web dashboard (needs Node.js 18+)
cd dashboard
npm install
npm run dev
# open http://localhost:5173
```

The uploader fills `evault_local/`; the dashboard reads from it and updates live while the uploader keeps running with `python run.py --watch`.

## Build the uploader as standalone .exe

The uploader can be packaged as a Windows executable (no Python install needed on the farm PC). The `config/` folder stays next to the `.exe`, so `settings.json` and `epassport.json` remain editable without rebuilding.

From the repo root, in the Anaconda Prompt:

```
build.bat
```

This produces:

```
dist/
├── data/                 raw milk files (for local mode; place yours here)
├── evault_local/         local test vault (created on first upload)
└── uploader/
    ├── uploader.exe
    └── config/           settings.json + epassport.json
```

The executable reads its settings from the `config/` folder beside it; the default paths (`../data`, `../evault_local`) point one level up. Double-click `uploader.exe` or run it with `--watch` via Windows Task Scheduler. Switch to the real eVault by editing `mode`, `endpoint` and the ePassport file in `config/settings.json`.

The dashboard is deployed differently because it is a web app: it runs as a server (see [dashboard/README.md](dashboard/README.md)) on a Raspberry Pi or any machine, and the same codebase can later be packaged as a native desktop app with Tauri or a mobile app with Capacitor.

## What's in the vault — [VAULT_SCHEMA.json](VAULT_SCHEMA.json)

Every collection the eVault holds — its path pattern, field names, types, and how to query it — is documented in **[`VAULT_SCHEMA.json`](VAULT_SCHEMA.json)**. It's *generated*, not hand-written (`uploader/generate_vault_schema.py`, from each data source's declared `record_schema`), so unlike prose docs it can't silently drift from what the uploader actually writes. Read it before building a new dashboard view or agent that needs to combine fields — no guessing which collection has what.

Every record is versioned and keeps source values **raw** — interpretation (liters = `yield_raw / yield_divisor`, aggregates, insights) happens in the readers, never in the stored data. That's what keeps the vault a clean, stable source as more data sources and readers (dashboards, an AI layer) get added. Today's `milking_controle_data` shape, for a feel of it:

```json
{
    "schema_version": 1,
    "id": "5256_2025-10-16T16-45-14",
    "animal_number": 5256,
    "registration_number": "NL 660752569",
    "timestamp": "2025-10-16T16:45:14",
    "status": "OK",
    "yield_raw": 13430,
    "source": "milking_robot"
}
```

## Notes

- Records whose `animalNumber` is not exactly 4 digits are ignored by the uploader.
- After this raw-data change, rebuild the local test vault once: delete `evault_local/` and run the uploader again.
- The raw files in `data/` and the local vault in `evault_local/` are gitignored — they hold private farm data and never reach GitHub.
