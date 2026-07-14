// Presentatie-helpers: labels en getalnotatie voor de browser.
// Rekenwerk hoort hier NIET thuis — dat doet de server (lib/server/aggregate.js).

export const DAY_LABELS = ['Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za', 'Zo'];

export function fmt(value, decimals = 1) {
    if (value == null || Number.isNaN(value)) {
        return '–';
    }
    return value.toLocaleString('nl-NL', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

export function monthLabel(monthKey) {
    const date = new Date(`${monthKey}-01T00:00:00`);
    const label = date.toLocaleDateString('nl-NL', { month: 'long', year: 'numeric' });
    return label.charAt(0).toUpperCase() + label.slice(1);
}

// Maandag van een ISO-week, bv. "2025-W14" -> Date van 31 maart 2025.
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
    const short = (d) => d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' });
    return `Week ${Number(weekKey.split('-W')[1])} · ${short(start)} – ${short(end)} ${end.getFullYear()}`;
}
