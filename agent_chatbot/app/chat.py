"""The tool-calling conversation loop against a local Ollama model.

This is the counterpart of the analysis agent's one-shot prompt: here the
model drives. It receives the farmer's question plus the tool catalogue,
decides which computations to request, gets the results back, and answers --
possibly after several rounds. The analysis agent's core rule survives intact:
the model composes and words, every number is computed in tools.py.

Uses Ollama's native tools API (POST /api/chat with "tools"), which requires a
model trained for tool calling -- qwen3 is the default. Standard library only,
like the rest of the project.
"""

import json
import logging
import urllib.error
import urllib.request
from datetime import date

from app.tools import compact, run_tool, tool_schemas

logger = logging.getLogger("chatbot")

SYSTEM_PROMPT = """\
You are the data analyst for a dairy farm. You answer the farmer's questions
using the farm's own eVault data, which you reach exclusively through the
provided tools.

Rules:
- Every figure in your answer must come from a tool result in this
  conversation. Never estimate, extrapolate or recall numbers yourself.
- Answer in the language of the question.
- Not sure which collection or field holds something? Call describe_vault.
- 'Is anything wrong / opvallend?' questions: start from list_insights (the
  standing analysis), then drill into raw data with the other tools as needed.
- If a question is ambiguous (which period, which cows, fixed group vs
  everyone passing through a lactation window), pick the most reasonable
  reading, state that choice in one short line, and answer it.
- Pass on the caveats tools return (coverage, uncertainty, data lag) whenever
  they affect the answer.
- Be concrete and practical: name animal numbers, round sensibly, and keep the
  answer as short as the question allows. Plain text, no markdown tables.
- If the data cannot answer the question, say so and name what is missing.\
"""

FARM_CONTEXT_LABELS = {
    "herd_size": "Cows in the herd",
    "breed": "Breed",
    "robot_count": "Milking robots",
    "housing": "Housing and grazing",
    "typical_yield_liters_per_cow_day": "Typical yield per cow per day (L)",
    "calving_pattern": "Calving pattern",
    "notes": "Other notes from the farmer",
}


def build_system_prompt(settings, data_until=None):
    sections = [settings.get("llm", {}).get("system_prompt") or SYSTEM_PROMPT]
    farm_context = settings.get("farm_context") or {}
    lines = [
        f"- {FARM_CONTEXT_LABELS.get(key, key)}: {value}"
        for key, value in farm_context.items()
        if value not in (None, "", [], {})
    ]
    if lines:
        sections.append("This farm:\n" + "\n".join(lines))
    today = date.today().isoformat()
    data_note = f" The newest measurement in the vault is from {data_until}." if data_until else ""
    sections.append(
        f"Today is {today}.{data_note} Periods like 'last month' count back "
        "from the newest data, not from today, and answers should name the "
        "actual dates used."
    )
    return "\n\n".join(sections)


class ChatSession:

    def __init__(self, settings, store, on_tool_call=None):
        llm = settings.get("llm", {})
        self.host = llm.get("host", "http://localhost:11434").rstrip("/")
        self.model = llm.get("model", "qwen3:8b")
        self.temperature = llm.get("temperature", 0.2)
        self.num_ctx = llm.get("num_ctx", 16384)
        self.timeout_seconds = llm.get("timeout_seconds", 300)
        self.max_tool_rounds = llm.get("max_tool_rounds", 8)
        self.store = store
        self.on_tool_call = on_tool_call  # UI hook: show the farmer what runs
        self.messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    settings,
                    data_until=(store.latest_milking_date() or None),
                ),
            }
        ]

    def available(self):
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def _chat_request(self):
        payload = {
            "model": self.model,
            "messages": self.messages,
            "tools": tool_schemas(),
            "stream": False,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
        }
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Ollama returned HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, OSError) as error:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.host} ({error}). Is `ollama serve` running?"
            ) from error

    def ask(self, question):
        """One farmer question -> one answer, running as many tool rounds as
        the model asks for (bounded, so a confused model cannot loop forever)."""
        self.messages.append({"role": "user", "content": question})

        for _round in range(self.max_tool_rounds):
            body = self._chat_request()
            message = body.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            # The model's turn goes into history exactly as it came back,
            # including its tool_calls, so the transcript stays coherent.
            self.messages.append(message)

            if not tool_calls:
                return (message.get("content") or "").strip()

            for call in tool_calls:
                function = call.get("function") or {}
                name = function.get("name", "")
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):  # some models return JSON text
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                if self.on_tool_call:
                    self.on_tool_call(name, arguments)
                result = run_tool(self.store, name, arguments)
                self.messages.append(
                    {"role": "tool", "tool_name": name, "content": compact(result)}
                )

        return (
            "I hit the tool-call limit for one question without reaching an "
            "answer. Please ask it more specifically."
        )
