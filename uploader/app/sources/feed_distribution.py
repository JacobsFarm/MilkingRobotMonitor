"""Feed distribution per milking (robot ``Voerdistributie-rapport*.csv`` export)."""

from datetime import datetime
from pathlib import Path

from app.sources.base import DataSource, parse_number, read_delimited_rows


class FeedDistributionSource(DataSource):
    """Reads ``Voerdistributie-rapport*.csv`` exports (';'-separated).

    Column layout by position: two robot-internal columns that are ignored,
    then date (d-m-yyyy), time of the milking visit, cow id, whether the cow
    finished her feed (Ja/Nee) and the dispensed amount per feed type A-D
    exactly as the robot reported it. The header row and the export's empty
    filler rows fail to parse and are dropped by records().

    The timestamp is the milking visit this feeding belongs to, so readers can
    join a feeding to its milking in ``milking_controle_data`` on
    (animal_number, timestamp) -- the robot stamps both with the same visit.
    """

    type_name = "feed_distribution"

    SCHEMA_VERSION = 1
    SOURCE = "feed_distribution"
    ANIMAL_NUMBER_DIGITS = 4
    TIME_FORMATS = ("%H:%M:%S", "%H:%M")

    path_pattern = "{collection}/{animal_number}/{id}"

    record_schema = {
        "schema_version": {
            "type": "integer",
            "description": "Bumped when this record's shape changes.",
            "example": SCHEMA_VERSION,
        },
        "id": {
            "type": "string",
            "description": "Unique within the collection; used for dedup on upload.",
            "format": "{animal_number}_{timestamp:%Y-%m-%dT%H-%M}",
            "example": "5606_2026-07-05T22-18",
        },
        "animal_number": {
            "type": "integer",
            "description": "4-digit animal tag number (same numbering as milking_controle_data).",
            "example": 5606,
        },
        "timestamp": {
            "type": "string",
            "description": (
                "Start of the milking visit this feeding belongs to (ISO 8601, "
                "farm-local). Join key to milking_controle_data records of the "
                "same animal and visit."
            ),
            "example": "2026-07-05T22:18:00",
        },
        "all_feed_consumed": {
            "type": "boolean",
            "description": (
                "Whether the cow finished the dispensed feed (robot's Ja/Nee "
                "column); null when the export holds anything else."
            ),
            "example": True,
        },
        "feed_a_raw": {
            "type": "number",
            "description": (
                "Amount of feed type A exactly as the robot reported it (robot-"
                "configured unit, typically grams). Interpretation is the "
                "reader's job, like yield_raw."
            ),
            "example": 1800,
        },
        "feed_b_raw": {
            "type": "number",
            "description": "Amount of feed type B, as reported.",
            "example": 40,
        },
        "feed_c_raw": {
            "type": "number",
            "description": "Amount of feed type C, as reported.",
            "example": 0,
        },
        "feed_d_raw": {
            "type": "number",
            "description": "Amount of feed type D, as reported.",
            "example": 0,
        },
        "source": {
            "type": "string",
            "description": "Constant identifying which DataSource produced this record.",
            "example": SOURCE,
        },
    }

    def parse(self):
        directory = Path(self.config["data_directory"])
        pattern = self.config.get("file_pattern", "Voerdistributie-rapport*.csv")
        rows = []
        for file_path in sorted(directory.glob(pattern)):
            for row in read_delimited_rows(file_path):
                if len(row) < 10:
                    continue
                rows.append(
                    {
                        "date": row[2].strip(),
                        "time": row[3].strip(),
                        "cow_id": row[4].strip(),
                        "all_consumed": row[5].strip(),
                        "feed_a": row[6].strip(),
                        "feed_b": row[7].strip(),
                        "feed_c": row[8].strip(),
                        "feed_d": row[9].strip(),
                    }
                )
        return rows

    def _parse_timestamp(self, date_text, time_text):
        for time_format in self.TIME_FORMATS:
            try:
                return datetime.strptime(f"{date_text} {time_text}", f"%d-%m-%Y {time_format}")
            except ValueError:
                continue
        raise ValueError(f"unparseable visit time: {date_text} {time_text}")

    def transform(self, raw):
        timestamp = self._parse_timestamp(raw["date"], raw["time"])
        animal_number = int(raw["cow_id"])
        if len(str(animal_number)) != self.ANIMAL_NUMBER_DIGITS:
            raise ValueError(
                f"cow id {animal_number} is not {self.ANIMAL_NUMBER_DIGITS} digits"
            )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "id": f"{animal_number}_{timestamp.strftime('%Y-%m-%dT%H-%M')}",
            "animal_number": animal_number,
            "timestamp": timestamp.isoformat(),
            "all_feed_consumed": {"ja": True, "nee": False}.get(raw["all_consumed"].lower()),
            "feed_a_raw": parse_number(raw["feed_a"]),
            "feed_b_raw": parse_number(raw["feed_b"]),
            "feed_c_raw": parse_number(raw["feed_c"]),
            "feed_d_raw": parse_number(raw["feed_d"]),
            "source": self.SOURCE,
        }

    def record_path(self, record):
        return f"{self.collection}/{record['animal_number']}/{record['id']}"
