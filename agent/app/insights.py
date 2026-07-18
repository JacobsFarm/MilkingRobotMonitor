"""The `milking_insights` record: what the agent writes back into the eVault.

Declared the same way a DataSource declares its records in the uploader, so the
repo-root VAULT_SCHEMA.json generator can document this collection too and
readers never have to guess these field names.

Design rule: `evidence` holds the numbers computed in analysis.py, `title` and
`body` hold the model's wording. An insight is therefore always checkable --
you can see exactly which figures led to the conclusion, and which model
phrased it.
"""

import hashlib

SCHEMA_VERSION = 2  # v2: added "period" (which measurement dates the insight covers)
SOURCE = "ai_agent"
COLLECTION = "milking_insights"
PATH_PATTERN = "{collection}/{type}/{id}"

RECORD_SCHEMA = {
    "schema_version": {
        "type": "integer",
        "description": "Bumped when this record's shape changes.",
        "example": SCHEMA_VERSION,
    },
    "id": {
        "type": "string",
        "description": (
            "Unique within the collection, and deterministic for a given "
            "analysis date + analysed dataset + finding + subject. Re-running "
            "on unchanged data therefore stores nothing (the eVault has no "
            "overwrite-on-id), while re-running after new data was uploaded "
            "produces a fresh batch."
        ),
        "format": "insight_{analysis_date}_{dataset_key}_{kind}_{subject}",
        "example": "insight_2026-07-18_a3f9c1_cow_yield_drop_5337",
    },
    "created_at": {
        "type": "string",
        "description": "When the agent produced this insight (ISO 8601).",
        "example": "2026-07-17T03:00:00",
    },
    "type": {
        "type": "string",
        "description": "Which analysis produced this insight.",
        "enum": {
            "herd_yield_change": "herd-level yield moved vs the baseline window",
            "herd_failure_rate": "share of milkings not finishing normally is high",
            "cow_yield_drop": "one cow produces clearly less than her own baseline",
            "cow_yield_rise": "one cow produces clearly more than her own baseline",
            "cow_interval_rise": "one cow visits the robot noticeably less often",
            "cow_feed_left": "one cow repeatedly leaves feed uneaten (early illness signal)",
            "herd_feed_efficiency_change": "liters of milk per kg of feed moved vs baseline",
            "cow_speed_drop": "one cow's milking speed dropped between production reports",
        },
        "example": "cow_yield_drop",
    },
    "severity": {
        "type": "string",
        "description": "How far the measurement deviates.",
        "enum": {"high": "large deviation", "medium": "worth watching"},
        "example": "high",
    },
    "scope": {
        "type": "object",
        "description": (
            "What the insight is about: {'animal_number': 5337} for one cow, "
            "{'herd': true} for the whole herd. Use animal_number to join back "
            "to milking_controle_data."
        ),
        "example": {"animal_number": 5337},
    },
    "period": {
        "type": "object",
        "description": (
            "The measurement dates this insight is based on. The recent window "
            "runs data_from -> data_until, compared against the baseline window "
            "baseline_from -> data_from. Anchored on the newest record in the "
            "vault, NOT on the analysis date -- if data_until is well before "
            "created_at, the underlying data is running behind."
        ),
        "example": {
            "data_from": "2026-07-11",
            "data_until": "2026-07-18",
            "baseline_from": "2026-06-13",
        },
    },
    "title": {
        "type": "string",
        "description": "One-line summary, written by the model.",
        "example": "Cow 5337 is producing 18% below her own average",
    },
    "body": {
        "type": "string",
        "description": "Explanation and suggested action, written by the model.",
        "example": "Her daily yield fell from 34.8 to 28.5 L/day over the past week...",
    },
    "evidence": {
        "type": "object",
        "description": (
            "The exact figures this insight is based on, computed in Python "
            "(never by the model). Makes every insight auditable."
        ),
        "example": {"recent_liters_per_day": 28.5, "baseline_liters_per_day": 34.8},
    },
    "model": {
        "type": "string",
        "description": "Which model wrote title/body, e.g. 'ollama:gemma3'.",
        "example": "ollama:gemma3",
    },
    "source": {
        "type": "string",
        "description": "Constant identifying the writing platform.",
        "example": SOURCE,
    },
}


def _subject_of(scope):
    if "animal_number" in scope:
        return str(scope["animal_number"])
    return "herd"


def dataset_key(*parts):
    """Short tag identifying the data an analysis ran on (all collections).

    Part of every insight id, so that the same data always yields the same ids
    (a repeated run is a harmless no-op) while newly uploaded data -- in any of
    the analysed collections -- yields a genuinely new batch.
    """
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:6]


def build_insight_record(
    finding, title, body, model, analysis_date, created_at, period, data_key
):
    """Combine a code-computed finding with the model's wording."""
    scope = finding["scope"]
    kind = finding["kind"]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": f"insight_{analysis_date}_{data_key}_{kind}_{_subject_of(scope)}",
        "created_at": created_at,
        "type": kind,
        "severity": finding["severity"],
        "scope": scope,
        "period": period,
        "title": title,
        "body": body,
        "evidence": finding["metrics"],
        "model": model,
        "source": SOURCE,
    }


def record_path(record):
    return PATH_PATTERN.format(collection=COLLECTION, type=record["type"], id=record["id"])
