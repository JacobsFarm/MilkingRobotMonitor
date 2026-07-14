# Melkmonitor

A modular system for managing milking control data, using a MetaState eVault as the central, decentralized data store. It consists of fully independent programs that communicate only through the eVault — there is no direct API between them.

```
                 ┌────────────┐        ┌──────────────┐        ┌───────────────┐
   raw files ───▶│  Uploader  │ ─────▶ │    eVault     │ ─────▶ │  Dashboards   │
   (data/)       │  (writer)  │  store │ (data store)  │  read  │ (web/desktop) │
                 └────────────┘        └──────┬───────┘  live   └───────────────┘
                                              │
                                              ▼  reads raw data, writes insights back
                                        ┌───────────┐
                                        │  AI layer │  (planned)
                                        └───────────┘
```

## Components

- **[uploader/](uploader/)** — Python program that reads raw milking control files, cleans them, and writes JSON records to the eVault path `milking_controle_data/[animalNumber]/[unique_id]`. The yield stays **raw** (`yield_raw`) so the stored data remains machine-readable for the AI layer; the dashboard converts to liters at display time.
- **[dashboard/](dashboard/)** — SvelteKit web dashboard, made to run on a Raspberry Pi and be viewed from any browser (phone, tablet, laptop). Prepared for the `milking_insights` AI path, and can later be packaged as a native desktop/mobile app (Tauri/Capacitor) from the same codebase.
- **[data/](data/)** — folder where the raw milking control files (FULLSENSE format) go. The files themselves are private and gitignored; only a placeholder README is committed.

Each program is self-contained: the uploader runs on the farm PC, a dashboard runs wherever you want to look. They share nothing but the eVault. A future AI layer joins the same way: it subscribes to `milking_controle_data`, computes insights (anomaly detection, yield prediction), and writes them back to the vault under `milking_insights` — no changes to the other programs needed.

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

## Data format (machine-readable, AI-ready)

Every record in the vault is versioned and keeps the source values raw:

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

Interpretation (like liters = `yield_raw / 1000`) happens in the readers, never in the stored data. This keeps the vault a clean training and inference source for the AI layer, and `schema_version` + `source` make it safe to add more data sources later.

## Notes

- Records whose `animalNumber` is not exactly 4 digits are ignored by the uploader.
- After this raw-data change, rebuild the local test vault once: delete `evault_local/` and run the uploader again.
- The raw files in `data/` and the local vault in `evault_local/` are gitignored — they hold private farm data and never reach GitHub.
