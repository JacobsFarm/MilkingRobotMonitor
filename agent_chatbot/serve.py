"""Entry point for the web chatbot -- the browser counterpart of run.py.

Same settings, same vault, same ChatSession; only the way in differs. Loading
the vault takes real time on a cold cache, so it happens once here at startup
rather than inside the first question.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `core`

from app.config import load_settings
from app.datastore import DataStore
from app.server import serve
from core.vault_client import create_vault_client

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser(
        description="Melkmonitor chatbot -- web interface"
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (0.0.0.0 to reach it from the tablet in the barn)")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--refresh", action="store_true",
                        help="re-read the vault instead of using the local cache")
    parser.add_argument("--verbose", action="store_true",
                        help="show data loading, requests and tool errors")
    options = parser.parse_args()
    logging.getLogger().setLevel(logging.INFO if options.verbose else logging.WARNING)

    settings = load_settings()
    vault = create_vault_client(settings["vault"])
    store = DataStore(settings, vault, refresh=options.refresh)

    # Warm the cache before the first browser question, and fail here -- at the
    # terminal, where someone is looking -- if the vault cannot be read at all.
    print("Loading the vault...")
    data_until = store.latest_milking_date()
    print(f"Data up to {data_until.isoformat() if data_until else 'unknown'}.")

    server = serve(settings, store, host=options.host, port=options.port)
    shown_host = "localhost" if options.host in ("127.0.0.1", "0.0.0.0") else options.host
    print(f"Chatbot running on http://{shown_host}:{options.port}")
    if not (Path(__file__).resolve().parent / "web" / "build").is_dir():
        print("No frontend build found -- run `npm run dev` in web/ and open http://localhost:5173")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
