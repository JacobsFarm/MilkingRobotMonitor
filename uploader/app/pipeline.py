import argparse
import logging
import time

from app.config import load_settings
from app.parser import parse_directory
from app.transformer import transform_all
from app.vault_client import create_vault_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("uploader")


def run_once(settings, vault):
    raw_records = parse_directory(
        settings["data_directory"], settings.get("file_pattern", "*.txt")
    )
    records = transform_all(raw_records)
    base_path = settings.get("base_path", "milking_controle_data")
    for record in records:
        vault.store(f"{base_path}/{record['animal_number']}/{record['id']}", record)
    logger.info(
        "Uploaded %d unique records from %d raw rows", len(records), len(raw_records)
    )


def main():
    arguments = argparse.ArgumentParser(description="Milking control data uploader")
    arguments.add_argument("--watch", action="store_true")
    options = arguments.parse_args()
    settings = load_settings()
    vault = create_vault_client(settings["vault"])
    run_once(settings, vault)
    while options.watch:
        time.sleep(settings.get("watch_interval_seconds", 60))
        run_once(settings, vault)
