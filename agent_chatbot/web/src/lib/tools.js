// Presentation for the tool catalogue in app/tools.py.
//
// The terminal prints `[compare_windows(metric=yield, ...)]`. The same
// transparency has to survive here: a farmer should be able to see that a
// number came out of a named computation, without having to read Python.

export const TOOL_LABELS = {
    describe_vault: 'Reading what is in the vault',
    query_records: 'Filtering and aggregating records',
    lactation_cohort: 'Building the lactation cohort',
    daily_yield: 'Computing production per day',
    compare_windows: 'Comparing two periods',
    cow_profile: 'Collecting one cow’s full profile',
    list_insights: 'Reading the standing analysis'
};

export function toolLabel(name) {
    return TOOL_LABELS[name] ?? name;
}

/** `{metric: 'yield', direction: 'down'}` -> `metric=yield, direction=down`,
 *  matching run.py's printout. Long values are clipped: a tool call is a hint
 *  about what ran, not a payload dump. */
export function formatArguments(args) {
    if (!args || typeof args !== 'object') return '';
    return Object.entries(args)
        .map(([key, value]) => {
            const text = Array.isArray(value) ? value.join('|') : String(value ?? '');
            return `${key}=${text.length > 40 ? `${text.slice(0, 39)}…` : text}`;
        })
        .join(', ');
}
