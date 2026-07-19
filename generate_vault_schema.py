"""Generates VAULT_SCHEMA.json: a machine- and human-readable map of every
eVault collection this project uses -- the vault path pattern, which fields
each record contains, and how to query it.

This is the shared contract between every platform: the uploader (writes
milking data), the agent (writes insights), the dashboard and any future AI
agent (read). Nobody has to guess a field name or reverse-engineer another
program's source to know what is in the vault.

Regenerate it whenever a source's record_schema changes, or a new collection /
platform is added:

    python generate_vault_schema.py

It reads each program's settings.example.json -- never the real settings.json --
so the output never depends on, or leaks, a real w3id or registry URL, and is
identical no matter which machine generates it.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "uploader"))

from app.config import load_settings  # uploader's settings loader
from app.sources import create_source  # uploader's data sources
from agent.app import insights as agent_insights

UPLOADER_EXAMPLE = REPO_ROOT / "uploader" / "config" / "settings.example.json"
AGENT_EXAMPLE = REPO_ROOT / "agent" / "config" / "settings.example.json"
OUTPUT_PATH = REPO_ROOT / "VAULT_SCHEMA.json"

# Which programs read a collection isn't introspectable from the writers alone.
# The chatbot reads every active collection by design: it builds its view of
# the vault from this very file, so a new collection is queryable through it
# the moment the schema is regenerated.
CHATBOT_READER = "chatbot (ad-hoc questions over any collection, schema-driven)"
KNOWN_READERS = {
    "milking_controle_data": [
        "dashboard (/api/records, /api/stats)",
        "agent (analyses it, writes milking_insights)",
        CHATBOT_READER,
    ],
    "feed_distribution_data": [
        "dashboard (/api/stats: feed x milk join, efficiency, leftovers)",
        "agent (cow_feed_left, herd_feed_efficiency_change findings)",
        CHATBOT_READER,
    ],
    "milking_production_data": [
        "dashboard (/api/stats: speed/lactation scatter)",
        "agent (cow_speed_drop findings, lactation data)",
        CHATBOT_READER,
    ],
    "milking_insights": ["dashboard (/api/insights)", CHATBOT_READER],
}

# Collections that are part of the design but have no writer yet. Documented so
# a reader knows they are coming (and field_authority can already point at
# them) instead of discovering them by accident later.
PLANNED_COLLECTIONS = {
    "mpr_uitslag": {
        "note": (
            "CRV MPR results per cow per sampling (Dieroverzicht): levensnummer "
            "+ werknummer, cell count, fat/protein %, urea, lactation number "
            "and days. Parser not built yet. Once uploaded, this is the "
            "leading source for lactation data (see field_authority) and the "
            "only source for cell count. Links to the robot collections via "
            "werknummer (animal_number); the levensnummer <-> werknummer "
            "mapping lives in milking_controle_data (registration_number)."
        ),
    },
}

# Different sources can report the SAME quantity (the robot and CRV both track
# lactation). Writers never merge or overwrite each other -- every source
# stores its own records with its own `source` tag, and this table tells
# READERS which source to prefer per quantity. Resolution rule: walk the list
# in order and take the value from the first collection that has one for the
# animal/date at hand. Making CRV leading later is a change HERE, not a
# re-upload: the robot's values stay stored exactly as reported.
FIELD_AUTHORITY = {
    "lactation_days": [
        {
            "collection": "mpr_uitslag",
            "status": "planned",
            "note": "CRV registration -- leading as soon as it is uploaded",
        },
        {
            "collection": "milking_production_data",
            "field": "lactation_days",
            "status": "active",
            "note": "robot's own registration; less reliable, fallback only",
        },
    ],
    "lactation_number": [
        {
            "collection": "mpr_uitslag",
            "status": "planned",
            "note": "CRV registration -- leading as soon as it is uploaded",
        },
        {
            "collection": "milking_production_data",
            "field": "lactation_number",
            "status": "active",
            "note": "robot's own registration; less reliable, fallback only",
        },
    ],
    "milking_speed": [
        {
            "collection": "milking_production_data",
            "field": "average_milking_speed_kg_min",
            "status": "active",
            "note": "the robot measures this itself -- authoritative, CRV has no equivalent",
        },
    ],
    "cell_count": [
        {
            "collection": "mpr_uitslag",
            "status": "planned",
            "note": "only CRV measures cell count",
        },
    ],
}


def _query_help(collection, ontology_id):
    return {
        "python": f"vault.fetch_all('{collection}')",
        "dashboard_js": f"fetchAll(settings, '{collection}')",
        "graphql": (
            f'metaEnvelopes(filter: {{ ontologyId: "{ontology_id}" }}, '
            "first: 100, after: $cursor) "
            "{ edges { node { parsed } } pageInfo { hasNextPage endCursor } }"
        ),
    }


def _example_record(record_schema):
    example = {name: spec.get("example") for name, spec in record_schema.items()}
    if example and all(value is not None for value in example.values()):
        return example
    return None


def build():
    collections = {}

    # --- Collections written by the uploader (one per configured data source)
    uploader_settings = load_settings(UPLOADER_EXAMPLE)
    uploader_schema_ids = uploader_settings["vault"].get("schema_ids", {})
    for source_config in uploader_settings["sources"]:
        source = create_source(source_config)
        collection = source.collection
        ontology_id = uploader_schema_ids.get(collection, collection)
        example = _example_record(source.record_schema)
        collections[collection] = {
            "status": "active",
            "written_by": f"uploader (source type: {source.type_name})",
            "read_by": KNOWN_READERS.get(collection, []),
            "ontology_id": ontology_id,
            "vault_path_pattern": source.path_pattern,
            "vault_path_example": source.record_path(example) if example else None,
            "fields": source.record_schema,
            "how_to_query": _query_help(collection, ontology_id),
        }

    # --- Collection written by the AI agent
    agent_settings = json.loads(AGENT_EXAMPLE.read_text(encoding="utf-8"))
    agent_schema_ids = agent_settings["vault"].get("schema_ids", {})
    collection = agent_insights.COLLECTION
    ontology_id = agent_schema_ids.get(collection, collection)
    example = _example_record(agent_insights.RECORD_SCHEMA)
    collections[collection] = {
        "status": "active",
        "written_by": "agent (local LLM analysis of milking_controle_data)",
        "read_by": KNOWN_READERS.get(collection, []),
        "ontology_id": ontology_id,
        "vault_path_pattern": agent_insights.PATH_PATTERN,
        "vault_path_example": agent_insights.record_path(example) if example else None,
        "fields": agent_insights.RECORD_SCHEMA,
        "how_to_query": _query_help(collection, ontology_id),
        "note": (
            "Insights are written by a separate post-platform. 'evidence' holds "
            "figures computed in Python; 'title'/'body' are worded by the model "
            "named in 'model' -- so every insight can be checked against its "
            "own numbers."
        ),
    }

    for name, extra in PLANNED_COLLECTIONS.items():
        if name not in collections:
            collections[name] = {
                "status": "planned",
                "written_by": None,
                "read_by": KNOWN_READERS.get(name, []),
                "ontology_id": name,
                "vault_path_pattern": None,
                "vault_path_example": None,
                "fields": None,
                **extra,
            }

    return {
        "$generated_by": "generate_vault_schema.py -- do not hand-edit, regenerate instead",
        "$generated_at": datetime.now(timezone.utc).isoformat(),
        "vault_path_pattern": "{collection}/{subject}/{record_id}",
        "note": (
            "Every collection's ontology id is a plain stable string by default "
            "(the collection name itself) -- no Ontology-service registration "
            "required for store/fetch to work. See vault.schema_ids in a "
            "program's config/settings.json to map a collection to a registered "
            "Ontology W3ID instead, which is only needed for cross-platform "
            "interop."
        ),
        "field_authority": {
            "note": (
                "Which source READERS should prefer when multiple collections "
                "report the same quantity. Walk each list in order and take the "
                "first collection that has a value for the animal/date at hand. "
                "Writers never merge or overwrite: every source keeps its own "
                "records, provenance stays intact, and promoting a better "
                "source later (e.g. CRV) is an edit to this table -- no "
                "re-upload, no data loss."
            ),
            "fields": FIELD_AUTHORITY,
        },
        "collections": collections,
    }


if __name__ == "__main__":
    data = build()
    OUTPUT_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.name} ({len(data['collections'])} collections)")
