# Chatbot

Independent AI post-platform: **ask your eVault anything**. An interactive chat where a local tool-calling model translates a free-form farmer question — *"hoe zijn de koeien tussen 60 en 100 lactatiedagen de laatste 3 maanden gegroeid of gedaald?"* — into calls against a fixed set of Python computations over the raw collections, and words the result.

Like every program here it shares nothing with the others but the eVault, and has its own platform identity (`melkmonitor-chatbot`). It complements the [agent](../agent/): the agent runs unattended and pushes findings (`milking_insights`), the chatbot answers whatever you pull.

## The core rule, chatbot edition: the model composes, Python computes

The vault holds 70k+ milkings — they fit in no context window, and a language model summing even a hundred rows produces confident, wrong numbers. So the model **never receives raw records to add up**. It receives a tool catalogue; every figure in an answer comes out of [`app/tools.py`](app/tools.py), and each tool call is printed as it runs, so you can see which computation produced which number:

```
vraag> welke koeien zijn het hardst gedaald deze maand?
  [compare_windows(metric=yield, direction=down, a_from=..., b_from=...)]
```

## Schema-driven: it knows what is in the vault by itself

The chatbot builds its entire view of the vault from [`VAULT_SCHEMA.json`](../VAULT_SCHEMA.json) (the generated contract at the repo root): which collections exist, which fields they hold, what they mean. The `describe_vault` tool serves exactly that to the model.

That makes new data sources cheap: when the uploader gains a source and the schema is regenerated, the new collection is **immediately** queryable through the generic `query_records` tool — filter, group, aggregate — without touching chatbot code. A specialized tool (or a unit conversion in `DERIVERS`) is only worth adding when a question type becomes common.

## The tools

| Tool | Answers |
|---|---|
| `describe_vault` | "what data is there?" — collections, fields, meanings, counts, date ranges |
| `query_records` | anything generic: filter/group/aggregate over **any** active collection, incl. future ones |
| `lactation_cohort` | lactation-stage questions: cows in a DIM window during a period, each with the dates she was inside it, with per-cow and group yield trends |
| `daily_yield` | production per day: herd mean/trend, per cow, day- or week series |
| `compare_windows` | "who fell / who improved between period A and B" on yield, visits, intervals, feed intake or feed refusals |
| `cow_profile` | everything about one cow, across every collection |
| `list_insights` | what the analysis agent already flagged — "is anything wrong?" starts here |

Tool errors (wrong field name, bad date) go back to the model **as data**, so it corrects itself instead of the chat crashing.

### Days in milk (DIM) — one pitfall worth knowing

Lactation questions need a calving date per cow, derived from the robot's production reports (`report_date − lactation_days`). Verified against this vault: the robot's DIM counter drifts (it advanced 12 days over a 13-day calendar gap for 41 of 49 cows), so estimates from different reports disagree. The `LactationModel` therefore anchors every cow on her **newest** report and reports ±2 days uncertainty — and every lactation answer carries that caveat, plus the fact that only cows present in a production report have a DIM at all. When CRV data (`mpr_uitslag`) is uploaded it becomes the leading source for lactation days (see `field_authority` in the schema), which shrinks that uncertainty.

## Requirements

[Ollama](https://ollama.com) with a **tool-calling** model — this is where the chatbot differs from the agent, which only needs a chat model:

```
ollama serve
ollama pull qwen3:8b
```

Apart from Ollama: standard library only, no `pip install`.

## Usage

```
copy config\settings.example.json config\settings.json    (fill in vault.w3id)

python run.py                      # interactive chat
python run.py --ask "..."          # one question, one answer, exit
python run.py --refresh            # re-read the vault instead of the local cache
```

Questions can be asked in any language; the model answers in the language of the question.

## The web interface

The terminal REPL and the browser drive the **same** `ChatSession`; `serve.py` only moves the conversation from stdin to a socket. Nothing about the core rule changes — the model composes, `tools.py` computes.

```
python serve.py                    # http://localhost:8420
python serve.py --host 0.0.0.0     # reachable from the tablet in the barn
python serve.py --refresh          # re-read the vault first
```

Development needs two terminals, because Vite serves the frontend and proxies `/api` to Python:

```
python serve.py                    # terminal 1
cd web && npm install && npm run dev   # terminal 2 -> http://localhost:5174
```

For production build the frontend once; `serve.py` then serves it itself, so there is one process and one port:

```
cd web && npm run build
python serve.py                    # open http://localhost:8420
```

### What the browser adds over the terminal

The REPL prints `[compare_windows(metric=yield, ...)]` as each computation runs. That transparency is the product, so it survives: `/api/ask` is a **server-sent event stream**, and every tool call is pushed to the browser the moment it fires. The answer shows the computations that produced it, collapsed but one click away.

Two deliberate choices worth knowing:

- **No CORS headers.** This server hands out the farm's data to anything that can reach it, so it stays same-origin — the Vite proxy in development, the server's own static files in production. Point `--host 0.0.0.0` at a trusted farm network only; there is no authentication.
- **One request at a time per conversation.** A `ChatSession` owns a message history, so overlapping questions would interleave into it. A per-session lock serializes them; separate browser tabs get separate sessions and answer in parallel over the shared, read-only `DataStore`.

Design: the frontend follows the [CowCatcher AI](https://jacobsfarm.github.io/website/) house style — barn green (`#386938`), gold accent (`#bf8100`), ink footer (`#151d15`), Bebas for headings and Roboto for text. Every token lives in `web/src/lib/theme.css`, so re-skinning is one file.

## Folder layout

```
agent_chatbot/
├── run.py                  Entry point (REPL / --ask)
├── serve.py                Entry point (web)
├── config/
│   └── settings.json       Model, vault, farm context (gitignored; use the .example)
├── cache/                  Local copy of vault collections (gitignored)
├── app/
│   ├── config.py            Loads settings + VAULT_SCHEMA.json
│   ├── datastore.py         Schema-driven loading, derived fields, LactationModel
│   ├── tools.py             ALL the arithmetic — the tool catalogue
│   ├── chat.py              Ollama tool-calling loop + system prompt
│   └── server.py            HTTP + SSE around ChatSession; serves the build
└── web/                    SvelteKit frontend (static build, no server half)
    └── src/
        ├── app.html
        ├── lib/
        │   ├── theme.css        CowCatcher design tokens — the only place colours live
        │   ├── api.js           /api client; parses the SSE answer stream
        │   ├── tools.js         Human-readable labels for the tool catalogue
        │   └── components/      Message, ToolTrace, Composer
        └── routes/
            ├── +layout.svelte   Green nav, ink footer
            └── +page.svelte     The conversation
```

Shared with the other programs via the repo root: `core/vault_client.py` (eVault transport) and `core/record_cache.py` (local collection cache — reading the full vault takes minutes, a count-check takes under a second).

## Settings (`config/settings.json`)

- `llm.model` — must support tool calling: `qwen3:8b` (default), a larger qwen3, or llama3.1+. Gemma does **not** reliably call tools.
- `llm.num_ctx` — context window (default 16384). Tool results land in the conversation, so multi-step questions need room.
- `llm.max_tool_rounds` — bound on tool rounds per question (default 8), so a confused model cannot loop forever.
- `llm.system_prompt` — overrides the built-in instructions (`null` = default).
- `farm_context` — herd size, breed, housing, typical yield, free-form notes; the model uses it as context when interpreting questions.
- `yield_divisor` / `feed_divisor` — raw units per liter / kg, must match the dashboard.
- `vault.*` — same shape as the other programs; `platform` is this chatbot's own identity.
