import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    PROGRAM_ROOT = Path(sys.executable).resolve().parent
else:
    PROGRAM_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SETTINGS_PATH = PROGRAM_ROOT / "config" / "settings.json"
STATE_DIRECTORY = PROGRAM_ROOT / "state"
VAULT_PATH_KEYS = ("local_path",)


def _resolve(relative_path):
    return str((PROGRAM_ROOT / relative_path).resolve())


def _normalize_sources(settings):
    """Return the list of data-source configs.

    New format: a top-level ``sources`` array, one entry per data source.
    Legacy format (single milking-robot source configured via top-level
    ``data_directory`` / ``file_pattern`` / ``base_path``) is converted
    automatically so old settings.json files keep working.
    """
    sources = settings.get("sources")
    if not sources:
        sources = [
            {
                "type": "milking_robot",
                "collection": settings.get("base_path", "milking_controle_data"),
                "data_directory": settings.get("data_directory", "../data"),
                "file_pattern": settings.get("file_pattern", "*.txt"),
            }
        ]
    for source in sources:
        if "data_directory" in source:
            source["data_directory"] = _resolve(source["data_directory"])
    return sources


def load_settings(settings_path=None):
    settings_path = Path(settings_path) if settings_path else DEFAULT_SETTINGS_PATH
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["sources"] = _normalize_sources(settings)
    vault = settings.get("vault", {})
    for key in VAULT_PATH_KEYS:
        if key in vault:
            vault[key] = _resolve(vault[key])
    return settings
