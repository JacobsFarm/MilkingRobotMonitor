from datetime import datetime

SCHEMA_VERSION = 1
SOURCE = "milking_robot"
EXCLUDED_FIELDS = ("systemCode", "frameNumber", "bottleNumber")
KNOWN_STATUSES = ("OK", "!", "#")
ANIMAL_NUMBER_DIGITS = 4


def build_unique_id(animal_number, timestamp):
    return f"{animal_number}_{timestamp.strftime('%Y-%m-%dT%H-%M-%S')}"


def transform(raw):
    timestamp = datetime.strptime(
        f"{raw['milkingDate']} {raw['milkingTime']}", "%d-%m-%Y %H:%M:%S"
    )
    animal_number = int(raw["animalNumber"])
    if len(str(animal_number)) != ANIMAL_NUMBER_DIGITS:
        raise ValueError(f"animalNumber {animal_number} is not {ANIMAL_NUMBER_DIGITS} digits")
    status = raw["endOfMilkingStatus"]
    if status not in KNOWN_STATUSES:
        status = "#"
    yield_raw = float(raw["currentYield"])
    if yield_raw.is_integer():
        yield_raw = int(yield_raw)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": build_unique_id(animal_number, timestamp),
        "animal_number": animal_number,
        "registration_number": raw["registrationNumber"],
        "timestamp": timestamp.isoformat(),
        "status": status,
        "yield_raw": yield_raw,
        "source": SOURCE,
    }


def transform_all(raw_records):
    transformed = {}
    for raw in raw_records:
        try:
            record = transform(raw)
        except (KeyError, ValueError):
            continue
        transformed[record["id"]] = record
    return list(transformed.values())
