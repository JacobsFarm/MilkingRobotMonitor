// ---------------------------------------------------------------------------
// Server-side read-model en aggregatielaag.
//
// Rolverdeling in dit systeem:
//   - eVault           = bron van waarheid (eigendom, sync tussen programma's)
//   - vault.js         = transport + cache (beschermt de rate-limited eVault)
//   - deze module      = REKENWERK: filtert en aggregeert de records op de
//                        server en levert compacte, kant-en-klare cijfers
//   - de browser       = alleen presentatie (grafieken tekenen, labels)
//
// De browser krijgt zo enkele KB aan aggregaten in plaats van de volledige
// recordset (tienduizenden records), en elke berekening gebeurt precies één
// keer per unieke (dataset, filter)-combinatie dankzij de memo.
//
// Uitbreiden met een nieuwe dataset: schrijf naast getMilkingStats een eigen
// get<Naam>Stats met een eigen buildstap, en geef die een eigen API-route.
// Koppelen van datasets (bv. gezondheid × melkgift) gebeurt ook hier: beide
// collecties ophalen en server-side joinen op animal_number + tijd.
// ---------------------------------------------------------------------------

import { createHash } from 'node:crypto';
import { fetchAll } from './vault.js';

// Intervallen groter dan dit aantal uren zijn gaten tussen meetsessies
// (losse melkcontrole-exports) en tellen niet mee in de gemiddelden.
export const MAX_INTERVAL_HOURS = 24;
export const INTERVAL_BIN_HOURS = 2;
const RECENT_ROWS = 30;
const TOP_COWS = 15;
const MEMO_LIMIT = 40;

// Verrijkte dataset per records-array. De array uit de vault-cache is stabiel
// tussen verversingen, dus een WeakMap geeft automatische invalidatie zodra de
// cache een nieuwe versie plaatst.
const datasetCache = new WeakMap();
// (datasetSignature + filters) -> kant-en-klare stats.
const statsMemo = new Map();

// ---- basishelpers ----------------------------------------------------------

function sum(values) {
    return values.reduce((acc, v) => acc + (v ?? 0), 0);
}

function mean(values) {
    return values.length ? sum(values) / values.length : null;
}

function litersOf(record, divisor) {
    if (typeof record.yield_raw === 'number') {
        return record.yield_raw / divisor;
    }
    if (typeof record.yield_liters === 'number') {
        return record.yield_liters;
    }
    return null;
}

// ISO-8601 weeknummer als sorteerbare sleutel, bv. "2025-W14".
function isoWeekKey(date) {
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

// ---- dataset (verrijkte rijen + filteropties + signature) ------------------

function enrichAll(records, divisor) {
    const rows = [];
    for (const record of records) {
        const date = new Date(record.timestamp);
        if (Number.isNaN(date.getTime())) {
            continue;
        }
        rows.push({
            ...record,
            date,
            liters: litersOf(record, divisor),
            hour: date.getHours(),
            dayIdx: (date.getDay() + 6) % 7,
            dayKey: record.timestamp.slice(0, 10),
            monthKey: record.timestamp.slice(0, 7),
            weekKey: isoWeekKey(date)
        });
    }
    rows.sort((a, b) => a.date - b.date);
    return rows;
}

function datasetOf(records, divisor) {
    let dataset = datasetCache.get(records);
    if (!dataset || dataset.divisor !== divisor) {
        const rows = enrichAll(records, divisor);
        const signature = createHash('sha1')
            .update(rows.map((r) => r.id).sort().join('|'))
            .digest('hex');
        const options = {
            cows: [...new Set(rows.map((r) => String(r.animal_number)))].sort(
                (a, b) => Number(a) - Number(b)
            ),
            months: [...new Set(rows.map((r) => r.monthKey))].sort(),
            weeks: [...new Set(rows.map((r) => r.weekKey))].sort()
        };
        dataset = { rows, signature, options, divisor };
        datasetCache.set(records, dataset);
    }
    return dataset;
}

// ---- filters ----------------------------------------------------------------

export function normalizeFilters(searchParams) {
    const list = (name) =>
        (searchParams.get(name) ?? '')
            .split(',')
            .map((v) => v.trim())
            .filter(Boolean);
    let from = searchParams.get('from') ?? '';
    let to = searchParams.get('to') ?? '';
    // Verwissel van/tot als ze omgekeerd zijn ingevuld.
    if (from && to && from > to) {
        [from, to] = [to, from];
    }
    return { cows: list('cows'), months: list('months'), weeks: list('weeks'), from, to };
}

function filterKeyOf(filters) {
    const part = (values) => [...values].sort().join(',');
    return `${part(filters.cows)}|${part(filters.months)}|${part(filters.weeks)}|${filters.from}|${filters.to}`;
}

function applyFilters(rows, filters) {
    const cowSet = new Set(filters.cows);
    const monthSet = new Set(filters.months);
    const weekSet = new Set(filters.weeks);
    return rows.filter(
        (r) =>
            (cowSet.size === 0 || cowSet.has(String(r.animal_number))) &&
            (monthSet.size === 0 || monthSet.has(r.monthKey)) &&
            (weekSet.size === 0 || weekSet.has(r.weekKey)) &&
            (!filters.from || r.dayKey >= filters.from) &&
            (!filters.to || r.dayKey <= filters.to)
    );
}

// ---- melkstatistieken --------------------------------------------------------

// Tijd tussen opeenvolgende melkingen van dezelfde koe, in uren.
function computeIntervals(rows, maxHours = MAX_INTERVAL_HOURS) {
    const byCow = new Map();
    for (const record of rows) {
        const key = String(record.animal_number);
        if (!byCow.has(key)) {
            byCow.set(key, []);
        }
        byCow.get(key).push(record);
    }
    const intervals = [];
    const byRecordId = new Map();
    for (const [animal, list] of byCow) {
        // rows is al chronologisch gesorteerd, dus list ook.
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

function buildMilkingStats(dataset, filters) {
    const rows = applyFilters(dataset.rows, filters);
    const { intervals, byRecordId } = computeIntervals(rows);

    // Heatmaps: 7x24 (dag van de week x uur).
    const heatCount = Array.from({ length: 7 }, () => Array(24).fill(0));
    const heatLiters = Array.from({ length: 7 }, () => Array(24).fill(0));
    // Uur- en weekdaggroepen.
    const hourCount = Array(24).fill(0);
    const hourLiters = Array(24).fill(0);
    const weekdayCount = Array(7).fill(0);
    const weekdayLiters = Array(7).fill(0);
    // Groeperingen per dag / week / status; unieke (koe, dag) voor frequentie.
    const byDay = new Map();
    const byWeek = new Map();
    const statusCounts = new Map();
    const cowDays = new Set();
    const cows = new Set();

    for (const r of rows) {
        const liters = r.liters ?? 0;
        heatCount[r.dayIdx][r.hour] += 1;
        heatLiters[r.dayIdx][r.hour] += liters;
        hourCount[r.hour] += 1;
        hourLiters[r.hour] += liters;
        weekdayCount[r.dayIdx] += 1;
        weekdayLiters[r.dayIdx] += liters;
        if (!byDay.has(r.dayKey)) {
            byDay.set(r.dayKey, { liters: 0, count: 0 });
        }
        const day = byDay.get(r.dayKey);
        day.liters += liters;
        day.count += 1;
        if (!byWeek.has(r.weekKey)) {
            byWeek.set(r.weekKey, { liters: 0, count: 0 });
        }
        const week = byWeek.get(r.weekKey);
        week.liters += liters;
        week.count += 1;
        statusCounts.set(r.status, (statusCounts.get(r.status) ?? 0) + 1);
        cowDays.add(`${r.animal_number}|${r.dayKey}`);
        cows.add(String(r.animal_number));
    }

    const totalLiters = sum(rows.map((r) => r.liters));
    const cumulative = [];
    for (const liters of hourLiters) {
        cumulative.push((cumulative.length ? cumulative[cumulative.length - 1] : 0) + liters);
    }

    // Verdeling van intervallen in bakken van INTERVAL_BIN_HOURS uur.
    const bins = Array(MAX_INTERVAL_HOURS / INTERVAL_BIN_HOURS).fill(0);
    for (const { hours } of intervals) {
        const index = Math.min(bins.length - 1, Math.floor(hours / INTERVAL_BIN_HOURS));
        bins[index] += 1;
    }

    // Ranglijst: langste gemiddelde tijd tussen melkingen per koe.
    const intervalsByCow = new Map();
    for (const { animal, hours } of intervals) {
        if (!intervalsByCow.has(animal)) {
            intervalsByCow.set(animal, []);
        }
        intervalsByCow.get(animal).push(hours);
    }
    const perCowTop = [...intervalsByCow.entries()]
        .map(([animal, list]) => ({ animal, avg: mean(list), n: list.length }))
        .filter((e) => e.n >= 2)
        .sort((a, b) => b.avg - a.avg)
        .slice(0, TOP_COWS);

    const dayKeys = [...byDay.keys()].sort();
    const weekKeys = [...byWeek.keys()].sort();

    return {
        filtered: { count: rows.length, of: dataset.rows.length },
        totals: {
            count: rows.length,
            cowCount: cows.size,
            totalLiters,
            avgPerMilking: rows.length ? totalLiters / rows.length : null,
            milkingsPerCowDay: cowDays.size ? rows.length / cowDays.size : null,
            avgIntervalHours: mean(intervals.map((i) => i.hours))
        },
        heatmaps: {
            count: heatCount.map((row) => row.map((count) => (count > 0 ? count : null))),
            avgLiters: heatCount.map((row, d) =>
                row.map((count, h) => (count > 0 ? heatLiters[d][h] / count : null))
            )
        },
        hourly: {
            count: hourCount,
            totalLiters: hourLiters,
            avgPerMilking: hourCount.map((count, h) => (count ? hourLiters[h] / count : null)),
            cumulative
        },
        weekday: { count: weekdayCount, totalLiters: weekdayLiters },
        intervals: {
            bins,
            binHours: INTERVAL_BIN_HOURS,
            maxHours: MAX_INTERVAL_HOURS,
            perCowTop
        },
        dailyTrend: {
            labels: dayKeys,
            liters: dayKeys.map((d) => byDay.get(d).liters),
            counts: dayKeys.map((d) => byDay.get(d).count)
        },
        status: [...statusCounts.entries()]
            .sort((a, b) => b[1] - a[1])
            .map(([status, count]) => ({ status, count })),
        weekly: {
            labels: weekKeys,
            counts: weekKeys.map((k) => byWeek.get(k).count),
            liters: weekKeys.map((k) => byWeek.get(k).liters)
        },
        recent: [...rows]
            .slice(-RECENT_ROWS)
            .reverse()
            .map((r) => ({
                id: r.id,
                timestamp: r.timestamp,
                animal_number: r.animal_number,
                liters: r.liters,
                status: r.status,
                intervalHours: byRecordId.get(r.id) ?? null
            }))
    };
}

// ---- publieke API ------------------------------------------------------------

export async function getMilkingStats(settings, filters) {
    const basePath = settings.base_path ?? 'milking_controle_data';
    const records = await fetchAll(settings, basePath);
    const dataset = datasetOf(records, settings.yield_divisor ?? 1000);

    // De signature dekt dataset én filters: zelfde signature = gegarandeerd
    // zelfde statistieken, dus de client kan met `sig` een lege "unchanged"
    // respons krijgen in plaats van dezelfde cijfers opnieuw.
    const filterKey = filterKeyOf(filters);
    const signature = createHash('sha1')
        .update(`${dataset.signature}|${filterKey}`)
        .digest('hex');

    let stats = statsMemo.get(signature);
    if (!stats) {
        stats = buildMilkingStats(dataset, filters);
        stats.options = dataset.options;
        statsMemo.set(signature, stats);
        while (statsMemo.size > MEMO_LIMIT) {
            statsMemo.delete(statsMemo.keys().next().value);
        }
    }
    return { signature, stats };
}
