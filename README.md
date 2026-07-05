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
- **[data/](data/)** — example raw milking control files (FULLSENSE format) used for local testing.

Each program is self-contained: the uploader runs on the farm PC, a dashboard runs wherever you want to look. They share nothing but the eVault. A future AI layer joins the same way: it subscribes to `milking_controle_data`, computes insights (anomaly detection, yield prediction), and writes them back to the vault under `milking_insights` — no changes to the other programs needed.

## eVault modes

Both programs support two vault backends, switched with `vault.mode` in their `config/settings.json`:

- `local` — a file-based stand-in vault (folder `evault_local/`) for development and testing without any credentials. This is the default.
- `evault` — the real MetaState eVault over GraphQL, using the farm ePassport for authentication.

Switching from local testing to a real eVault is only a config change (`mode`, `endpoint`, and the ePassport file); no application code changes.

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
- The `data/` folder contains real registration numbers as example data; remove or replace it before publishing if that is a concern.
- The GraphQL calls in the vault clients (`uploader/app/vault_client.py` and `dashboard/src/lib/server/vault.js`) are written conceptually against the MetaState eVault core API and should be verified against your deployed eVault version.
