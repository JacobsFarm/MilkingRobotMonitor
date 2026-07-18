"""Turns raw milking records into a small set of hard findings.

This is deliberately the *only* place where numbers are produced. The LLM never
sees the raw records and never computes anything -- it receives these findings
and writes the farmer-facing explanation. That keeps every stored insight
auditable: the numbers come from here, the wording comes from the model.

It also keeps the prompt small. 64k records will not fit in a context window
(and a model would get the arithmetic wrong anyway); a few dozen findings do.

Adding a new kind of analysis = one more function returning findings in the
same shape, appended in build_findings().
"""

from datetime import timedelta

# A cow needs at least this many milkings in *each* window before we compare
# them, so a single missed day can't look like a collapse in production.
MIN_MILKINGS_PER_WINDOW = 4
# Relative change that counts as worth reporting.
YIELD_DROP_THRESHOLD = 0.15
YIELD_RISE_THRESHOLD = 0.20
INTERVAL_RISE_THRESHOLD = 0.30
# Failed/interrupted milkings; ratio of non-OK above this is flagged.
FAILURE_RATE_THRESHOLD = 0.20
MAX_FINDINGS_PER_KIND = 8
# Feed left uneaten (an early illness signal): flag a cow when she left feed at
# least this many times AND in at least this share of her recent feedings.
FEED_LEFT_MIN_EVENTS = 3
FEED_LEFT_RATE_THRESHOLD = 0.25
# Herd-level liters of milk per kg of feed; relative change that is flagged.
FEED_EFFICIENCY_THRESHOLD = 0.10
# Overlap days (feed AND milk data) needed before efficiency is comparable.
FEED_EFFICIENCY_MIN_DAYS = 3
# Milking speed drop between the two most recent production reports.
SPEED_DROP_THRESHOLD = 0.15


def liters_of(record, divisor):
    raw = record.get("yield_raw")
    if isinstance(raw, (int, float)):
        return raw / divisor
    return None


def enrich(records, divisor, parse_timestamp):
    """Parse timestamps and convert yield once, dropping unusable rows."""
    rows = []
    for record in records:
        timestamp = parse_timestamp(record.get("timestamp"))
        if timestamp is None:
            continue
        rows.append(
            {
                "animal_number": record.get("animal_number"),
                "registration_number": record.get("registration_number"),
                "timestamp": timestamp,
                "day": timestamp.date(),
                "status": record.get("status"),
                "liters": liters_of(record, divisor),
            }
        )
    rows.sort(key=lambda row: row["timestamp"])
    return rows


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _change(recent, baseline):
    """Relative change, or None when the baseline can't support a ratio."""
    if recent is None or baseline is None or baseline == 0:
        return None
    return (recent - baseline) / baseline


def _liters_per_cow_day(rows):
    """{animal: [liters produced on each day she was milked]} -- comparing per
    day rather than per milking, so a change in visit frequency doesn't get
    mistaken for a change in production."""
    per_cow_day = {}
    for row in rows:
        if row["liters"] is None:
            continue
        key = (row["animal_number"], row["day"])
        per_cow_day[key] = per_cow_day.get(key, 0.0) + row["liters"]
    by_cow = {}
    for (animal, _day), liters in per_cow_day.items():
        by_cow.setdefault(animal, []).append(liters)
    return by_cow


def _intervals_by_cow(rows):
    """Hours between consecutive milkings, per cow."""
    per_cow = {}
    for row in rows:
        per_cow.setdefault(row["animal_number"], []).append(row["timestamp"])
    intervals = {}
    for animal, stamps in per_cow.items():
        stamps.sort()
        hours = [
            (stamps[i] - stamps[i - 1]).total_seconds() / 3600
            for i in range(1, len(stamps))
        ]
        # Gaps beyond a day are export gaps between measurement sessions, not
        # real visit intervals; they'd swamp the average.
        intervals[animal] = [h for h in hours if 0 < h <= 24]
    return intervals


def split_windows(rows, recent_days, baseline_days):
    """Split into (recent, baseline) using the newest record as 'now', because
    the vault may not contain data up to today."""
    if not rows:
        return [], [], None
    latest = rows[-1]["timestamp"]
    recent_start = latest - timedelta(days=recent_days)
    baseline_start = recent_start - timedelta(days=baseline_days)
    recent = [r for r in rows if r["timestamp"] > recent_start]
    baseline = [r for r in rows if baseline_start < r["timestamp"] <= recent_start]
    return recent, baseline, latest


def _finding(kind, severity, scope, summary, metrics):
    return {
        "kind": kind,
        "severity": severity,
        "scope": scope,
        "summary": summary,
        "metrics": metrics,
    }


def herd_findings(recent, baseline):
    findings = []
    recent_days = len({row["day"] for row in recent})
    baseline_days = len({row["day"] for row in baseline})
    if not recent_days or not baseline_days:
        return findings

    recent_per_day = sum(r["liters"] or 0 for r in recent) / recent_days
    baseline_per_day = sum(r["liters"] or 0 for r in baseline) / baseline_days
    change = _change(recent_per_day, baseline_per_day)
    if change is not None and abs(change) >= 0.05:
        findings.append(
            _finding(
                "herd_yield_change",
                "high" if abs(change) >= 0.10 else "medium",
                {"herd": True},
                f"Herd yield per day {'down' if change < 0 else 'up'} "
                f"{abs(change) * 100:.1f}% "
                f"({baseline_per_day:.0f} -> {recent_per_day:.0f} L/day).",
                {
                    "recent_liters_per_day": round(recent_per_day, 1),
                    "baseline_liters_per_day": round(baseline_per_day, 1),
                    "change_pct": round(change * 100, 1),
                    "recent_days": recent_days,
                    "baseline_days": baseline_days,
                },
            )
        )

    recent_failures = sum(1 for r in recent if r["status"] != "OK")
    if recent and recent_failures / len(recent) >= FAILURE_RATE_THRESHOLD:
        rate = recent_failures / len(recent)
        findings.append(
            _finding(
                "herd_failure_rate",
                "medium",
                {"herd": True},
                f"{rate * 100:.1f}% of recent milkings did not finish normally "
                f"({recent_failures} of {len(recent)}).",
                {
                    "failure_rate_pct": round(rate * 100, 1),
                    "failed": recent_failures,
                    "total": len(recent),
                },
            )
        )
    return findings


def cow_yield_findings(recent, baseline):
    recent_by_cow = _liters_per_cow_day(recent)
    baseline_by_cow = _liters_per_cow_day(baseline)
    candidates = []
    for animal, recent_days_liters in recent_by_cow.items():
        baseline_days_liters = baseline_by_cow.get(animal, [])
        if (
            len(recent_days_liters) < MIN_MILKINGS_PER_WINDOW
            or len(baseline_days_liters) < MIN_MILKINGS_PER_WINDOW
        ):
            continue
        recent_avg = _mean(recent_days_liters)
        baseline_avg = _mean(baseline_days_liters)
        change = _change(recent_avg, baseline_avg)
        if change is None:
            continue
        if change <= -YIELD_DROP_THRESHOLD or change >= YIELD_RISE_THRESHOLD:
            candidates.append((abs(change), animal, recent_avg, baseline_avg, change,
                               len(recent_days_liters), len(baseline_days_liters)))

    candidates.sort(reverse=True)
    findings = []
    for _, animal, recent_avg, baseline_avg, change, n_recent, n_base in (
        candidates[:MAX_FINDINGS_PER_KIND]
    ):
        dropped = change < 0
        findings.append(
            _finding(
                "cow_yield_drop" if dropped else "cow_yield_rise",
                "high" if abs(change) >= 0.25 else "medium",
                {"animal_number": animal},
                f"Cow {animal}: daily yield {'down' if dropped else 'up'} "
                f"{abs(change) * 100:.1f}% vs her own baseline "
                f"({baseline_avg:.1f} -> {recent_avg:.1f} L/day).",
                {
                    "recent_liters_per_day": round(recent_avg, 1),
                    "baseline_liters_per_day": round(baseline_avg, 1),
                    "change_pct": round(change * 100, 1),
                    "recent_days_measured": n_recent,
                    "baseline_days_measured": n_base,
                },
            )
        )
    return findings


def cow_interval_findings(recent, baseline):
    recent_intervals = _intervals_by_cow(recent)
    baseline_intervals = _intervals_by_cow(baseline)
    candidates = []
    for animal, hours in recent_intervals.items():
        base_hours = baseline_intervals.get(animal, [])
        if len(hours) < MIN_MILKINGS_PER_WINDOW or len(base_hours) < MIN_MILKINGS_PER_WINDOW:
            continue
        recent_avg = _mean(hours)
        baseline_avg = _mean(base_hours)
        change = _change(recent_avg, baseline_avg)
        if change is not None and change >= INTERVAL_RISE_THRESHOLD:
            candidates.append((change, animal, recent_avg, baseline_avg, len(hours)))

    candidates.sort(reverse=True)
    findings = []
    for change, animal, recent_avg, baseline_avg, n_recent in candidates[:MAX_FINDINGS_PER_KIND]:
        findings.append(
            _finding(
                "cow_interval_rise",
                "high" if change >= 0.5 else "medium",
                {"animal_number": animal},
                f"Cow {animal}: visits the robot less often -- average gap up "
                f"{change * 100:.1f}% ({baseline_avg:.1f}h -> {recent_avg:.1f}h).",
                {
                    "recent_avg_interval_hours": round(recent_avg, 1),
                    "baseline_avg_interval_hours": round(baseline_avg, 1),
                    "change_pct": round(change * 100, 1),
                    "recent_intervals_measured": n_recent,
                },
            )
        )
    return findings


def enrich_feed(records, feed_divisor, parse_timestamp):
    """Feed records -> rows with parsed time, kg and consumed flag."""
    rows = []
    for record in records:
        timestamp = parse_timestamp(record.get("timestamp"))
        if timestamp is None:
            continue
        grams = sum(
            record.get(key) or 0
            for key in ("feed_a_raw", "feed_b_raw", "feed_c_raw", "feed_d_raw")
        )
        rows.append(
            {
                "animal_number": record.get("animal_number"),
                "timestamp": timestamp,
                "day": timestamp.date(),
                "kg": grams / feed_divisor,
                "consumed": record.get("all_feed_consumed"),
            }
        )
    rows.sort(key=lambda row: row["timestamp"])
    return rows


def _liters_per_kg(feed_rows, milk_rows):
    """Herd efficiency over days where BOTH feed and milk were measured."""
    feed_by_day = {}
    for row in feed_rows:
        feed_by_day[row["day"]] = feed_by_day.get(row["day"], 0.0) + row["kg"]
    milk_by_day = {}
    for row in milk_rows:
        if row["liters"] is not None:
            milk_by_day[row["day"]] = milk_by_day.get(row["day"], 0.0) + row["liters"]
    overlap = [d for d, kg in feed_by_day.items() if kg > 0 and d in milk_by_day]
    if len(overlap) < FEED_EFFICIENCY_MIN_DAYS:
        return None
    return sum(milk_by_day[d] for d in overlap) / sum(feed_by_day[d] for d in overlap)


def feed_findings(feed_recent, feed_baseline, milk_recent, milk_baseline):
    findings = []

    # Herd feed efficiency: liters of milk per kg of feed.
    recent_eff = _liters_per_kg(feed_recent, milk_recent)
    baseline_eff = _liters_per_kg(feed_baseline, milk_baseline)
    change = _change(recent_eff, baseline_eff)
    if change is not None and abs(change) >= FEED_EFFICIENCY_THRESHOLD:
        findings.append(
            _finding(
                "herd_feed_efficiency_change",
                "high" if abs(change) >= 0.20 else "medium",
                {"herd": True},
                f"Feed efficiency {'down' if change < 0 else 'up'} "
                f"{abs(change) * 100:.1f}% "
                f"({baseline_eff:.2f} -> {recent_eff:.2f} L milk per kg feed).",
                {
                    "recent_liters_per_kg": round(recent_eff, 2),
                    "baseline_liters_per_kg": round(baseline_eff, 2),
                    "change_pct": round(change * 100, 1),
                },
            )
        )

    # Cows leaving feed uneaten -- often one of the first visible illness signs.
    per_cow = {}
    for row in feed_recent:
        stats = per_cow.setdefault(row["animal_number"], {"not_finished": 0, "total": 0})
        stats["total"] += 1
        if row["consumed"] is False:
            stats["not_finished"] += 1
    baseline_per_cow = {}
    for row in feed_baseline:
        stats = baseline_per_cow.setdefault(row["animal_number"], {"not_finished": 0, "total": 0})
        stats["total"] += 1
        if row["consumed"] is False:
            stats["not_finished"] += 1

    candidates = []
    for animal, stats in per_cow.items():
        if stats["total"] == 0:
            continue
        rate = stats["not_finished"] / stats["total"]
        if stats["not_finished"] >= FEED_LEFT_MIN_EVENTS and rate >= FEED_LEFT_RATE_THRESHOLD:
            candidates.append((rate, animal, stats))
    candidates.sort(reverse=True)

    for rate, animal, stats in candidates[:MAX_FINDINGS_PER_KIND]:
        base = baseline_per_cow.get(animal, {"not_finished": 0, "total": 0})
        base_rate = base["not_finished"] / base["total"] if base["total"] else None
        findings.append(
            _finding(
                "cow_feed_left",
                "high" if rate >= 0.5 else "medium",
                {"animal_number": animal},
                f"Cow {animal}: left feed uneaten in {stats['not_finished']} of "
                f"{stats['total']} recent feedings ({rate * 100:.0f}%).",
                {
                    "not_finished": stats["not_finished"],
                    "feedings": stats["total"],
                    "rate_pct": round(rate * 100, 1),
                    "baseline_rate_pct": round(base_rate * 100, 1) if base_rate is not None else None,
                },
            )
        )
    return findings


def production_speed_findings(production_records):
    """Milking speed drop between a cow's two most recent production reports.

    Speed is a stable trait per cow (and the robot is the authoritative source
    for it -- see field_authority in VAULT_SCHEMA.json), so a clear drop
    between reports is worth a look at the udder/robot settings.
    """
    by_cow = {}
    for record in production_records:
        date = record.get("report_date")
        speed = record.get("average_milking_speed_kg_min")
        if isinstance(date, str) and isinstance(speed, (int, float)):
            by_cow.setdefault(record.get("animal_number"), []).append((date, speed))

    candidates = []
    for animal, entries in by_cow.items():
        entries.sort()
        if len(entries) < 2:
            continue
        (previous_date, previous), (latest_date, latest) = entries[-2], entries[-1]
        change = _change(latest, previous)
        if change is not None and change <= -SPEED_DROP_THRESHOLD:
            candidates.append((change, animal, previous, latest, previous_date, latest_date))
    candidates.sort()

    findings = []
    for change, animal, previous, latest, previous_date, latest_date in (
        candidates[:MAX_FINDINGS_PER_KIND]
    ):
        findings.append(
            _finding(
                "cow_speed_drop",
                "high" if change <= -0.25 else "medium",
                {"animal_number": animal},
                f"Cow {animal}: milking speed down {abs(change) * 100:.1f}% "
                f"between reports ({previous:.2f} -> {latest:.2f} kg/min).",
                {
                    "previous_speed_kg_min": previous,
                    "latest_speed_kg_min": latest,
                    "change_pct": round(change * 100, 1),
                    "previous_report": previous_date,
                    "latest_report": latest_date,
                },
            )
        )
    return findings


def build_findings(
    records,
    divisor,
    parse_timestamp,
    recent_days=7,
    baseline_days=28,
    feed_records=None,
    production_records=None,
    feed_divisor=1000,
):
    """Full analysis bundle: context the model needs + the findings themselves."""
    rows = enrich(records, divisor, parse_timestamp)
    recent, baseline, latest = split_windows(rows, recent_days, baseline_days)

    findings = []
    findings.extend(herd_findings(recent, baseline))
    findings.extend(cow_yield_findings(recent, baseline))
    findings.extend(cow_interval_findings(recent, baseline))

    # Cross-dataset findings: feed and production data joined against the same
    # windows (anchored on the newest milking, so all findings describe the
    # same period).
    feed_rows = enrich_feed(feed_records or [], feed_divisor, parse_timestamp)
    if feed_rows and latest:
        recent_start = latest - timedelta(days=recent_days)
        baseline_start = recent_start - timedelta(days=baseline_days)
        feed_recent = [r for r in feed_rows if r["timestamp"] > recent_start]
        feed_baseline = [
            r for r in feed_rows if baseline_start < r["timestamp"] <= recent_start
        ]
        findings.extend(feed_findings(feed_recent, feed_baseline, recent, baseline))
    if production_records:
        findings.extend(production_speed_findings(production_records))

    # The windows are anchored on the newest record, not on today: if the
    # uploader falls behind, "recent" is genuinely older than it sounds.
    # Making the dates explicit lets readers see exactly which period every
    # finding is about (and warn when the data is stale).
    window = None
    if latest:
        recent_start = latest - timedelta(days=recent_days)
        baseline_start = recent_start - timedelta(days=baseline_days)
        window = {
            "data_from": recent_start.date().isoformat(),
            "data_until": latest.date().isoformat(),
            "baseline_from": baseline_start.date().isoformat(),
        }

    return {
        "context": {
            "records_analysed": len(rows),
            "feed_records_analysed": len(feed_rows),
            "production_records_analysed": len(production_records or []),
            "latest_record": latest.isoformat() if latest else None,
            "recent_window_days": recent_days,
            "baseline_window_days": baseline_days,
            "window": window,
            "recent_milkings": len(recent),
            "baseline_milkings": len(baseline),
            "cows_in_recent_window": len({r["animal_number"] for r in recent}),
        },
        "findings": findings,
    }
