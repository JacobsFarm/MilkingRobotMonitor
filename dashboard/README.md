# Dashboard

SvelteKit web dashboard (the "reader"). Serves the milk monitor as a web page: run it on a Raspberry Pi (or any machine) and open it in a browser on your phone, tablet or laptop. It never talks to the uploader directly — the eVault is the only shared channel.

## Behavior

- Loads the full history from the vault path `milking_controle_data` and polls for new records while open.
- Converts the raw yield value to liters **at display time** (`yield_raw / yield_divisor`) — the vault keeps the raw, machine-readable value for the future AI layer.
- Line chart of liters per milking (Chart.js), animal selector, colored status indicator (green `OK`, orange `!`, red `#`) and a color-coded record table.
- `/api/insights` endpoint is prepared for the future AI layer: it reads the `milking_insights` vault path (empty until an AI writer exists).

## Folder layout

```
dashboard/
├── package.json
├── svelte.config.js
├── vite.config.js
├── config/
│   ├── settings.example.json   Template (copy to settings.json)
│   └── epassport.example.json
└── src/
    ├── app.html
    ├── lib/server/
    │   ├── settings.js         Loads config/settings.json
    │   └── vault.js            Vault backends (local + MetaState eVault)
    └── routes/
        ├── +page.svelte        Dashboard UI
        └── api/
            ├── records/+server.js
            └── insights/+server.js
```

## Usage (development)

Requires Node.js 18+. From inside the `dashboard/` folder:

```
copy config\settings.example.json config\settings.json
npm install
npm run dev
```

Open http://localhost:5173. The default settings read the local test vault (`../evault_local`) that the uploader fills.

## Deployment on a Raspberry Pi

```
npm install
npm run build
node build/index.js
```

Serve it permanently with a systemd service or `pm2`. Run the command from inside the `dashboard/` folder so `config/settings.json` is found. The site is then reachable on the Pi's address, port 3000 (set `PORT=80` or put a reverse proxy in front to change that).

## Settings (`config/settings.json`)

- `vault.mode` — `local` (file-based test vault) or `evault` (MetaState eVault over GraphQL).
- `vault.local_path` — the folder the uploader writes to in local mode (relative to this folder).
- `vault.endpoint` / `vault.epassport_path` — eVault GraphQL endpoint and ePassport credential for `evault` mode.
- `yield_divisor` — raw yield units per liter (display conversion only).
- `refresh_ms` — how often the browser polls for new records.

## Desktop app (Tauri) — later step

The same codebase can be packaged as a native desktop app with [Tauri](https://tauri.app). That requires the Rust toolchain and switching to `@sveltejs/adapter-static` (the desktop app then talks to the eVault directly instead of through the Node server routes). Planned, not yet configured — the web version works standalone without it.
