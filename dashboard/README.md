# Dashboard

SvelteKit web dashboard (the "reader"). Serves the milk monitor as a web page: run it on a Raspberry Pi (or any machine) and open it in a browser on your phone, tablet or laptop. It never talks to the uploader or the agent directly — the eVault is the only shared channel. What it reads is documented in [`VAULT_SCHEMA.json`](../VAULT_SCHEMA.json) at the repo root.

## Architecture: the server computes, the browser draws

All statistics live in `src/lib/server/aggregate.js` and are computed **server-side**. The browser polls `/api/stats` with its filters as query parameters and receives a few KB of ready-made aggregates — never the raw records (tens of thousands). A signature covers dataset + filters: when the browser sends its previous signature back and nothing changed, the server replies `unchanged` without a payload.

The server also joins the datasets — that is deliberate: combining collections is computation, so it belongs on the server, and every reader gets the same joined numbers.

## What it shows

**From `milking_controle_data`** (per milking): heatmaps per hour × weekday, hourly/weekday production, daily and weekly trends, time-between-milkings distribution and per-cow ranking, status distribution, recent milkings table.

**From `feed_distribution_data` × milkings** (joined on day, same filters):
- feed given (kg) vs milk produced (L) per day,
- feed efficiency (liters of milk per kg of feed) and leftover-feed % per day,
- per-cow "feed left uneaten" ranking — often one of the first visible illness signals.

**From `milking_production_data`** (latest report): milking speed vs daily production scatter, and the lactation curve (days in lactation vs production). Milking speed comes from the robot, which is the authoritative source for it; lactation data here is the robot's own registration until CRV (`mpr_uitslag`) is uploaded — see `field_authority` in `VAULT_SCHEMA.json`.

**From `milking_insights`** (written by the agent): the AI findings panel on top — severity, the model's wording, the exact figures it was based on, and the measurement period. Cow-scoped findings link straight to that cow's filtered dashboard.

All charts respond to the shared filters (cows, months, weeks, date range) — the feed and production figures always describe the same cows and period as the milking charts next to them.

## eVault protection

The real eVault pages at 100 records and rate-limits hard, so the server keeps an in-memory cache per collection, fills it progressively in the background (the UI shows loading progress), and re-checks with a single `totalCount` request instead of re-reading everything — a full re-page only happens when the count actually changed.

## Folder layout

```
dashboard/
├── package.json
├── svelte.config.js
├── vite.config.js
├── config/
│   └── settings.example.json   Template (copy to settings.json)
└── src/
    ├── app.html
    ├── lib/
    │   ├── format.js           Pure presentation helpers (labels, number format)
    │   ├── components/         ChartBox, Heatmap, MultiSelect
    │   └── server/
    │       ├── settings.js     Loads config/settings.json
    │       ├── vault.js        eVault transport + progressive cache
    │       └── aggregate.js    ALL computation: filters, stats, dataset joins
    └── routes/
        ├── +page.svelte        Presentation only (charts, filters, panels)
        └── api/
            ├── stats/+server.js     Aggregates (signature-cached)
            ├── insights/+server.js  Latest AI findings batch
            └── records/+server.js   Legacy raw-records endpoint
```

## Usage (development)

Requires Node.js 18+. From inside the `dashboard/` folder:

```
copy config\settings.example.json config\settings.json
npm install
npm run dev
```

Open http://localhost:5173. On the real eVault the first load pages the full history in the background — the charts fill progressively and a banner shows progress.

## Deployment on a Raspberry Pi

```
npm install
npm run build
node build/index.js
```

Serve it permanently with a systemd service or `pm2`. Run the command from inside the `dashboard/` folder so `config/settings.json` is found. The site is then reachable on the Pi's address, port 3000 (set `PORT=80` or put a reverse proxy in front to change that).

## Settings (`config/settings.json`)

- `base_path` / `feed_path` / `production_path` / `insights_path` — the vault collections to read.
- `yield_divisor` — raw yield units per liter (display conversion only, default 1000).
- `feed_divisor` — raw feed units per kg (default 1000).
- `refresh_ms` — how often the browser checks for changes (signature check; aggregates are only re-sent when something changed).
- `vault.mode` — `local` (file-based test vault) or `evault` (MetaState W3DS eVault over GraphQL).
- `vault.local_path` — the folder the uploader writes to in local mode (relative to this folder).
- `vault.registry_url` — base URL of the W3DS Registry (evault mode): resolves the eVault endpoint (`GET /resolve?w3id=...`) and issues the platform token (`POST /platforms/certification`).
- `vault.w3id` — the w3id (eName) whose eVault is read; sent as `X-ENAME` header on every GraphQL call.
- `vault.platform` — platform name used when requesting a certification token.
- `vault.schema_ids` — optional map of collection name → registered Ontology W3ID; without an entry the collection name itself is the ontology id.

## Desktop app (Tauri) — later step

The same codebase can be packaged as a native desktop app with [Tauri](https://tauri.app). That requires the Rust toolchain and switching to `@sveltejs/adapter-static` (the desktop app then talks to the eVault directly instead of through the Node server routes). Planned, not yet configured — the web version works standalone without it.
