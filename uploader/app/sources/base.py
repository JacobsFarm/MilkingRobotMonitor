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
2. register the class in ``app/sources/__init__.py`` (explicit import, so
   PyInstaller picks it up),
3. add a ``sources`` entry with its settings in ``config/settings.json``.
The pipeline, vault clients, dedup state and dashboard need no changes.
"""

from abc import ABC, abstractmethod


class DataSource(ABC):

    #: registry key used as ``"type"`` in config; set by subclasses.
    type_name = None

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
