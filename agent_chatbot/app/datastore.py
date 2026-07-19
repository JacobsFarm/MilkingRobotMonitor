"""The chatbot's view of the vault: schema-driven, cached, lazily loaded.

Everything the chatbot knows about the vault comes from VAULT_SCHEMA.json (the
generated contract at the repo root), not from hardcoded collection names. A
new data source therefore shows up here automatically: the uploader gains a
source, the schema is regenerated, and the chatbot can describe and query the
new collection without a code change.

Two things are added on top of the raw records:

- **Derived fields.** Raw records store what the robot reported (yield_raw,
  feed_a_raw..). Farmer questions are about liters, kg and dates, so each
  record is enriched once at load time: a `date`, and per-collection
  conversions declared in DERIVERS. Unknown collections still get `date`
  derived from whatever ISO date/timestamp field the schema shows.
- **The lactation model.** Days-in-milk per cow per date, derived from the
  production reports. Kept here (not in a tool) because several tools need it
  and because the derivation has a real pitfall -- see LactationModel.
"""

import logging
from datetime import date, datetime, timedelta

from core.record_cache import RecordCache, load_records

from app.config import CACHE_DIRECTORY, load_vault_schema, vault_fingerprint

logger = logging.getLogger("chatbot.data")


def parse_date(value):
    """ISO date or timestamp string -> datetime.date, else None."""
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _derive_milking(record, settings):
    raw = record.get("yield_raw")
    if isinstance(raw, (int, float)):
        record["liters"] = round(raw / settings.get("yield_divisor", 1000), 2)
    record["milking_ok"] = record.get("status") == "OK"


def _derive_feed(record, settings):
    total = 0
    for key in ("feed_a_raw", "feed_b_raw", "feed_c_raw", "feed_d_raw"):
        value = record.get(key)
        if isinstance(value, (int, float)):
            total += value
    record["feed_total_kg"] = round(total / settings.get("feed_divisor", 1000), 3)


# Per-collection enrichment. Keyed by collection name; anything not listed
# still gets the generic `date` field, so future collections are queryable
# from day one (in their raw units) and only need an entry here when a unit
# conversion is worth adding.
DERIVERS = {
    "milking_controle_data": _derive_milking,
    "feed_distribution_data": _derive_feed,
}

# Which fields can carry the record's date, in preference order.
DATE_FIELD_CANDIDATES = ("timestamp", "report_date", "created_at")


class LactationModel:
    """Days-in-milk (DIM) per cow per date, from the production reports.

    Each report gives (report_date, lactation_days) per cow, so the estimated
    calving date is report_date - lactation_days. The **newest** report per cow
    is used as the anchor: verified against this vault, the robot's DIM counter
    drifts (it advanced 12 days over a 13-day gap between reports for 41 of 49
    cows), so estimates from different reports disagree by a day or more. One
    consistent anchor keeps every DIM in an answer on the same basis; the
    remaining uncertainty (~2 days) is reported so answers can say so.

    Coverage: only cows present in a production report have a DIM at all.
    Tools must surface `coverage_note` rather than silently answering about
    the covered subset.
    """

    UNCERTAINTY_DAYS = 2

    def __init__(self, production_records):
        self.calving = {}
        self.lactation_number = {}
        newest = {}
        for record in production_records:
            animal = record.get("animal_number")
            report_date = parse_date(record.get("report_date"))
            dim = record.get("lactation_days")
            if animal is None or report_date is None or not isinstance(dim, int):
                continue
            if animal not in newest or report_date > newest[animal]:
                newest[animal] = report_date
                self.calving[animal] = report_date - timedelta(days=dim)
                number = record.get("lactation_number")
                if isinstance(number, int):
                    self.lactation_number[animal] = number

    def dim_on(self, animal, on_date):
        calving = self.calving.get(animal)
        if calving is None:
            return None
        days = (on_date - calving).days
        return days if days >= 0 else None

    def cows_in_dim_window(self, dim_min, dim_max, date_from, date_to):
        """Cows whose DIM fell inside [dim_min, dim_max] at any point during
        [date_from, date_to], with the exact dates they were inside it.

        'Cows at 60-100 days over the last 3 months' is genuinely ambiguous:
        a 40-day DIM window is narrower than a 3-month period, so cows slide
        through it and the set at the start shares nobody with the set at the
        end (verified on this vault: overlap 0). Returning each cow's own
        in-window dates makes that explicit instead of silently picking one
        reading.
        """
        result = []
        for animal, calving in self.calving.items():
            window_start = calving + timedelta(days=dim_min)
            window_end = calving + timedelta(days=dim_max)
            overlap_start = max(window_start, date_from)
            overlap_end = min(window_end, date_to)
            if overlap_start > overlap_end:
                continue
            result.append(
                {
                    "animal_number": animal,
                    "in_window_from": overlap_start.isoformat(),
                    "in_window_until": overlap_end.isoformat(),
                    "dim_on_start": (overlap_start - calving).days,
                    "dim_on_end": (overlap_end - calving).days,
                    "lactation_number": self.lactation_number.get(animal),
                }
            )
        result.sort(key=lambda entry: entry["animal_number"])
        return result

    @property
    def coverage_note(self):
        return (
            f"DIM is known for {len(self.calving)} cows (those in a robot "
            f"production report), with an uncertainty of about "
            f"{self.UNCERTAINTY_DAYS} days. Cows that left the herd before the "
            "first report have no DIM and are not included."
        )


class DataStore:

    def __init__(self, settings, vault, refresh=False):
        self.settings = settings
        self.vault = vault
        self.refresh = refresh
        self.schema = load_vault_schema()
        self.fingerprint = vault_fingerprint(settings["vault"])
        self._records = {}
        self._lactation = None

    # -- collections ---------------------------------------------------------

    def active_collections(self):
        return {
            name: info
            for name, info in self.schema.get("collections", {}).items()
            if info.get("status") == "active"
        }

    def _date_field_for(self, collection):
        fields = (self.schema["collections"].get(collection) or {}).get("fields") or {}
        for candidate in DATE_FIELD_CANDIDATES:
            if candidate in fields:
                return candidate
        return None

    def records(self, collection):
        """The collection's records, enriched, loading from cache/vault once."""
        if collection not in self.active_collections():
            known = ", ".join(sorted(self.active_collections()))
            raise ValueError(f"Unknown or inactive collection '{collection}' (active: {known})")
        if collection not in self._records:
            cache = RecordCache(CACHE_DIRECTORY / f"{collection}.json", self.fingerprint)
            records = load_records(self.vault, collection, cache, self.refresh, logger)
            self.refresh = False  # a --refresh run re-reads each collection once
            date_field = self._date_field_for(collection)
            deriver = DERIVERS.get(collection)
            for record in records:
                if date_field:
                    parsed = parse_date(record.get(date_field))
                    record["date"] = parsed.isoformat() if parsed else None
                if deriver:
                    deriver(record, self.settings)
            self._records[collection] = records
        return self._records[collection]

    # -- lactation -----------------------------------------------------------

    def lactation(self):
        if self._lactation is None:
            self._lactation = LactationModel(self.records("milking_production_data"))
        return self._lactation

    # -- common shortcuts ----------------------------------------------------

    def milkings(self):
        return self.records("milking_controle_data")

    def latest_milking_date(self):
        dates = [r["date"] for r in self.milkings() if r.get("date")]
        return date.fromisoformat(max(dates)) if dates else None
