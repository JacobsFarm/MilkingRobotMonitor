import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    PROGRAM_ROOT = Path(sys.executable).resolve().parent
else:
    PROGRAM_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SETTINGS_PATH = PROGRAM_ROOT / "config" / "settings.json"
PATH_KEYS = ("data_directory",)
VAULT_PATH_KEYS = ("local_path", "epassport_path")


def _resolve(relative_path):
    return str((PROGRAM_ROOT / relative_path).resolve())


def load_settings(settings_path=None):
    settings_path = Path(settings_path) if settings_path else DEFAULT_SETTINGS_PATH
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    for key in PATH_KEYS:
        if key in settings:
            settings[key] = _resolve(settings[key])
    vault = settings.get("vault", {})
    for key in VAULT_PATH_KEYS:
        if key in vault:
            vault[key] = _resolve(vault[key])
    return settings
