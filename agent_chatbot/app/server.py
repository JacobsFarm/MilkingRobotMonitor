"""HTTP front door for the chatbot: the browser talks to the same ChatSession
the terminal REPL drives.

Nothing about the core rule changes here -- the model still composes and
`tools.py` still computes. This module only moves the conversation from stdin
to a socket, and turns run.py's `show_tool_call` printout into a stream of
server-sent events, so the browser can show which computation ran *while* the
answer is still being worked out.

Standard library only, like the rest of the program.

One request at a time per conversation: a ChatSession owns a message history,
so two overlapping questions on the same session would interleave into it. A
per-session lock serializes them; different browser tabs get different
sessions and run in parallel over the shared, read-only DataStore.

There are deliberately no CORS headers. This server hands out the farm's data
to anything that can reach it, so it must stay same-origin: in development the
Vite proxy fronts it, in production it serves the built frontend itself.
"""

import json
import logging
import mimetypes
import threading
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.chat import ChatSession

logger = logging.getLogger("chatbot.server")

# A browser tab that is closed never says goodbye, so sessions are evicted
# least-recently-used rather than on an explicit end.
MAX_SESSIONS = 50
MAX_QUESTION_CHARS = 2000
MAX_BODY_BYTES = 64_000

PROGRAM_ROOT = Path(__file__).resolve().parent.parent
WEB_BUILD = PROGRAM_ROOT / "web" / "build"


class SessionRegistry:
    """The live conversations, one per browser tab."""

    def __init__(self, settings, store):
        self.settings = settings
        self.store = store
        self._sessions = OrderedDict()
        self._guard = threading.Lock()

    def create(self):
        session_id = uuid.uuid4().hex
        session = ChatSession(self.settings, self.store)
        with self._guard:
            self._sessions[session_id] = (session, threading.Lock())
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
        return session_id

    def get(self, session_id):
        """The session plus its lock, marked as recently used."""
        with self._guard:
            entry = self._sessions.get(session_id)
            if entry is not None:
                self._sessions.move_to_end(session_id)
            return entry


class ChatRequestHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"
    server_version = "Melkmonitor-chatbot"

    # Injected by serve(); shared by every handler instance.
    registry = None
    settings = None
    store = None

    def log_message(self, format, *args):  # noqa: A002 - signature is the stdlib's
        logger.info("%s %s", self.address_string(), format % args)

    # -- routing -------------------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._health()
        elif path.startswith("/api/"):
            self._send_json(404, {"error": "unknown endpoint"})
        else:
            self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/session":
            self._send_json(200, {"session_id": self.registry.create()})
        elif path == "/api/ask":
            self._ask()
        else:
            self._send_json(404, {"error": "unknown endpoint"})

    # -- endpoints -----------------------------------------------------------

    def _health(self):
        """What the UI needs to explain itself before the first question:
        which model answers, how far the data reaches, and whether Ollama is
        actually up (the most common reason nothing works)."""
        llm = self.settings.get("llm", {})
        probe = ChatSession(self.settings, self.store)
        data_until = self.store.latest_milking_date()
        self._send_json(
            200,
            {
                "ollama_available": probe.available(),
                "model": llm.get("model", "qwen3:8b"),
                "host": llm.get("host", "http://localhost:11434"),
                "data_until": data_until.isoformat() if data_until else None,
                "collections": sorted(self.store.active_collections()),
                "farm": self.settings.get("farm_context") or {},
            },
        )

    def _ask(self):
        payload = self._read_json()
        if payload is None:
            self._send_json(400, {"error": "expected a JSON body"})
            return

        question = (payload.get("question") or "").strip()
        if not question:
            self._send_json(400, {"error": "question is required"})
            return
        if len(question) > MAX_QUESTION_CHARS:
            self._send_json(400, {"error": f"question exceeds {MAX_QUESTION_CHARS} characters"})
            return

        entry = self.registry.get(payload.get("session_id") or "")
        if entry is None:
            # Expired or unknown: the client is told to start a new one rather
            # than silently answering without the conversation's history.
            self._send_json(404, {"error": "unknown session", "code": "session_expired"})
            return

        self._start_event_stream()
        session, lock = entry
        with lock:
            session.on_tool_call = lambda name, arguments: self._emit(
                "tool", {"name": name, "arguments": arguments or {}}
            )
            try:
                answer = session.ask(question)
                self._emit("answer", {"content": answer})
            except RuntimeError as error:
                # Ollama unreachable or refusing: a normal condition on a farm
                # PC, so it is reported to the UI, not raised into a 500.
                self._emit("error", {"message": str(error)})
            except Exception:
                logger.exception("unexpected failure while answering")
                self._emit("error", {"message": "The chatbot hit an unexpected error."})
            finally:
                session.on_tool_call = None

    # -- server-sent events --------------------------------------------------

    def _start_event_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        # The stream ends by closing the connection, so its length is unknown
        # up front and it must not be kept alive.
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _emit(self, event, data):
        """One SSE frame. A closed tab shows up as a broken pipe; that is the
        client leaving, not an error worth surfacing."""
        frame = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        try:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            logger.info("client disconnected mid-answer")

    # -- plumbing ------------------------------------------------------------

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            body = self.rfile.read(length)
            parsed = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_static(self, path):
        """The built frontend, when there is one. In development Vite serves
        it instead and proxies /api here, so this stays unused."""
        if not WEB_BUILD.is_dir():
            self._send_json(
                404,
                {
                    "error": "no built frontend; run `npm run dev` in web/ "
                    "(development) or `npm run build` (production)"
                },
            )
            return

        relative = unquote(path).lstrip("/") or "index.html"
        target = (WEB_BUILD / relative).resolve()
        if not target.is_relative_to(WEB_BUILD.resolve()):
            self._send_json(403, {"error": "forbidden"})
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            target = WEB_BUILD / "index.html"  # client-side routing fallback
            if not target.is_file():
                self._send_json(404, {"error": "not found"})
                return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def serve(settings, store, host="127.0.0.1", port=8420):
    ChatRequestHandler.registry = SessionRegistry(settings, store)
    ChatRequestHandler.settings = settings
    ChatRequestHandler.store = store
    server = ThreadingHTTPServer((host, port), ChatRequestHandler)
    server.daemon_threads = True
    return server
