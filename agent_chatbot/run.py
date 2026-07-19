import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `core`

# The Windows console defaults to a legacy codepage (cp1252) that cannot print
# every character a model emits (arrows, curly quotes). Answers must never
# crash on their own punctuation.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from app.chat import ChatSession
from app.config import load_settings
from app.datastore import DataStore
from core.vault_client import create_vault_client

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")


def show_tool_call(name, arguments):
    """Transparency: the farmer sees which computation ran for each answer."""
    summary = ", ".join(f"{k}={v}" for k, v in arguments.items()) if arguments else ""
    print(f"  [{name}({summary})]")


def main():
    parser = argparse.ArgumentParser(description="Melkmonitor chatbot -- ask your eVault anything")
    parser.add_argument("--ask", help="one question, print the answer, exit")
    parser.add_argument(
        "--refresh", action="store_true", help="re-read the vault instead of using the local cache"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show data loading and tool errors"
    )
    options = parser.parse_args()
    if options.verbose:
        logging.getLogger().setLevel(logging.INFO)

    settings = load_settings()
    vault = create_vault_client(settings["vault"])
    store = DataStore(settings, vault, refresh=options.refresh)
    session = ChatSession(settings, store, on_tool_call=show_tool_call)

    if not session.available():
        model = settings.get("llm", {}).get("model", "qwen3:8b")
        print(
            f"Ollama is not reachable. Start it with `ollama serve` and make "
            f"sure the model is pulled: `ollama pull {model}`."
        )
        sys.exit(1)

    if options.ask:
        print(session.ask(options.ask))
        return

    print("Melkmonitor chatbot. Ask about your herd (type 'exit' to quit).")
    while True:
        try:
            question = input("\nvraag> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            continue
        if question.lower() in ("exit", "quit", "stop"):
            break
        try:
            print("\n" + session.ask(question))
        except RuntimeError as error:
            print(f"\n{error}")


if __name__ == "__main__":
    main()
