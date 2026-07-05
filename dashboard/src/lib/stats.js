// Pure helpers voor het berekenen van statistieken op melkingsrecords.

// Intervallen groter dan dit aantal uren worden beschouwd als een gat tussen
// meetsessies (de melkcontrole-exports) en tellen niet mee in de gemiddelden.
export const MAX_INTERVAL_HOURS = 24;

export const DAY_LABELS = ['Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za', 'Zo'];

export function litersOf(record, divisor = 1000) {
    if (typeof record.yield_raw === 'number') {
        return record.yield_raw / divisor;
    }
    if (typeof record.yield_liters === 'number') {
        return record.yield_liters;
    }
    return null;
}

// ISO-8601 weeknummer als sorteerbare sleutel, bv. "2025-W14".
export function isoWeekKey(date) {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    const dayNum = (d.getUTCDay() + 6) % 7;
    d.setUTCDate(d.getUTCDate() - dayNum + 3);
    const firstThursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
    const week =
        1 +
        Math.round(
            ((d - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7
        );
    return `${d.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
}

export function enrich(record, divisor) {
    const date = new Date(record.timestamp);
    return {
        ...record,
        date,
        liters: litersOf(record, divisor),
        hour: date.getHours(),
        dayIdx: (date.getDay() + 6) % 7,
        dayKey: record.timestamp.slice(0, 10),
        monthKey: record.timestamp.slice(0, 7),
        weekKey: isoWeekKey(date)
    };
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

// Tijd tussen opeenvolgende melkingen van dezelfde koe, in uren.
// Retourneert { intervals, byRecordId } zodat de tabel per melking het
// interval sinds de vorige melking kan tonen.
export function computeIntervals(records, maxHours = MAX_INTERVAL_HOURS) {
    const byCow = new Map();
    for (const record of records) {
        const key = String(record.animal_number);
        if (!byCow.has(key)) {
            byCow.set(key, []);
        }
        byCow.get(key).push(record);
    }
    const intervals = [];
    const byRecordId = new Map();
    for (const [animal, list] of byCow) {
        list.sort((a, b) => a.date - b.date);
        for (let i = 1; i < list.length; i++) {
            const hours = (list[i].date - list[i - 1].date) / 3600000;
            if (hours > 0 && hours <= maxHours) {
                intervals.push({ animal, hours });
                byRecordId.set(list[i].id, hours);
            }
        }
    }
    return { intervals, byRecordId };
}

export function sum(values) {
    return values.reduce((acc, v) => acc + (v ?? 0), 0);
}

export function mean(values) {
    return values.length ? sum(values) / values.length : null;
}

// 7x24 matrices (dag van de week x uur) met aantal melkingen en gemiddelde liters.
export function buildHeatmaps(records) {
    const counts = Array.from({ length: 7 }, () => Array(24).fill(0));
    const liters = Array.from({ length: 7 }, () => Array(24).fill(0));
    for (const record of records) {
        counts[record.dayIdx][record.hour] += 1;
        liters[record.dayIdx][record.hour] += record.liters ?? 0;
    }
    const avgLiters = counts.map((row, d) =>
        row.map((count, h) => (count > 0 ? liters[d][h] / count : null))
    );
    const countMatrix = counts.map((row) => row.map((count) => (count > 0 ? count : null)));
    return { countMatrix, avgLiters };
}

export function fmt(value, decimals = 1) {
    if (value == null || Number.isNaN(value)) {
        return '–';
    }
    return value.toLocaleString('nl-NL', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}
