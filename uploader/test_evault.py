"""Standalone live-eVault self-test.

Reads uploader/config/settings.json, connects to the REAL MetaState W3DS eVault
configured there, stores one throwaway record in an isolated
'melkmonitor_selftest' collection and reads it back.

    cd uploader
    python test_evault.py

It never touches your real 'milking_controle_data'. Safe to run repeatedly.
Exit code 0 = round-trip works.
"""
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import load_settings
from app.vault_client import create_vault_client

TEST_COLLECTION = "melkmonitor_selftest"
FETCH_RETRIES = 5
FETCH_DELAY_SECONDS = 3


def main():
    settings = load_settings()
    vault_cfg = settings["vault"]
    mode = vault_cfg.get("mode")
    print(f"vault.mode   = {mode}")
    if mode != "evault":
        print('\n!! Set "mode": "evault" in uploader/config/settings.json first.')
        return 1
    print(f"registry_url = {vault_cfg.get('registry_url')}")
    print(f"w3id         = {vault_cfg.get('w3id')}")
    print(f"platform     = {vault_cfg.get('platform')}\n")

    client = create_vault_client(vault_cfg)
    # Isolated test collection so we never pollute real milking data.
    client.schema_ids[TEST_COLLECTION] = TEST_COLLECTION

    try:
        print("[1/4] Resolving eVault endpoint via registry ...")
        endpoint = client._resolve_endpoint()
        print(f"      -> {endpoint}")

        print("[2/4] Requesting platform token ...")
        token = client._get_token()
        print(f"      -> token received ({len(token)} chars)")

        record = {
            "schema_version": 1,
            "id": f"selftest_{uuid.uuid4().hex[:8]}",
            "source": "melkmonitor_selftest",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        print(f"[3/4] Storing test record id={record['id']} ...")
        client.store(f"{TEST_COLLECTION}/test/{record['id']}", record)
        print("      -> stored (no error)")

        print("[4/4] Fetching the collection back ...")
        for attempt in range(1, FETCH_RETRIES + 1):
            records = client.fetch_all(TEST_COLLECTION)
            found = any(r.get("id") == record["id"] for r in records)
            print(f"      attempt {attempt}: {len(records)} record(s), test record present: {found}")
            if found:
                print("\nSUCCESS -- store + fetch round-trip works against the real eVault.")
                return 0
            if attempt < FETCH_RETRIES:
                time.sleep(FETCH_DELAY_SECONDS)

        print("\nStored without error but the record did not come back in fetch.")
        print("Writes may need a moment to index -- re-run the script once more.")
        return 2
    except Exception as error:  # noqa: BLE001 - surface any failure clearly
        print(f"\nFAILED: {type(error).__name__}: {error}")
        print("\nCommon causes:")
        print("  - w3id has no provisioned eVault yet, or is mistyped (must be '@<uuid>').")
        print("  - The eVault is unreachable (registry resolved it but the host is down).")
        print("  - 401/403 on store: this platform is not allowed to write to that eVault.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
