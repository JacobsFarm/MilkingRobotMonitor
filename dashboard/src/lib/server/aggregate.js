// ---------------------------------------------------------------------------
// Server-side read model and aggregation layer.
//
// Division of roles in this system:
//   - eVault           = source of truth (ownership, sync between programs)
//   - vault.js         = transport + cache (protects the rate-limited eVault)
//   - this module      = THE CALCULATIONS: filters and aggregates the records
//                        on the server and returns compact, ready-made figures
//   - the browser      = presentation only (drawing charts, labels)
//
// The browser gets a few KB of aggregates instead of the full record set (tens
// of thousands of records), and every calculation happens exactly once per
// unique (dataset, filter) combination thanks to the memo.
//
// Joining datasets also happens here, server-side: feed distribution and
// production snapshots are joined to the milkings on animal_number + day (see
// buildFeedStats/buildProductionStats). The browser only sees the result.
// Which source is leading per quantity is in VAULT_SCHEMA.json under
// field_authority — milking speed comes from the robot (authoritative);
// lactation data here also comes from the robot until CRV (mpr_uitslag) is
// uploaded, after which that source becomes first choice here.
// ---------------------------------------------------------------------------

import { createHash } from 'node:crypto';
import { fetchAll } from './vault.js';

// Intervals longer than this many hours are gaps between measurement sessions
// (separate milking control exports) and do not count towards the averages.
export const MAX_INTERVAL_HOURS = 24;
export const INTERVAL_BIN_HOURS = 2;
const RECENT_ROWS = 30;
const TOP_COWS = 15;
const MEMO_LIMIT = 40;

// Enriched dataset per records array. The array from the vault cache is stable
// between refreshes, so a WeakMap gives automatic invalidation as soon as the
// cache stores a new version.
const datasetCache = new WeakMap();
const feedCache = new WeakMap();
const productionCache = new WeakMap();
// (datasetSignature + filters) -> ready-made stats.
const statsMemo = new Map();

// ---- basic helpers ---------------------------------------------------------

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

// ISO-8601 week number as a sortable key, e.g. "2025-W14".
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

// ---- dataset (enriched rows + filter options + signature) ------------------

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

// ---- feed distribution (feed_distribution_data) ----------------------------

// Enriches feed records into rows with the same filter keys as milkings
// (animal_number, dayKey, monthKey, weekKey), so applyFilters can filter them
// unchanged. kg = sum of the four feed types / feed_divisor.
function feedDatasetOf(records, feedDivisor) {
    let dataset = feedCache.get(records);
    if (!dataset || dataset.feedDivisor !== feedDivisor) {
        const rows = [];
        for (const record of records) {
            const date = new Date(record.timestamp);
            if (Number.isNaN(date.getTime())) {
                continue;
            }
            const grams =
                (record.feed_a_raw ?? 0) +
                (record.feed_b_raw ?? 0) +
                (record.feed_c_raw ?? 0) +
                (record.feed_d_raw ?? 0);
            rows.push({
                id: record.id,
                animal_number: record.animal_number,
                date,
                kg: grams / feedDivisor,
                consumed: record.all_feed_consumed ?? null,
                dayKey: record.timestamp.slice(0, 10),
                monthKey: record.timestamp.slice(0, 7),
                weekKey: isoWeekKey(date)
            });
        }
        rows.sort((a, b) => a.date - b.date);
        const signature = createHash('sha1')
            .update(rows.map((r) => r.id).sort().join('|'))
            .digest('hex');
        dataset = { rows, signature, feedDivisor };
        feedCache.set(records, dataset);
    }
    return dataset;
}

// Feed × milk: joined on day (and, through the shared filters, on cow/period).
function buildFeedStats(feedRows, milkDaily) {
    if (!feedRows.length) {
        return { available: false };
    }
    const byDay = new Map();
    const byCow = new Map();
    for (const r of feedRows) {
        if (!byDay.has(r.dayKey)) {
            byDay.set(r.dayKey, { kg: 0, feedings: 0, notFinished: 0 });
        }
        const day = byDay.get(r.dayKey);
        day.kg += r.kg;
        day.feedings += 1;
        if (r.consumed === false) {
            day.notFinished += 1;
        }
        const cowKey = String(r.animal_number);
        if (!byCow.has(cowKey)) {
            byCow.set(cowKey, { notFinished: 0, total: 0 });
        }
        const cow = byCow.get(cowKey);
        cow.total += 1;
        if (r.consumed === false) {
            cow.notFinished += 1;
        }
    }

    // Milk liters per day from the already computed daily trend of the milkings.
    const milkByDay = new Map(milkDaily.labels.map((label, i) => [label, milkDaily.liters[i]]));
    const labels = [...byDay.keys()].sort();
    const feedKg = labels.map((d) => byDay.get(d).kg);
    const milkLiters = labels.map((d) => milkByDay.get(d) ?? null);
    const efficiency = labels.map((d, i) =>
        feedKg[i] > 0 && milkLiters[i] != null ? milkLiters[i] / feedKg[i] : null
    );
    const leftoverPct = labels.map((d) => {
        const day = byDay.get(d);
        return day.feedings ? (day.notFinished / day.feedings) * 100 : null;
    });

    // Overall efficiency only over days where both datasets have data.
    let overlapMilk = 0;
    let overlapFeed = 0;
    labels.forEach((d, i) => {
        if (feedKg[i] > 0 && milkLiters[i] != null) {
            overlapMilk += milkLiters[i];
            overlapFeed += feedKg[i];
        }
    });

    const topLeftovers = [...byCow.entries()]
        .filter(([, c]) => c.notFinished > 0)
        .map(([animal, c]) => ({ animal, notFinished: c.notFinished, total: c.total }))
        .sort((a, b) => b.notFinished - a.notFinished || b.total - a.total)
        .slice(0, 10);

    return {
        available: true,
        filtered: { count: feedRows.length },
        totals: {
            totalKg: sum(feedKg),
            litersPerKg: overlapFeed > 0 ? overlapMilk / overlapFeed : null,
            overlapDays: labels.filter((d, i) => feedKg[i] > 0 && milkLiters[i] != null).length
        },
        dailyTrend: { labels, feedKg, milkLiters, efficiency, leftoverPct },
        leftovers: { topCows: topLeftovers }
    };
}

// ---- production snapshots (milking_production_data) ------------------------

function productionDatasetOf(records) {
    let dataset = productionCache.get(records);
    if (!dataset) {
        const rows = [];
        for (const record of records) {
            if (typeof record.report_date !== 'string') {
                continue;
            }
            const date = new Date(record.report_date);
            if (Number.isNaN(date.getTime())) {
                continue;
            }
            rows.push({
                id: record.id,
                animal_number: record.animal_number,
                dayKey: record.report_date,
                monthKey: record.report_date.slice(0, 7),
                weekKey: isoWeekKey(date),
                speed: record.average_milking_speed_kg_min ?? null,
                milk24: record.milk_24h_kg ?? null,
                milk10dAvg: record.milk_10d_avg_kg ?? null,
                lactationDays: record.lactation_days ?? null,
                lactationNumber: record.lactation_number ?? null
            });
        }
        rows.sort((a, b) => (a.dayKey < b.dayKey ? -1 : 1));
        const signature = createHash('sha1')
            .update(rows.map((r) => r.id).sort().join('|'))
            .digest('hex');
        dataset = { rows, signature };
        productionCache.set(records, dataset);
    }
    return dataset;
}

function buildProductionStats(productionRows) {
    if (!productionRows.length) {
        return { available: false };
    }
    const reportDates = [...new Set(productionRows.map((r) => r.dayKey))].sort();
    const latestDate = reportDates[reportDates.length - 1];
    const latest = productionRows.filter((r) => r.dayKey === latestDate);

    // Scatter points from the newest report. Milking speed is the authoritative
    // source here (the robot measures it itself, see field_authority);
    // lactation_days is the robot's registration and will later be replaced by CRV.
    const points = latest.map((r) => ({
        animal: String(r.animal_number),
        speed: r.speed,
        milk24: r.milk24,
        lactationDays: r.lactationDays,
        lactationNumber: r.lactationNumber
    }));

    return {
        available: true,
        filtered: { count: productionRows.length },
        reportDates,
        latestDate,
        latest: {
            cowCount: latest.length,
            avgSpeed: mean(latest.map((r) => r.speed).filter((v) => v != null)),
            avgMilk24: mean(latest.map((r) => r.milk24).filter((v) => v != null))
        },
        points
    };
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
    // Swap from/to if they were entered the wrong way round.
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

// ---- milking statistics ------------------------------------------------------

// Time between consecutive milkings of the same cow, in hours.
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
        // rows is already sorted chronologically, so list is too.
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

    // Heatmaps: 7x24 (day of the week x hour).
    const heatCount = Array.from({ length: 7 }, () => Array(24).fill(0));
    const heatLiters = Array.from({ length: 7 }, () => Array(24).fill(0));
    // Hour and weekday groups.
    const hourCount = Array(24).fill(0);
    const hourLiters = Array(24).fill(0);
    const weekdayCount = Array(7).fill(0);
    const weekdayLiters = Array(7).fill(0);
    // Groupings per day / week / status; unique (cow, day) for frequency.
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

    // Distribution of intervals into bins of INTERVAL_BIN_HOURS hours.
    const bins = Array(MAX_INTERVAL_HOURS / INTERVAL_BIN_HOURS).fill(0);
    for (const { hours } of intervals) {
        const index = Math.min(bins.length - 1, Math.floor(hours / INTERVAL_BIN_HOURS));
        bins[index] += 1;
    }

    // Ranking: longest average time between milkings per cow.
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

// ---- public API --------------------------------------------------------------

export async function getMilkingStats(settings, filters) {
    const basePath = settings.base_path ?? 'milking_controle_data';
    const feedPath = settings.feed_path ?? 'feed_distribution_data';
    const productionPath = settings.production_path ?? 'milking_production_data';

    const [records, feedRecords, productionRecords] = await Promise.all([
        fetchAll(settings, basePath),
        fetchAll(settings, feedPath),
        fetchAll(settings, productionPath)
    ]);
    const dataset = datasetOf(records, settings.yield_divisor ?? 1000);
    const feedDataset = feedDatasetOf(feedRecords, settings.feed_divisor ?? 1000);
    const productionDataset = productionDatasetOf(productionRecords);

    // The signature covers ALL datasets AND the filters: same signature =
    // guaranteed the same statistics, so with `sig` the client can get an empty
    // "unchanged" response instead of the same figures all over again.
    const filterKey = filterKeyOf(filters);
    const signature = createHash('sha1')
        .update(
            `${dataset.signature}|${feedDataset.signature}|${productionDataset.signature}|${filterKey}`
        )
        .digest('hex');

    let stats = statsMemo.get(signature);
    if (!stats) {
        stats = buildMilkingStats(dataset, filters);
        stats.options = dataset.options;
        // The same filters apply to all datasets: the feed and production
        // figures therefore refer to exactly the same cows and period as the
        // milk charts next to them.
        stats.feed = buildFeedStats(applyFilters(feedDataset.rows, filters), stats.dailyTrend);
        stats.production = buildProductionStats(applyFilters(productionDataset.rows, filters));
        statsMemo.set(signature, stats);
        while (statsMemo.size > MEMO_LIMIT) {
            statsMemo.delete(statsMemo.keys().next().value);
        }
    }
    return { signature, stats };
}
