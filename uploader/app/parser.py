import csv
from pathlib import Path

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


def parse_file(file_path):
    records = []
    with open(file_path, encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if not row or row[0].strip().startswith("sep="):
                continue
            if len(row) < len(COLUMNS):
                continue
            records.append(dict(zip(COLUMNS, (value.strip() for value in row))))
    return records


def parse_directory(directory, pattern="*.txt"):
    records = []
    for file_path in sorted(Path(directory).glob(pattern)):
        records.extend(parse_file(file_path))
    return records
