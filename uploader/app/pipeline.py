import argparse
import logging
import time

from app.config import STATE_DIRECTORY, load_settings
from app.sources import create_source
from app.state import SyncState
from app.vault_client import create_vault_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("uploader")


def run_once(sources, vault, states):
    for source in sources:
        records = source.records()
        state = states.get(source.collection)
        known = state.known if state else None
        if known is None:
            # No usable local sync state: rebuild the id set from the vault.
            # On the real eVault this is a full paged crawl and can take
            # minutes — it happens once; afterwards the state file keeps
            # every run incremental.
            logger.info(
                "Collection '%s': rebuilding sync state from the vault "
                "(first run; can take minutes on the real eVault)...",
                source.collection,
            )
            known = {record.get("id") for record in vault.fetch_all(source.collection)}
            if state:
                state.replace(known)
        new_records = [record for record in records if record["id"] not in known]

        def on_stored(chunk, _state=state, _known=known):
            # Runs after every successfully stored chunk, so an interrupted
            # run never re-uploads what already landed.
            ids = [record["id"] for record in chunk]
            _known.update(ids)
            if _state:
                _state.add(ids)

        vault.store_many(
            ((source.record_path(record), record) for record in new_records),
            on_stored=on_stored,
        )
        logger.info(
            "Collection '%s': uploaded %d new records (%d in source files, %d already stored)",
            source.collection,
            len(new_records),
            len(records),
            len(records) - len(new_records),
        )


def main():
    arguments = argparse.ArgumentParser(description="Melkmonitor data uploader")
    arguments.add_argument("--watch", action="store_true", help="keep running; re-scan periodically")
    arguments.add_argument(
        "--rebuild-state",
        action="store_true",
        help="discard the local sync state and rebuild it from the vault",
    )
    options = arguments.parse_args()

    settings = load_settings()
    vault = create_vault_client(settings["vault"])
    sources = [create_source(source_config) for source_config in settings["sources"]]

    # Local sync state is only worth it for the real eVault (rate-limited,
    # expensive to crawl); the local test vault is cheap to re-read every run.
    states = {}
    vault_config = settings["vault"]
    if vault_config.get("mode") == "evault":
        fingerprint = f"evault|{vault_config.get('registry_url')}|{vault_config.get('w3id')}"
        for source in sources:
            state_path = STATE_DIRECTORY / f"{source.collection}.json"
            if options.rebuild_state and state_path.exists():
                state_path.unlink()
            states[source.collection] = SyncState(state_path, fingerprint)

    run_once(sources, vault, states)
    while options.watch:
        time.sleep(settings.get("watch_interval_seconds", 60))
        run_once(sources, vault, states)
