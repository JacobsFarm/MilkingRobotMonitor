// Presentation helpers: labels and number formatting for the browser.
// Calculations do NOT belong here — the server does those (lib/server/aggregate.js).

export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function fmt(value, decimals = 1) {
    if (value == null || Number.isNaN(value)) {
        return '–';
    }
    return value.toLocaleString('en-GB', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

export function monthLabel(monthKey) {
    const date = new Date(`${monthKey}-01T00:00:00`);
    const label = date.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    return label.charAt(0).toUpperCase() + label.slice(1);
}

// Monday of an ISO week, e.g. "2025-W14" -> Date of 31 March 2025.
export function isoWeekStart(weekKey) {
    const [yearPart, weekPart] = weekKey.split('-W');
    const year = Number(yearPart);
    const week = Number(weekPart);
    const jan4 = new Date(year, 0, 4);
    const mondayWeek1 = new Date(year, 0, 4 - ((jan4.getDay() + 6) % 7));
    mondayWeek1.setDate(mondayWeek1.getDate() + (week - 1) * 7);
    return mondayWeek1;
}

export function weekLabel(weekKey) {
    const start = isoWeekStart(weekKey);
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    const short = (d) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
    return `Week ${Number(weekKey.split('-W')[1])} · ${short(start)} – ${short(end)} ${end.getFullYear()}`;
}
