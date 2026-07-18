"""Base class for data sources.

One DataSource = one kind of input data (milking robot files, feed computer
exports, health events, ...). A source knows three things:

1. how to read its raw input (``parse``),
2. how to normalize one raw row into a vault record (``transform``),
3. which vault collection its records belong to (``collection``).

Record contract — every transformed record MUST contain:

- ``schema_version`` (int)  — bump when the record shape changes,
- ``id`` (str)              — globally unique within the collection; used for
                              deduplication (the eVault has no overwrite-on-id),
- ``source`` (str)          — where the data came from,
- raw measured values, never derived/interpreted ones. Interpretation
  (liters, aggregates, insights) is the job of the readers.

Adding a new data source:
1. subclass ``DataSource`` in a new module under ``app/sources/``,
2. declare ``record_schema`` and ``path_pattern`` (see below) so the source is
   self-documenting,
3. register the class in ``app/sources/__init__.py`` (explicit import, so
   PyInstaller picks it up),
4. add a ``sources`` entry with its settings in ``config/settings.json``,
5. run ``python generate_vault_schema.py`` from the repo root to refresh
   ``VAULT_SCHEMA.json``, so readers (the dashboard, the agent, ...) know the
   new collection exists without reading this source's code.
The pipeline, vault clients and dedup state need no changes.
"""

import csv
from abc import ABC, abstractmethod


def read_delimited_rows(file_path):
    """Yield rows from a milking-robot CSV/TXT export.

    These exports declare their own separator on the first line (``sep=,``),
    which follows the robot's locale settings rather than a fixed convention --
    so honour that line instead of assuming a separator. Values containing the
    separator are quoted by the export (``"14,8"``), which csv handles.

    Read as UTF-8 with replacement: the ignored robot columns can contain
    anything (the feed export literally holds emoji), and that must never stop
    the data columns from parsing.
    """
    with open(file_path, encoding="utf-8-sig", errors="replace", newline="") as handle:
        first_line = handle.readline()
        if first_line.strip().lower().startswith("sep="):
            delimiter = first_line.strip()[4:] or ","
        else:
            # No declaration: guess from the header, then re-read from the top.
            delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
            handle.seek(0)
        yield from csv.reader(handle, delimiter=delimiter)


def parse_number(value):
    """Number from a Dutch robot export: decimal comma, empty -> None.
    Returns int when the value is integral (mirrors yield_raw handling)."""
    text = (value or "").strip().replace(",", ".")
    if not text:
        return None
    number = float(text)
    return int(number) if number.is_integer() else number


def parse_int(value):
    """Whole number, empty -> None. Raises ValueError on garbage, which
    records() treats as 'skip this row'."""
    text = (value or "").strip()
    return int(text) if text else None


class DataSource(ABC):

    #: registry key used as ``"type"`` in config; set by subclasses.
    type_name = None

    #: Declarative documentation of the record shape, keyed by field name:
    #: {"type": ..., "description": ..., "example": ..., "enum": [...] }.
    #: Purely descriptive (not validated at runtime) — consumed by
    #: generate_vault_schema.py to build VAULT_SCHEMA.json. Keep it in sync
    #: with what transform() actually returns.
    record_schema = {}

    #: Human-readable vault path template, e.g. "{collection}/{animal_number}/{id}".
    path_pattern = "{collection}/records/{id}"

    def __init__(self, source_config):
        self.config = source_config
        self.collection = source_config["collection"]

    @abstractmethod
    def parse(self):
        """Read the raw input and return a list of raw row dicts."""
        raise NotImplementedError

    @abstractmethod
    def transform(self, raw):
        """Normalize one raw row into a vault record (see record contract).

        Raise KeyError/ValueError (or return None) to skip an invalid row.
        """
        raise NotImplementedError

    def record_path(self, record):
        """Vault path for a record: collection/subject/unique_id.

        Default groups everything under one ``records`` subject; sources with a
        natural subject (e.g. an animal number) should override this.
        """
        return f"{self.collection}/records/{record['id']}"

    def records(self):
        """Parse + transform everything, deduplicated by record id."""
        unique = {}
        for raw in self.parse():
            try:
                record = self.transform(raw)
            except (KeyError, ValueError):
                continue
            if record:
                unique[record["id"]] = record
        return list(unique.values())
