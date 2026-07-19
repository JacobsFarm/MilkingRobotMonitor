# Agent

Independent AI post-platform (the "analyst"). It reads milking records from the eVault, works out what stands out, has a **local** language model put that into words, and writes the result back to the eVault as `milking_insights` — which the dashboard already reads.

It never talks to the uploader or the dashboard. Like every program here, the eVault is the only shared channel. It has its own platform identity (`melkmonitor-ai-agent`), so it can be started, stopped or replaced without touching anything else.

## The core rule: Python calculates, the model explains

Every number is produced in [`app/analysis.py`](app/analysis.py). The model **never sees the raw records** and never computes anything — it receives finished findings and writes the farmer-facing explanation.

That matters for three reasons:

- **Trust** — a language model cannot do arithmetic over tens of thousands of rows reliably. It would produce confident, wrong averages.
- **Auditability** — every stored insight keeps its `evidence` (the figures from Python) next to the `title`/`body` (the model's words) and the `model` that wrote them. You can always check a conclusion against its own numbers.
- **Scale** — 64k records don't fit in a context window; a few dozen findings do. This keeps working as the vault grows.

If the model is unreachable, the agent still stores the findings — with the plain machine-written summary instead of a written explanation. A missing model degrades the wording, never the detection.

## How the model is steered

Wording quality is decided in [`app/prompting.py`](app/prompting.py), not by making the prompt longer. Three things happen there:

- **Findings are grouped per cow.** `analysis.py` emits one finding per detection, so a single cow can appear three times. Sent flat, the model writes three unrelated notes and the farmer reads three small problems; sent grouped, it can write about one animal going downhill — which is what the data actually says.
- **Domain guidance is attached per finding type.** A finding says "yield down 18%"; `KIND_GUIDANCE` supplies the shortlist of causes worth checking. Only the types actually present are sent, so the prompt stays small.
- **The farm's own context is injected** from `farm_context` in settings, so the model stops reasoning about a generic average herd.

Requests are **batched** (default 12 findings, groups are never split). Asking one call to word forty findings degrades all forty, and a single malformed reply would cost the wording of the entire run instead of one batch.

### Context window

`llm.num_ctx` is sent explicitly on every request. This matters: Ollama's own default is small (4k on current builds) and it truncates an oversized prompt **without reporting it** — the model answers about the findings it still saw, the rest silently fall back to their machine summary, and nothing says why. The agent logs a warning when a prompt approaches `num_ctx`, so the failure is visible instead of silent.

## What it looks for

From `milking_controle_data`:

| Finding | Meaning |
|---|---|
| `herd_yield_change` | herd yield per day moved vs the baseline window |
| `herd_failure_rate` | share of milkings not finishing normally is high |
| `cow_yield_drop` / `cow_yield_rise` | a cow deviates from **her own** baseline (not the herd average) |
| `cow_interval_rise` | a cow visits the robot noticeably less often — often the first visible sign something is wrong |
| `cow_recovered` | **good news**: a cow dipped ≥15% below her own baseline and is back within 5% of it — closes the loop on an earlier drop ("the intervention worked", or "she sorted it out herself, keep half an eye on her") |

Cross-dataset, joined against the same windows:

| Finding | Data | Meaning |
|---|---|---|
| `cow_feed_left` | `feed_distribution_data` | a cow repeatedly leaves feed uneaten — an early illness signal |
| `herd_feed_efficiency_change` | feed × milkings | liters of milk per kg of feed moved vs the baseline (only over days where both were measured) |
| `cow_speed_drop` | `milking_production_data` | a cow's milking speed dropped clearly between the two most recent reports (speed is robot-authoritative, see `field_authority` in `VAULT_SCHEMA.json`) |

Each comparison uses a recent window (default 7 days) against a preceding baseline (default 28 days), anchored on the newest milking in the vault, and requires a minimum number of measurements before reporting — so one missed day can't look like a collapse.

Adding a new analysis = one more function returning findings in the same shape, appended in `build_findings()`.

### The finding that reads the other findings

| Finding | Meaning |
|---|---|
| `cow_multi_signal` | **two or more** of the concerning analyses above flagged the *same* cow in the same period |

This is the one a farmer is most likely to miss, and the reason it is computed separately. Every other analysis compares one quantity against one threshold, so a cow drifting downhill on several fronts shows up as two or three *unremarkable* entries — each just barely over its threshold, each scattered among dozens of others. Nothing in a per-quantity list ever says "these are the same animal".

The signals aren't independent in reality either: fewer robot visits, feed left uneaten and a slower milking are the textbook early course of lameness or mastitis, roughly in that order. Seeing them coincide is much stronger evidence than any one of them crossing its threshold.

It derives entirely from findings that already exist (`correlation_findings()` in `analysis.py`), so it obeys the same rule as everything else: the numbers come from the analyses above, this only reports which of them landed on the same cow. Its `evidence` carries the underlying figures per signal, so the insight stays auditable without joining the other records.

## Requirements

[Ollama](https://ollama.com) running locally:

```
ollama serve
ollama pull gemma3:12b
```

Any chat model works, because the agent never asks the model to call tools — only to interpret findings Python already calculated. Gemma is a good fit for that. (If you later build an interactive chat that lets the model query the vault itself, models trained for tool-calling such as Qwen 2.5 or Llama 3.1+ are the safer pick.)

Running a reasoning model such as `qwen3`: its thinking tokens are generated inside the same window and *before* the JSON, so with `format: json` it can spend the budget reasoning and return a truncated object. Use an instruct variant, disable thinking, or give it a generous `num_ctx`.

Apart from Ollama: standard library only, no `pip install`.

## Usage

First create your local settings from the template (the real `settings.json` is gitignored):

```
copy config\settings.example.json config\settings.json
```

Then, from inside the `agent/` folder:

```
python run.py                 # analyse and write insights to the vault
python run.py --dry-run       # print the findings, write nothing (start here)
python run.py --refresh       # re-read the vault instead of using the local cache
python run.py --watch         # keep running, re-analyse every interval_seconds
```

Start with `--dry-run`: it shows exactly which findings came out and the figures behind them, without touching the vault.

## The local cache

Reading a large collection from the real eVault is slow: the server pages 100 records at a time and rate-limits hard, so a full read takes minutes and competes with the uploader for the same limit. The agent therefore keeps a local copy in `cache/`.

It does **not** blindly trust that copy. On every run it asks the vault how many records the collection holds — one request, well under a second — and re-reads only when that differs from the cache. So a normal `python run.py` picks up newly uploaded milkings by itself; `--refresh` is only needed to force a re-read when you suspect the cache is corrupt.

Fetching *only* the new records is not possible against this API, and it is worth knowing why: the envelope filter has no date field, and results are ordered by each envelope's content-derived UUID, so newly stored records scatter throughout the ordering instead of landing at the end. Verified against production: after an upload, 11 of the first 100 records in vault order were new. Resuming from a stored cursor would therefore silently skip records — comparing counts is the safe alternative.

## Re-running on the same day

Insight ids include both the analysis date and a short key for the analysed dataset, so:

- re-running on **unchanged** data stores nothing (the eVault has no overwrite-on-id, so this is what stops `--watch` from filling the vault with duplicates);
- re-running after **new data** was uploaded produces a genuinely new batch, and the dashboard shows the newest one.

## Folder layout

```
agent/
├── run.py                  Entry point
├── config/
│   └── settings.json       Windows, model, vault (gitignored; use the .example)
├── cache/                  Local copy of vault collections (gitignored)
└── app/
    ├── config.py            Loads settings, vault fingerprint for the cache
    ├── cache.py             Local record cache (see above)
    ├── analysis.py          ALL the arithmetic — findings with hard numbers
    ├── prompting.py         Grouping, farm context and domain guidance -> prompts
    ├── insights.py          The milking_insights record shape + schema
    ├── analyst.py           Orchestrates: read -> analyse -> explain -> store
    └── llm/
        ├── base.py          LLMClient contract
        └── ollama.py        Local Ollama backend
```

`core/vault_client.py` (repo root) provides the eVault transport, shared with the uploader so the rate-limiting, retry and pagination logic exists once.

## Settings (`config/settings.json`)

- `source_collection` / `feed_collection` / `production_collection` — the collections the analysis reads (each behind its own local cache).
- `insights_collection` — where findings are written.
- `recent_window_days` / `baseline_window_days` — the comparison windows (default 7 vs 28).
- `yield_divisor` — raw yield units per liter, must match the dashboard (default 1000).
- `feed_divisor` — raw feed units per kg (default 1000).
- `interval_seconds` — how often `--watch` re-analyses (default 6 hours).
- `llm.provider` — `ollama` today. Add a hosted backend by registering it in `app/llm/__init__.py`; nothing else changes.
- `llm.model` — e.g. `gemma3:12b`. Must be a model you have pulled.
- `llm.temperature` — kept low (0.2): this is analysis, not creative writing.
- `llm.num_ctx` — context window (default 16384). Raise it for a large herd; lower it if the model doesn't fit in VRAM — but then lower `max_findings_per_request` too.
- `llm.max_findings_per_request` — findings per call (default 12). Groups are never split, so this is a target, not a hard cap.
- `llm.system_prompt` — overrides the default instructions. Leave `null` to use the built-in one; set it to change tone or output language without editing code.
- `llm.kind_guidance` — `{"cow_yield_drop": "..."}` to override or extend the built-in domain guidance per finding type, e.g. with something specific to your own herd.
- `farm_context` — herd size, breed, housing, typical yield, free-form `notes`. Sent to the model as context. Unknown keys are passed through, so you can add anything you think it should know.
- `vault.*` — same shape as the other programs. `platform` is this agent's own identity.

`farm_context` and the `llm.*` additions are all optional — the agent runs with the defaults if your `settings.json` predates them. Copy the blocks from `settings.example.json` to use them.

## Adding a hosted model later

`app/llm/base.py` defines the contract; `ollama.py` implements it. A Claude or OpenAI backend is one more subclass plus an entry in `LLM_TYPES`, then a config switch — the analysis and storage code is unaware of which model it talks to. That lets you run everything locally by default and reach for a stronger hosted model only for the hard questions.
