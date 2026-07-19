"""The tools the model can call. This is where the project's core rule lands
for the chatbot: **the model composes, Python computes.**

73k+ milkings fit in no context window, and a language model doing its own
arithmetic over even a hundred rows produces confident, wrong sums. So the
model never receives raw records to add up -- it translates the farmer's
question into calls against this fixed, testable set of computations, and
words the result. Every figure in an answer is traceable to a tool result.

Adding a capability for the model = one entry in TOOLS (schema + function).
Keep results SMALL and include the caveats ('note', 'coverage') right in the
result: whatever the model should tell the farmer must travel inside the data
it quotes from.
"""

import json
from datetime import date, timedelta

from app.datastore import parse_date

MAX_ROWS = 100
MAX_GROUPS = 200

FILTER_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and a > b,
    "gte": lambda a, b: a is not None and a >= b,
    "lt": lambda a, b: a is not None and a < b,
    "lte": lambda a, b: a is not None and a <= b,
    "in": lambda a, b: a in b,
    "between": lambda a, b: a is not None and b[0] <= a <= b[1],
    "contains": lambda a, b: isinstance(a, str) and str(b).lower() in a.lower(),
}


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _rounded(value, digits=2):
    return round(value, digits) if isinstance(value, float) else value


def _date_range(store, date_from, date_to):
    """Default period = everything up to the newest milking. Anchored on the
    data, not on today: the vault may be running behind."""
    latest = store.latest_milking_date() or date.today()
    parsed_to = parse_date(date_to) or latest
    parsed_from = parse_date(date_from) or date.fromisoformat("1900-01-01")
    return parsed_from, parsed_to


def _liters_per_day_by_cow(store, date_from, date_to, animals=None):
    """{animal: {date: liters}} over the period. The base of every yield tool:
    per day rather than per milking, so visit frequency doesn't masquerade as
    production."""
    wanted = set(animals) if animals else None
    per_cow = {}
    for record in store.milkings():
        day = record.get("date")
        liters = record.get("liters")
        animal = record.get("animal_number")
        if day is None or liters is None or animal is None:
            continue
        if wanted is not None and animal not in wanted:
            continue
        parsed = date.fromisoformat(day)
        if not (date_from <= parsed <= date_to):
            continue
        per_cow.setdefault(animal, {}).setdefault(day, 0.0)
        per_cow[animal][day] += liters
    return per_cow


def _trend(daily):
    """First-third vs last-third comparison of a {date: value} series. Blunt on
    purpose: robust against gaps, and honest for short series (returns None
    below 6 measured days rather than a trend made of noise)."""
    if len(daily) < 6:
        return None
    days = sorted(daily)
    third = len(days) // 3
    start = _mean([daily[d] for d in days[:third]])
    end = _mean([daily[d] for d in days[-third:]])
    if not start:
        return None
    return {
        "start_liters_per_day": round(start, 1),
        "end_liters_per_day": round(end, 1),
        "change_pct": round((end - start) / start * 100, 1),
        "days_measured": len(days),
    }


# --- tool implementations ---------------------------------------------------


def describe_vault(store, args):
    """What the model consults instead of guessing field names."""
    collections = {}
    for name, info in store.active_collections().items():
        fields = {
            field: spec.get("description", spec.get("type", ""))
            for field, spec in (info.get("fields") or {}).items()
        }
        loaded = store._records.get(name)
        entry = {
            "written_by": info.get("written_by"),
            "fields": fields,
            "derived_fields_added_at_load": ["date"],
        }
        if name == "milking_controle_data":
            entry["derived_fields_added_at_load"] += ["liters", "milking_ok"]
        if name == "feed_distribution_data":
            entry["derived_fields_added_at_load"] += ["feed_total_kg"]
        if loaded is not None:
            dates = sorted(r["date"] for r in loaded if r.get("date"))
            entry["record_count"] = len(loaded)
            if dates:
                entry["date_range"] = {"from": dates[0], "until": dates[-1]}
        collections[name] = entry
    return {
        "collections": collections,
        "field_authority": store.schema.get("field_authority", {}).get("fields", {}),
        "planned_collections": [
            name
            for name, info in store.schema.get("collections", {}).items()
            if info.get("status") == "planned"
        ],
        "note": (
            "record_count/date_range appear once a collection has been touched "
            "by another tool. Quantities: liters (converted), feed_total_kg "
            "(converted), *_raw fields are as the robot reported them."
        ),
    }


def query_records(store, args):
    """Generic filter/group/aggregate over ANY active collection -- including
    ones added after this code was written. The escape hatch that keeps the
    chatbot useful when a question doesn't fit a specialized tool."""
    records = store.records(args["collection"])
    for spec in args.get("filters") or []:
        op = FILTER_OPS.get(spec.get("op", "eq"))
        if op is None:
            raise ValueError(f"Unknown filter op '{spec.get('op')}' (known: {sorted(FILTER_OPS)})")
        field, value = spec["field"], spec.get("value")
        records = [r for r in records if op(r.get(field), value)]

    group_by = args.get("group_by")
    metrics = args.get("metrics") or []
    if not group_by and not metrics:
        limit = min(int(args.get("limit") or 20), MAX_ROWS)
        return {
            "total_matching": len(records),
            "returned": min(limit, len(records)),
            "rows": records[:limit],
            "note": "Sample only. Use group_by/metrics for figures over all matches.",
        }

    groups = {}
    for record in records:
        key = record.get(group_by) if group_by else "all"
        groups.setdefault(key, []).append(record)

    rows = []
    for key, members in groups.items():
        row = {group_by or "group": key, "count": len(members)}
        for metric in metrics:
            op, field = metric["op"], metric.get("field")
            values = [m.get(field) for m in members if isinstance(m.get(field), (int, float))]
            label = f"{op}_{field}" if field else op
            if op == "count":
                row[label] = len(members)
            elif not values:
                row[label] = None
            elif op == "sum":
                row[label] = _rounded(sum(values))
            elif op == "mean":
                row[label] = _rounded(sum(values) / len(values))
            elif op == "min":
                row[label] = min(values)
            elif op == "max":
                row[label] = max(values)
            else:
                raise ValueError(f"Unknown metric op '{op}' (known: count, sum, mean, min, max)")
        rows.append(row)

    sort_by = args.get("sort_by")
    if sort_by:
        rows.sort(key=lambda r: (r.get(sort_by) is None, r.get(sort_by)), reverse=bool(args.get("sort_desc")))
    limit = min(int(args.get("limit") or 50), MAX_GROUPS)
    return {"total_groups": len(rows), "returned": min(limit, len(rows)), "rows": rows[:limit]}


def lactation_cohort(store, args):
    """Cows in a DIM window during a period, optionally with their yield trend
    over exactly the dates they were inside the window."""
    lactation = store.lactation()
    latest = store.latest_milking_date() or date.today()
    date_to = parse_date(args.get("date_to")) or latest
    date_from = parse_date(args.get("date_from")) or date_to
    cows = lactation.cows_in_dim_window(
        int(args["dim_min"]), int(args["dim_max"]), date_from, date_to
    )

    result = {
        "period": {"from": date_from.isoformat(), "until": date_to.isoformat()},
        "dim_window": [int(args["dim_min"]), int(args["dim_max"])],
        "cows": cows,
        "cow_count": len(cows),
        "coverage": lactation.coverage_note,
    }
    if args.get("with_yield_trend"):
        trends = []
        for cow in cows:
            daily = _liters_per_day_by_cow(
                store,
                date.fromisoformat(cow["in_window_from"]),
                date.fromisoformat(cow["in_window_until"]),
                animals=[cow["animal_number"]],
            ).get(cow["animal_number"], {})
            trend = _trend(daily)
            cow["yield_trend"] = trend
            cow["mean_liters_per_day"] = (
                round(_mean(list(daily.values())), 1) if daily else None
            )
            if trend:
                trends.append(trend)
        changes = [t["change_pct"] for t in trends]
        result["group_summary"] = {
            "cows_with_enough_data": len(trends),
            "mean_change_pct": round(_mean(changes), 1) if changes else None,
            # Group-level liters too: without them a model asked for "group
            # level" fills the gap with one cow's figures.
            "group_mean_start_liters_per_day": (
                round(_mean([t["start_liters_per_day"] for t in trends]), 1) if trends else None
            ),
            "group_mean_end_liters_per_day": (
                round(_mean([t["end_liters_per_day"] for t in trends]), 1) if trends else None
            ),
            "risen": sum(1 for c in changes if c > 0),
            "fallen": sum(1 for c in changes if c < 0),
            "note": (
                "Each cow's trend covers her OWN dates inside the DIM window "
                "(first third vs last third of her measured days), so early- "
                "and late-period cows are compared fairly."
            ),
        }
    return result


def daily_yield(store, args):
    """Milk per day: herd series, or per-cow summaries."""
    date_from, date_to = _date_range(store, args.get("date_from"), args.get("date_to"))
    per_cow = _liters_per_day_by_cow(store, date_from, date_to, args.get("animals"))

    herd_by_day = {}
    for daily in per_cow.values():
        for day, liters in daily.items():
            herd_by_day[day] = herd_by_day.get(day, 0.0) + liters
    days = sorted(herd_by_day)
    if not days:
        return {"note": "No milkings in this period.", "period": [str(date_from), str(date_to)]}

    result = {
        "period": {"from": days[0], "until": days[-1]},
        "days_measured": len(days),
        "cows": len(per_cow),
        "herd_mean_liters_per_day": round(_mean(list(herd_by_day.values())), 1),
        "herd_trend": _trend(herd_by_day),
    }
    if args.get("per_cow"):
        summaries = []
        for animal, daily in per_cow.items():
            summaries.append(
                {
                    "animal_number": animal,
                    "mean_liters_per_day": round(_mean(list(daily.values())), 1),
                    "days_measured": len(daily),
                    "trend": _trend(daily),
                }
            )
        summaries.sort(key=lambda s: s["mean_liters_per_day"], reverse=True)
        result["per_cow"] = summaries[:MAX_ROWS]
        if len(summaries) > MAX_ROWS:
            result["note"] = f"Top {MAX_ROWS} of {len(summaries)} cows by mean yield."
    if args.get("include_series"):
        # Weekly buckets keep the series readable for long periods.
        if len(days) > 45:
            weekly = {}
            for day, liters in herd_by_day.items():
                year, week, _ = date.fromisoformat(day).isocalendar()
                weekly.setdefault(f"{year}-W{week:02d}", []).append(liters)
            result["herd_series_weekly_mean"] = {
                week: round(_mean(values), 1) for week, values in sorted(weekly.items())
            }
        else:
            result["herd_series"] = {day: round(herd_by_day[day], 1) for day in days}
    return result


def compare_windows(store, args):
    """Who moved between two periods -- both directions, so 'which cows improved'
    is as answerable as 'which cows fell'."""
    metric = args.get("metric", "yield")
    a_from, a_to = parse_date(args["a_from"]), parse_date(args["a_to"])
    b_from, b_to = parse_date(args["b_from"]), parse_date(args["b_to"])
    if None in (a_from, a_to, b_from, b_to):
        raise ValueError("a_from/a_to/b_from/b_to must be ISO dates (YYYY-MM-DD)")
    animals = args.get("animals")

    def per_cow_value(date_from, date_to):
        if metric == "yield":
            return {
                animal: (_mean(list(daily.values())), len(daily))
                for animal, daily in _liters_per_day_by_cow(store, date_from, date_to, animals).items()
            }
        if metric in ("visits", "interval_hours"):
            stats = {}
            for record in store.milkings():
                day = record.get("date")
                animal = record.get("animal_number")
                if day is None or animal is None:
                    continue
                if animals and animal not in animals:
                    continue
                if date_from <= date.fromisoformat(day) <= date_to:
                    entry = stats.setdefault(animal, {"visits": 0, "days": set()})
                    entry["visits"] += 1
                    entry["days"].add(day)
            result = {}
            for animal, entry in stats.items():
                per_day = entry["visits"] / len(entry["days"])
                value = 24.0 / per_day if metric == "interval_hours" else per_day
                result[animal] = (value, len(entry["days"]))
            return result
        if metric in ("feed_kg", "feed_left_rate"):
            stats = {}
            for record in store.records("feed_distribution_data"):
                day = record.get("date")
                animal = record.get("animal_number")
                if day is None or animal is None:
                    continue
                if animals and animal not in animals:
                    continue
                if not (date_from <= date.fromisoformat(day) <= date_to):
                    continue
                entry = stats.setdefault(animal, {"kg": 0.0, "events": 0, "left": 0, "days": set()})
                entry["kg"] += record.get("feed_total_kg") or 0
                entry["events"] += 1
                entry["days"].add(day)
                if record.get("all_feed_consumed") is False:
                    entry["left"] += 1
            result = {}
            for animal, entry in stats.items():
                if metric == "feed_kg":
                    result[animal] = (entry["kg"] / len(entry["days"]), len(entry["days"]))
                else:
                    result[animal] = (entry["left"] / entry["events"], len(entry["days"]))
            return result
        raise ValueError(
            f"Unknown metric '{metric}' (known: yield, visits, interval_hours, feed_kg, feed_left_rate)"
        )

    window_a = per_cow_value(a_from, a_to)
    window_b = per_cow_value(b_from, b_to)
    min_days = int(args.get("min_days") or 3)

    rows = []
    for animal in set(window_a) & set(window_b):
        (value_a, days_a), (value_b, days_b) = window_a[animal], window_b[animal]
        if days_a < min_days or days_b < min_days or value_a is None or value_b is None:
            continue
        change = ((value_b - value_a) / value_a * 100) if value_a else None
        rows.append(
            {
                "animal_number": animal,
                "window_a": round(value_a, 2),
                "window_b": round(value_b, 2),
                "change_pct": round(change, 1) if change is not None else None,
            }
        )
    direction = args.get("direction", "both")
    if direction == "down":
        rows = [r for r in rows if (r["change_pct"] or 0) < 0]
        rows.sort(key=lambda r: r["change_pct"])
    elif direction == "up":
        rows = [r for r in rows if (r["change_pct"] or 0) > 0]
        rows.sort(key=lambda r: r["change_pct"], reverse=True)
    else:
        rows.sort(key=lambda r: abs(r["change_pct"] or 0), reverse=True)
    top = min(int(args.get("top") or 20), MAX_ROWS)

    herd_a = _mean([r["window_a"] for r in rows])
    herd_b = _mean([r["window_b"] for r in rows])
    return {
        "metric": metric,
        "window_a": {"from": str(a_from), "until": str(a_to)},
        "window_b": {"from": str(b_from), "until": str(b_to)},
        "cows_compared": len(rows),
        "herd_mean_a": round(herd_a, 2) if herd_a is not None else None,
        "herd_mean_b": round(herd_b, 2) if herd_b is not None else None,
        "biggest_changes": rows[:top],
        "note": f"Cows need >= {min_days} measured days in each window to be compared.",
    }


def cow_profile(store, args):
    """Everything about one cow, across every collection -- the 'tell me about
    5337' question, and the drill-down after any other tool flagged her."""
    animal = int(args["animal_number"])
    latest = store.latest_milking_date() or date.today()
    recent_from = latest - timedelta(days=28)
    previous_from = recent_from - timedelta(days=28)

    daily = _liters_per_day_by_cow(store, previous_from, latest, [animal]).get(animal, {})
    recent = {d: v for d, v in daily.items() if date.fromisoformat(d) > recent_from}
    previous = {d: v for d, v in daily.items() if date.fromisoformat(d) <= recent_from}

    registration = None
    for record in store.milkings():
        if record.get("animal_number") == animal and record.get("registration_number"):
            registration = record["registration_number"]
            break

    feed = [
        r
        for r in store.records("feed_distribution_data")
        if r.get("animal_number") == animal
        and r.get("date")
        and date.fromisoformat(r["date"]) > recent_from
    ]
    production = sorted(
        (r for r in store.records("milking_production_data") if r.get("animal_number") == animal),
        key=lambda r: r.get("report_date") or "",
    )
    insights = sorted(
        (
            r
            for r in store.records("milking_insights")
            if (r.get("scope") or {}).get("animal_number") == animal
        ),
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )

    lactation = store.lactation()
    recent_mean = _mean(list(recent.values()))
    previous_mean = _mean(list(previous.values()))
    return {
        "animal_number": animal,
        "registration_number": registration,
        "lactation": {
            "days_in_milk_now": lactation.dim_on(animal, latest),
            "lactation_number": lactation.lactation_number.get(animal),
            "note": lactation.coverage_note,
        },
        "yield_last_28_days": {
            "mean_liters_per_day": round(recent_mean, 1) if recent_mean else None,
            "days_measured": len(recent),
            "vs_previous_28_days_pct": (
                round((recent_mean - previous_mean) / previous_mean * 100, 1)
                if recent_mean and previous_mean
                else None
            ),
        },
        "feed_last_28_days": {
            "feedings": len(feed),
            "left_feed_count": sum(1 for r in feed if r.get("all_feed_consumed") is False),
            "mean_kg_per_day": (
                round(sum(r.get("feed_total_kg") or 0 for r in feed) / len({r["date"] for r in feed}), 2)
                if feed
                else None
            ),
        },
        "production_reports": [
            {
                "report_date": r.get("report_date"),
                "milk_24h_kg": r.get("milk_24h_kg"),
                "milk_10d_avg_kg": r.get("milk_10d_avg_kg"),
                "speed_kg_min": r.get("average_milking_speed_kg_min"),
                "lactation_days": r.get("lactation_days"),
            }
            for r in production[-4:]
        ],
        "recent_insights": [
            {
                "created_at": r.get("created_at"),
                "type": r.get("type"),
                "severity": r.get("severity"),
                "title": r.get("title"),
            }
            for r in insights[:5]
        ],
    }


def list_insights(store, args):
    """What the analysis agent already flagged -- so the chatbot builds on the
    standing analysis instead of recomputing it."""
    records = store.records("milking_insights")
    if args.get("type"):
        records = [r for r in records if r.get("type") == args["type"]]
    if args.get("severity"):
        records = [r for r in records if r.get("severity") == args["severity"]]
    # Falsy animal_number (0/None) means no cow filter: small models tend to
    # fill optional integer parameters with 0, and no animal is numbered 0 --
    # taking it literally would silently hide every insight.
    if args.get("animal_number"):
        records = [
            r
            for r in records
            if (r.get("scope") or {}).get("animal_number") == int(args["animal_number"])
        ]
    since = parse_date(args.get("since"))
    if since:
        records = [r for r in records if (parse_date(r.get("created_at")) or date.min) >= since]
    records = sorted(records, key=lambda r: r.get("created_at") or "", reverse=True)
    return {
        "total_matching": len(records),
        "insights": [
            {
                "created_at": r.get("created_at"),
                "type": r.get("type"),
                "severity": r.get("severity"),
                "scope": r.get("scope"),
                "title": r.get("title"),
                "body": r.get("body"),
                "evidence": r.get("evidence"),
            }
            for r in records[:30]
        ],
    }


# --- registry ----------------------------------------------------------------

TOOLS = {
    "describe_vault": {
        "function": describe_vault,
        "description": (
            "What data exists: every collection in the farm's eVault, its fields "
            "(with meaning and units), counts and date ranges. Call this first "
            "when unsure which collection or field answers a question."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    "query_records": {
        "function": query_records,
        "description": (
            "Generic query over any collection from describe_vault: filter on "
            "fields, group by a field, aggregate (count/sum/mean/min/max). Use "
            "for questions no specialized tool covers. Useful derived fields: "
            "date (YYYY-MM-DD), liters, feed_total_kg, milking_ok."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string"},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "op": {
                                "type": "string",
                                "enum": sorted(FILTER_OPS),
                            },
                            "value": {},
                        },
                        "required": ["field", "op"],
                    },
                },
                "group_by": {"type": "string"},
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["count", "sum", "mean", "min", "max"]},
                            "field": {"type": "string"},
                        },
                        "required": ["op"],
                    },
                },
                "sort_by": {"type": "string"},
                "sort_desc": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
            "required": ["collection"],
        },
    },
    "lactation_cohort": {
        "function": lactation_cohort,
        "description": (
            "Cows whose days-in-milk (DIM) fell in [dim_min, dim_max] during a "
            "period, each with the exact dates she was inside that window. Set "
            "with_yield_trend=true to also get her milk trend over those dates "
            "plus a group summary. THE tool for lactation-stage questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dim_min": {"type": "integer"},
                "dim_max": {"type": "integer"},
                "date_from": {"type": "string", "description": "YYYY-MM-DD; default: newest data date"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD; default: newest data date"},
                "with_yield_trend": {"type": "boolean"},
            },
            "required": ["dim_min", "dim_max"],
        },
    },
    "daily_yield": {
        "function": daily_yield,
        "description": (
            "Milk production per day: herd mean and trend over a period, "
            "optionally per cow (per_cow=true) or with the day/week series "
            "(include_series=true). Dates default to all data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "animals": {"type": "array", "items": {"type": "integer"}},
                "per_cow": {"type": "boolean"},
                "include_series": {"type": "boolean"},
            },
        },
    },
    "compare_windows": {
        "function": compare_windows,
        "description": (
            "Compare two periods per cow and for the herd, on one metric: "
            "yield (L/day), visits (milkings/day), interval_hours, feed_kg "
            "(kg/day) or feed_left_rate. direction='down' for who fell, 'up' "
            "for who improved, 'both' (default) for the biggest movers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["yield", "visits", "interval_hours", "feed_kg", "feed_left_rate"],
                },
                "direction": {"type": "string", "enum": ["down", "up", "both"]},
                "a_from": {"type": "string"},
                "a_to": {"type": "string"},
                "b_from": {"type": "string"},
                "b_to": {"type": "string"},
                "animals": {"type": "array", "items": {"type": "integer"}},
                "top": {"type": "integer"},
                "min_days": {"type": "integer"},
            },
            "required": ["a_from", "a_to", "b_from", "b_to"],
        },
    },
    "cow_profile": {
        "function": cow_profile,
        "description": (
            "Everything about one cow: yield trend, feed intake and refusals, "
            "lactation stage, production reports, and what the analysis agent "
            "flagged about her. The drill-down after any tool names a cow."
        ),
        "parameters": {
            "type": "object",
            "properties": {"animal_number": {"type": "integer"}},
            "required": ["animal_number"],
        },
    },
    "list_insights": {
        "function": list_insights,
        "description": (
            "Findings the standing analysis agent already stored (yield drops, "
            "cows leaving feed, recoveries, multi-signal cows...). Check here "
            "before recomputing: 'is anything wrong' questions start here. "
            "Call it with NO arguments to see everything recent; only pass "
            "animal_number when asking about one specific cow."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "severity": {"type": "string", "enum": ["high", "medium"]},
                "animal_number": {"type": "integer", "description": "one specific cow; omit otherwise"},
                "since": {"type": "string", "description": "YYYY-MM-DD"},
            },
        },
    },
}


def tool_schemas():
    """Tool list in the shape Ollama's chat API expects."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for name, spec in TOOLS.items()
    ]


def run_tool(store, name, arguments):
    """Execute one tool call; errors come back as data so the model can correct
    itself (wrong field name, bad date) instead of the chat crashing."""
    spec = TOOLS.get(name)
    if spec is None:
        return {"error": f"Unknown tool '{name}' (available: {sorted(TOOLS)})"}
    try:
        return spec["function"](store, arguments or {})
    except (ValueError, KeyError, TypeError) as error:
        return {"error": f"{type(error).__name__}: {error}"}


def compact(result):
    return json.dumps(result, ensure_ascii=False, default=str)
