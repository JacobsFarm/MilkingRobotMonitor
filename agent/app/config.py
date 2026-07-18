import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    PROGRAM_ROOT = Path(sys.executable).resolve().parent
else:
    PROGRAM_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SETTINGS_PATH = PROGRAM_ROOT / "config" / "settings.json"
CACHE_DIRECTORY = PROGRAM_ROOT / "cache"
VAULT_PATH_KEYS = ("local_path",)


def load_settings(settings_path=None):
    settings_path = Path(settings_path) if settings_path else DEFAULT_SETTINGS_PATH
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    vault = settings.get("vault", {})
    for key in VAULT_PATH_KEYS:
        if key in vault:
            vault[key] = str((PROGRAM_ROOT / vault[key]).resolve())
    return settings


def vault_fingerprint(vault_config):
    """Identifies which vault a cache belongs to (see app/cache.py)."""
    if vault_config.get("mode") == "evault":
        return f"evault|{vault_config.get('registry_url')}|{vault_config.get('w3id')}"
    return f"local|{vault_config.get('local_path')}"
