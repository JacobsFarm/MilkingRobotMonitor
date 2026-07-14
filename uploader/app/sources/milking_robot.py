"""Milking robot control files (FULLSENSE csv export)."""

import csv
from datetime import datetime
from pathlib import Path

from app.sources.base import DataSource

COLUMNS = (
    "animalNumber",
    "registrationNumber",
    "milkingDate",
    "milkingTime",
    "endOfMilkingStatus",
    "currentYield",
    "frameNumber",
    "bottleNumber",
    "systemCode",
)


class MilkingRobotSource(DataSource):
    """Reads FULLSENSE ``*.txt`` exports from a directory.

    Keeps the yield raw (``yield_raw``, exactly as the robot reported it) so the
    stored data stays machine-readable; converting to liters is the job of the
    readers at display time. Drops machine-internal columns, normalizes the
    status to ``OK`` / ``!`` / ``#`` and stamps every record with
    ``schema_version`` and ``source``.
    """

    type_name = "milking_robot"

    SCHEMA_VERSION = 1
    SOURCE = "milking_robot"
    KNOWN_STATUSES = ("OK", "!", "#")
    ANIMAL_NUMBER_DIGITS = 4

    def parse(self):
        directory = Path(self.config["data_directory"])
        pattern = self.config.get("file_pattern", "*.txt")
        rows = []
        for file_path in sorted(directory.glob(pattern)):
            with open(file_path, encoding="utf-8") as handle:
                for row in csv.reader(handle):
                    if not row or row[0].strip().startswith("sep="):
                        continue
                    if len(row) < len(COLUMNS):
                        continue
                    rows.append(dict(zip(COLUMNS, (value.strip() for value in row))))
        return rows

    def transform(self, raw):
        timestamp = datetime.strptime(
            f"{raw['milkingDate']} {raw['milkingTime']}", "%d-%m-%Y %H:%M:%S"
        )
        animal_number = int(raw["animalNumber"])
        if len(str(animal_number)) != self.ANIMAL_NUMBER_DIGITS:
            raise ValueError(
                f"animalNumber {animal_number} is not {self.ANIMAL_NUMBER_DIGITS} digits"
            )
        status = raw["endOfMilkingStatus"]
        if status not in self.KNOWN_STATUSES:
            status = "#"
        yield_raw = float(raw["currentYield"])
        if yield_raw.is_integer():
            yield_raw = int(yield_raw)
        return {
            "schema_version": self.SCHEMA_VERSION,
            "id": f"{animal_number}_{timestamp.strftime('%Y-%m-%dT%H-%M-%S')}",
            "animal_number": animal_number,
            "registration_number": raw["registrationNumber"],
            "timestamp": timestamp.isoformat(),
            "status": status,
            "yield_raw": yield_raw,
            "source": self.SOURCE,
        }

    def record_path(self, record):
        return f"{self.collection}/{record['animal_number']}/{record['id']}"
