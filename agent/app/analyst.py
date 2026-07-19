"""The agent: read -> analyse in Python -> have the model explain -> write back.

This is a post-platform in its own right. It has its own platform identity, it
never talks to the uploader or the dashboard, and it shares nothing with them
but the eVault: it reads `milking_controle_data` and writes `milking_insights`,
which the dashboard already reads.
"""

import argparse
import json
import logging
import time
from datetime import datetime

from app.analysis import build_findings
from app.cache import RecordCache, load_records
from app.config import CACHE_DIRECTORY, load_settings, vault_fingerprint
from app.insights import build_insight_record, dataset_key, record_path
from app.llm import LLMError, create_llm_client
from app.prompting import (
    batch_groups,
    build_system_prompt,
    build_user_prompt,
    group_findings,
    kinds_in,
)
from core.vault_client import create_vault_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent")

# How many findings to put in one request. Findings are grouped per cow first
# and a group is never split, so this is a target rather than a hard cap.
DEFAULT_MAX_FINDINGS_PER_REQUEST = 12


def parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def explain(llm, bundle, settings):
    """Ask the model to word each finding, in grouped batches.

    Falls back to the machine-written summary wherever the model is unreachable
    or replies with something unusable -- an insight with plain wording still
    beats losing the finding. Batching keeps that fallback granular: one bad
    reply costs the wording of one batch, not of the whole run.
    """
    findings = bundle["findings"]
    groups = group_findings(findings)
    batches = batch_groups(
        groups,
        settings.get("llm", {}).get(
            "max_findings_per_request", DEFAULT_MAX_FINDINGS_PER_REQUEST
        ),
    )

    worded = {}
    for number, batch in enumerate(batches, start=1):
        system_prompt = build_system_prompt(settings, kinds_in(batch))
        user_prompt = build_user_prompt(bundle["context"], batch)
        if len(batches) > 1:
            logger.info("Wording batch %d of %d (%d subjects)", number, len(batches), len(batch))
        try:
            reply = llm.complete_json(system_prompt, user_prompt)
            entries = reply.get("insights") or []
        except LLMError as error:
            logger.warning(
                "Model unavailable for batch %d (%s); those findings are stored "
                "unworded.",
                number,
                error,
            )
            continue

        for entry in entries:
            try:
                ref = int(entry["ref"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= ref < len(findings):
                title = str(entry.get("title") or "").strip()
                body = str(entry.get("body") or "").strip()
                if title or body:
                    worded[ref] = (title or findings[ref]["summary"], body)

    missing = len(findings) - len(worded)
    if missing:
        logger.warning(
            "%d of %d findings came back unworded; they keep their calculated "
            "summary.",
            missing,
            len(findings),
        )
    return worded


def gather_data(settings, vault, refresh):
    """Load every collection the analysis uses (each behind its own cache)."""
    fingerprint = vault_fingerprint(settings["vault"])
    loaded = {}
    for key, default in (
        ("source_collection", "milking_controle_data"),
        ("feed_collection", "feed_distribution_data"),
        ("production_collection", "milking_production_data"),
    ):
        collection = settings.get(key, default)
        cache = RecordCache(CACHE_DIRECTORY / f"{collection}.json", fingerprint)
        loaded[key] = load_records(vault, collection, cache, refresh, logger)
    return loaded


def build_bundle(settings, data):
    return build_findings(
        data["source_collection"],
        divisor=settings.get("yield_divisor", 1000),
        parse_timestamp=parse_timestamp,
        recent_days=settings.get("recent_window_days", 7),
        baseline_days=settings.get("baseline_window_days", 28),
        feed_records=data["feed_collection"],
        production_records=data["production_collection"],
        feed_divisor=settings.get("feed_divisor", 1000),
    )


def run_once(settings, vault, llm, refresh=False):
    data = gather_data(settings, vault, refresh)
    bundle = build_bundle(settings, data)
    logger.info(
        "Analysed %d records; %d findings",
        bundle["context"]["records_analysed"],
        len(bundle["findings"]),
    )
    if not bundle["findings"]:
        logger.info("Nothing stands out -- no insights written.")
        return

    worded = explain(llm, bundle, settings)
    now = datetime.now()
    analysis_date = now.strftime("%Y-%m-%d")
    created_at = now.isoformat(timespec="seconds")

    period = bundle["context"].get("window")
    data_key = dataset_key(
        bundle["context"]["records_analysed"],
        bundle["context"]["latest_record"],
        bundle["context"]["feed_records_analysed"],
        bundle["context"]["production_records_analysed"],
    )
    records_to_store = []
    for index, finding in enumerate(bundle["findings"]):
        title, body = worded.get(index, (finding["summary"], ""))
        records_to_store.append(
            build_insight_record(
                finding, title, body, llm.name(), analysis_date, created_at, period, data_key
            )
        )

    # The eVault has no overwrite-on-id, so skip insights already stored for
    # this analysis date (ids are deterministic -- see app/insights.py).
    insights_collection = settings.get("insights_collection", "milking_insights")
    existing_ids = {r.get("id") for r in vault.fetch_all(insights_collection)}
    new_records = [r for r in records_to_store if r["id"] not in existing_ids]

    if not new_records:
        logger.info(
            "These %d findings were already stored for this data (dataset %s) -- "
            "nothing new to write. Upload new milkings, or wait for tomorrow's run.",
            len(records_to_store),
            data_key,
        )
        return

    vault.store_many((record_path(record), record) for record in new_records)
    logger.info(
        "Stored %d new insights in '%s' (dataset %s, %d already present)",
        len(new_records),
        insights_collection,
        data_key,
        len(records_to_store) - len(new_records),
    )
    for record in new_records:
        logger.info("  [%s] %s", record["severity"], record["title"])


def main():
    arguments = argparse.ArgumentParser(description="Melkmonitor AI analysis agent")
    arguments.add_argument("--watch", action="store_true", help="keep running periodically")
    arguments.add_argument(
        "--refresh", action="store_true", help="re-read the vault instead of using the local cache"
    )
    arguments.add_argument(
        "--dry-run", action="store_true", help="analyse and print, but write nothing to the vault"
    )
    options = arguments.parse_args()

    settings = load_settings()
    vault = create_vault_client(settings["vault"])
    llm = create_llm_client(settings.get("llm", {}))

    if not llm.available():
        logger.warning(
            "%s is not reachable -- findings will still be stored, but without "
            "written explanations. Start it with `ollama serve`.",
            llm.name(),
        )

    if options.dry_run:
        data = gather_data(settings, vault, options.refresh)
        bundle = build_bundle(settings, data)
        print(json.dumps(bundle, indent=2, default=str))
        return

    run_once(settings, vault, llm, refresh=options.refresh)
    while options.watch:
        time.sleep(settings.get("interval_seconds", 21600))  # default: 4x per day
        run_once(settings, vault, llm, refresh=True)
