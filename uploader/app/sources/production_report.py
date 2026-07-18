"""Daily per-cow production snapshot (robot ``Productie-rapport*.csv`` export)."""

import re
from datetime import datetime
from pathlib import Path

from app.sources.base import DataSource, parse_int, parse_number, read_delimited_rows

# The report date is not inside the file -- it is part of the file name
# (e.g. "Productie-rapport_5-7-2026.csv" or "..._2026-07-05.csv").
DATE_IN_NAME = (
    (re.compile(r"(\d{4}-\d{2}-\d{2})"), "%Y-%m-%d"),
    (re.compile(r"(\d{1,2}-\d{1,2}-\d{4})"), "%d-%m-%Y"),
)


def report_date_from_name(stem):
    for regex, date_format in DATE_IN_NAME:
        match = regex.search(stem)
        if match:
            return datetime.strptime(match.group(1), date_format).date().isoformat()
    return None


class ProductionReportSource(DataSource):
    """Reads ``Productie-rapport*.csv`` exports (';'-separated, decimal comma).

    One row per cow: 24h production, 10-day average, lactation number, average
    milking speed and days in lactation -- some measured, some computed by the
    robot, all stored exactly as the robot reported them (provenance is the
    ``source`` field). Files without a recognizable date in their name are
    skipped entirely: a snapshot without its date is meaningless.

    Provenance note: ``lactation_number`` and ``lactation_days`` come from the
    robot's own herd registration, which is less reliable than the CRV (MPR)
    registration that will be uploaded later. Records here keep the robot's
    values untouched; which source a reader should prefer per field is declared
    centrally in VAULT_SCHEMA.json under ``field_authority`` (robot stays
    authoritative for milking speed, CRV becomes leading for lactation data).
    """

    type_name = "production_report"

    SCHEMA_VERSION = 1
    SOURCE = "milking_robot_production"
    ANIMAL_NUMBER_DIGITS = 4

    path_pattern = "{collection}/{animal_number}/{id}"

    record_schema = {
        "schema_version": {
            "type": "integer",
            "description": "Bumped when this record's shape changes.",
            "example": SCHEMA_VERSION,
        },
        "id": {
            "type": "string",
            "description": (
                "Unique within the collection (one snapshot per cow per report "
                "date); used for dedup on upload."
            ),
            "format": "{animal_number}_{report_date}",
            "example": "5559_2026-07-05",
        },
        "animal_number": {
            "type": "integer",
            "description": "4-digit animal tag number (same numbering as milking_controle_data).",
            "example": 5559,
        },
        "report_date": {
            "type": "string",
            "description": "Date the snapshot describes (ISO 8601 date), taken from the file name.",
            "example": "2026-07-05",
        },
        "milk_24h_kg": {
            "type": "number",
            "description": "Milk produced in the last 24 hours (kg), as reported by the robot.",
            "example": 14.8,
        },
        "milk_10d_avg_kg": {
            "type": "number",
            "description": "10-day average of the 24h production (kg), as computed by the robot.",
            "example": 16.1,
        },
        "lactation_number": {
            "type": "integer",
            "description": (
                "Lactation number according to the ROBOT's herd registration. "
                "Less reliable than CRV; see field_authority in "
                "VAULT_SCHEMA.json -- CRV (mpr_uitslag) becomes the leading "
                "source for this once uploaded."
            ),
            "example": 1,
        },
        "average_milking_speed_kg_min": {
            "type": "number",
            "description": (
                "Average milking speed (kg/min), as measured by the robot. The "
                "robot is the authoritative source for this field."
            ),
            "example": 2.0,
        },
        "lactation_days": {
            "type": "integer",
            "description": (
                "Days in lactation according to the ROBOT's registration. Less "
                "reliable than CRV; see field_authority in VAULT_SCHEMA.json."
            ),
            "example": 229,
        },
        "source": {
            "type": "string",
            "description": "Constant identifying which DataSource produced this record.",
            "example": SOURCE,
        },
    }

    def parse(self):
        directory = Path(self.config["data_directory"])
        pattern = self.config.get("file_pattern", "Productie-rapport*.csv")
        rows = []
        for file_path in sorted(directory.glob(pattern)):
            report_date = report_date_from_name(file_path.stem)
            if not report_date:
                # A snapshot without its date cannot be stored truthfully.
                continue
            for row in read_delimited_rows(file_path):
                if len(row) < 6:
                    continue
                rows.append(
                    {
                        "report_date": report_date,
                        "cow_id": row[0].strip(),
                        "milk_24h": row[1].strip(),
                        "milk_10d_avg": row[2].strip(),
                        "lactation_number": row[3].strip(),
                        "milking_speed": row[4].strip(),
                        "lactation_days": row[5].strip(),
                    }
                )
        return rows

    def transform(self, raw):
        animal_number = int(raw["cow_id"])
        if len(str(animal_number)) != self.ANIMAL_NUMBER_DIGITS:
            raise ValueError(
                f"cow id {animal_number} is not {self.ANIMAL_NUMBER_DIGITS} digits"
            )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "id": f"{animal_number}_{raw['report_date']}",
            "animal_number": animal_number,
            "report_date": raw["report_date"],
            "milk_24h_kg": parse_number(raw["milk_24h"]),
            "milk_10d_avg_kg": parse_number(raw["milk_10d_avg"]),
            "lactation_number": parse_int(raw["lactation_number"]),
            "average_milking_speed_kg_min": parse_number(raw["milking_speed"]),
            "lactation_days": parse_int(raw["lactation_days"]),
            "source": self.SOURCE,
        }

    def record_path(self, record):
        return f"{self.collection}/{record['animal_number']}/{record['id']}"
