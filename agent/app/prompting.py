"""Turns a findings bundle into the prompts the model receives.

Separate from analyst.py on purpose: this is the one place where the farm's own
context enters the pipeline, and where the *grouping* of findings is decided --
and grouping is what determines which patterns the model is able to notice at
all.

Two things happen here that the raw findings list cannot express:

- **Grouping.** analysis.py emits one finding per detection, so a single cow can
  appear three times (less milk, fewer visits, feed left). Sent flat, the model
  writes three unrelated notes and the farmer reads three small problems. Sent
  grouped, it can write one note about one animal going downhill -- which is
  what the data actually says.
- **Domain guidance.** A finding says "yield down 18%". Only a vet or a farmer
  knows the shortlist of causes worth checking. KIND_GUIDANCE carries that
  shortlist, and only for the kinds actually present, so the prompt stays small.

Everything here is wording and framing. No number is produced in this module --
that stays analysis.py's job (see the core rule in the README).
"""

from datetime import datetime

DEFAULT_SYSTEM_PROMPT = """\
You are a dairy herd analyst assisting a cow dairy farmer.

You will receive findings that have ALREADY been calculated from the farm's
data (milking robot, feed distribution and production reports). Your job is to
explain them, not to recalculate them.

Findings are grouped by subject. When one cow has several findings, they are
almost certainly one story, not several -- say what the combination points to,
and treat the combination as more serious than any single signal.

Rules:
- Never invent, alter or recompute numbers. Only use the figures given.
- Do not merely restate the figure: the farmer can already see it. Say what it
  probably means and what to do about it.
- If a finding has an obvious veterinary or management explanation, say so, but
  make clear it is a possibility to check -- you cannot diagnose from yield data
  alone.
- Be concrete and short. A farmer should know what to do after reading it.\
"""

OUTPUT_CONTRACT = """\
Reply with JSON only, in exactly this shape:
{"insights": [{"ref": <the finding's ref number>,
               "title": "<one line in Dutch, max ~90 characters>",
               "body": "<2-4 sentences in Dutch: what is happening and what to check>"}]}
Return one entry per finding you were given, keeping the same ref numbers.\
"""

# One shortlist of plausible causes per finding kind. This is the domain
# knowledge the model cannot derive from a percentage, and the farmer should not
# have to supply. Phrased as things to CHECK -- none of this is a diagnosis.
KIND_GUIDANCE = {
    "cow_yield_drop": (
        "A sustained drop against a cow's own baseline is rarely the robot. "
        "Worth checking: mastitis or a rising cell count, lameness (she walks "
        "to the robot less), heat stress, ketosis in early lactation, or simply "
        "advancing lactation days on an older cow."
    ),
    "cow_yield_rise": (
        "Usually benign -- recovery after illness, or a fresh cow reaching peak "
        "lactation. Report it as reassurance and context, not as a problem."
    ),
    "cow_interval_rise": (
        "Fewer robot visits is often the FIRST visible sign of trouble, days "
        "before yield moves. Lameness is the most common cause. Also worth "
        "checking: whether dominant cows are blocking her at the robot, and "
        "whether her concentrate setting still makes the visit attractive."
    ),
    "cow_feed_left": (
        "Reduced intake usually precedes a yield drop. Worth checking: rumen "
        "fill, body temperature, mouth and claws. A cow leaving concentrate is "
        "worth a physical look even while her milk still looks normal."
    ),
    "cow_speed_drop": (
        "Milking speed is a stable trait per cow, so a clear drop points at the "
        "udder (oedema, teat-end damage, early mastitis) or at liner wear and "
        "vacuum settings on the robot."
    ),
    "cow_multi_signal": (
        "Several independent analyses flagged this same cow. Each signal alone "
        "may sit just over its threshold; together they are the strongest "
        "reason in this whole report to physically go and look at her today. "
        "Lead with that, and name which signals coincide."
    ),
    "cow_recovered": (
        "Good news, write it that way: she dipped and is back at her own "
        "level. If the farmer treated her, this confirms it worked; if not, "
        "she sorted it out herself but deserves half an eye for a recurrence."
    ),
    "herd_yield_change": (
        "Herd-wide movement points at something shared rather than at "
        "individual cows: ration or silage change, weather and heat stress, "
        "water supply, or robot downtime. A shift in the group's lactation "
        "stage explains slow changes, not sudden ones."
    ),
    "herd_failure_rate": (
        "Milkings not finishing normally point at the robot rather than the "
        "cows: teat detection, liner condition, vacuum, or cleaning cycles. "
        "Check whether the failures concentrate on a few cows or are spread "
        "across the herd."
    ),
    "herd_feed_efficiency_change": (
        "Liters per kg of concentrate moving means milk and feed drifted apart. "
        "Worth checking: roughage quality and intake (which this figure does "
        "not see), a feed table change, or heat stress suppressing intake."
    ),
}

FARM_CONTEXT_LABELS = {
    "herd_size": "Cows in the herd",
    "breed": "Breed",
    "robot_count": "Milking robots",
    "housing": "Housing and grazing",
    "typical_yield_liters_per_cow_day": "Typical yield per cow per day (L)",
    "calving_pattern": "Calving pattern",
    "notes": "Other notes from the farmer",
}


def _farm_context_block(farm_context):
    """The farm's own situation, so the model stops reasoning from a generic
    average herd. Unknown keys are passed through rather than dropped -- the
    farmer may know something we never thought to name."""
    if not farm_context:
        return ""
    lines = []
    for key, value in farm_context.items():
        if value in (None, "", [], {}):
            continue
        lines.append(f"- {FARM_CONTEXT_LABELS.get(key, key)}: {value}")
    if not lines:
        return ""
    return "This farm:\n" + "\n".join(lines)


def _guidance_block(kinds_present, extra_guidance):
    """Guidance for the kinds in THIS batch only, so the prompt does not carry
    advice about analyses that produced nothing."""
    guidance = {**KIND_GUIDANCE, **(extra_guidance or {})}
    lines = [f"- {kind}: {guidance[kind]}" for kind in sorted(kinds_present) if kind in guidance]
    if not lines:
        return ""
    return (
        "Background on the finding types in this batch (possibilities to check, "
        "never conclusions):\n" + "\n".join(lines)
    )


def build_system_prompt(settings, kinds_present):
    llm_settings = settings.get("llm", {})
    sections = [llm_settings.get("system_prompt") or DEFAULT_SYSTEM_PROMPT]
    for block in (
        _farm_context_block(settings.get("farm_context")),
        _guidance_block(kinds_present, llm_settings.get("kind_guidance")),
    ):
        if block:
            sections.append(block)
    # The output contract goes last, closest to generation, where instruction
    # following is most reliable.
    sections.append(OUTPUT_CONTRACT)
    return "\n\n".join(sections)


def group_findings(findings):
    """Group findings by the cow (or the herd) they are about.

    `ref` stays the index into the ORIGINAL findings list, because that is what
    analyst.py maps the model's reply back onto -- grouping and batching must
    never renumber. Cows with the most signals come first: they are both the
    most urgent and the ones a farmer scanning a list is most likely to miss.
    """
    groups = {}
    for index, finding in enumerate(findings):
        scope = finding["scope"]
        animal = scope.get("animal_number")
        key = ("cow", animal) if animal is not None else ("herd", None)
        group = groups.setdefault(
            key,
            {
                "subject": f"Cow {animal}" if animal is not None else "Whole herd",
                "findings": [],
            },
        )
        group["findings"].append(
            {
                "ref": index,
                "kind": finding["kind"],
                "severity": finding["severity"],
                "measured": finding["summary"],
                "figures": finding["metrics"],
            }
        )
    ordered = sorted(
        groups.items(),
        key=lambda item: (item[0][0] != "herd", -len(item[1]["findings"]), str(item[0][1])),
    )
    return [group for _key, group in ordered]


def batch_groups(groups, max_findings_per_request):
    """Split groups into request-sized batches, never splitting a group.

    A cow's signals have to stay in one request or the model cannot see that
    they belong together -- which is the whole point of grouping. Batching at
    all is what keeps quality stable as the herd grows: asking one call to word
    forty findings degrades every one of them, and a single malformed reply
    would cost the wording of the entire run instead of one batch.
    """
    if max_findings_per_request <= 0:
        return [groups] if groups else []
    batches = []
    current, current_size = [], 0
    for group in groups:
        size = len(group["findings"])
        if current and current_size + size > max_findings_per_request:
            batches.append(current)
            current, current_size = [], 0
        current.append(group)
        current_size += size
    if current:
        batches.append(current)
    return batches


def _data_lag_note(context, now=None):
    """The windows are anchored on the newest record, not on today. Without
    saying so, the model writes 'this past week' about data that may be weeks
    old if the uploader fell behind."""
    latest = context.get("latest_record")
    if not latest:
        return None
    try:
        latest_date = datetime.fromisoformat(latest)
    except ValueError:
        return None
    days = ((now or datetime.now()) - latest_date).days
    if days <= 1:
        return None
    return (
        f"NOTE: the newest measurement in the vault is {days} days old. The "
        "windows below are anchored on that measurement, not on today, so "
        "describe the period by its dates rather than as 'this week'."
    )


def build_user_prompt(context, groups, now=None):
    import json  # local: only the prompt text needs it

    sections = ["Context of the analysis:\n" + json.dumps(context, indent=2)]
    lag = _data_lag_note(context, now)
    if lag:
        sections.append(lag)
    sections.append(
        "Findings calculated from the data, grouped by subject:\n"
        + json.dumps(groups, indent=2)
    )
    return "\n\n".join(sections)


def kinds_in(groups):
    return {f["kind"] for group in groups for f in group["findings"]}
