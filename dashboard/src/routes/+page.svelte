<script>
    import { onDestroy, onMount } from 'svelte';
    import ChartBox from '$lib/components/ChartBox.svelte';
    import Heatmap from '$lib/components/Heatmap.svelte';
    import MultiSelect from '$lib/components/MultiSelect.svelte';
    import {
        DAY_LABELS,
        MAX_INTERVAL_HOURS,
        buildHeatmaps,
        computeIntervals,
        enrich,
        fmt,
        mean,
        monthLabel,
        sum,
        weekLabel
    } from '$lib/stats.js';

    const STATUS_STYLES = {
        OK: { color: '#2e8b57', label: 'Geslaagd' },
        '!': { color: '#e69500', label: 'Mislukt' },
        '#': { color: '#c0392b', label: 'Fout' }
    };

    let records = {};
    let refreshMs = 30000;
    let yieldDivisor = 1000;
    let timer;
    let loadError = '';

    // Ophaal-status voor de "slimme" poll: we sturen de laatst bekende
    // signature mee zodat de server niets terugstuurt als er niets veranderd is.
    let lastSignature = '';
    let lastUpdated = null;
    let lastChecked = null;
    let loading = false;

    function clockLabel(date) {
        return date
            ? date.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            : '–';
    }

    // Filters
    let selectedCows = [];
    let selectedMonths = [];
    let selectedWeeks = [];
    let dateFrom = '';
    let dateTo = '';

    function statusStyle(status) {
        return STATUS_STYLES[status] ?? STATUS_STYLES['#'];
    }

    function resetFilters() {
        selectedCows = [];
        selectedMonths = [];
        selectedWeeks = [];
        dateFrom = '';
        dateTo = '';
    }

    async function load() {
        if (loading) {
            return;
        }
        loading = true;
        try {
            const query = lastSignature ? `?sig=${encodeURIComponent(lastSignature)}` : '';
            const response = await fetch(`/api/records${query}`);
            if (!response.ok) {
                loadError = `Vault request failed (${response.status})`;
                return;
            }
            const payload = await response.json();
            refreshMs = payload.refresh_ms ?? refreshMs;
            yieldDivisor = payload.yield_divisor ?? yieldDivisor;
            lastChecked = new Date();
            lastSignature = payload.signature ?? lastSignature;
            if (!payload.unchanged) {
                const next = { ...records };
                for (const record of payload.records) {
                    next[record.id] = record;
                }
                records = next;
                lastUpdated = new Date();
            }
            loadError = '';
        } catch (error) {
            loadError = String(error);
        } finally {
            loading = false;
        }
    }

    onMount(async () => {
        await load();
        timer = setInterval(load, refreshMs);
    });

    onDestroy(() => {
        if (timer) {
            clearInterval(timer);
        }
    });

    // ---- Basisdata ----
    $: enriched = Object.values(records)
        .map((record) => enrich(record, yieldDivisor))
        .filter((record) => !Number.isNaN(record.date.getTime()))
        .sort((a, b) => a.date - b.date);

    $: cowOptions = [...new Set(enriched.map((r) => String(r.animal_number)))]
        .sort((a, b) => Number(a) - Number(b))
        .map((cow) => ({ value: cow, label: `Koe ${cow}` }));
    $: monthOptions = [...new Set(enriched.map((r) => r.monthKey))]
        .sort()
        .map((month) => ({ value: month, label: monthLabel(month) }));
    $: weekOptions = [...new Set(enriched.map((r) => r.weekKey))]
        .sort()
        .map((week) => ({ value: week, label: weekLabel(week) }));

    // ---- Filtering ----
    $: cowSet = new Set(selectedCows);
    $: monthSet = new Set(selectedMonths);
    $: weekSet = new Set(selectedWeeks);
    // Verwissel van/tot als ze omgekeerd zijn ingevuld.
    $: rangeFrom = dateFrom && dateTo && dateFrom > dateTo ? dateTo : dateFrom;
    $: rangeTo = dateFrom && dateTo && dateFrom > dateTo ? dateFrom : dateTo;
    $: filtered = enriched.filter(
        (r) =>
            (cowSet.size === 0 || cowSet.has(String(r.animal_number))) &&
            (monthSet.size === 0 || monthSet.has(r.monthKey)) &&
            (weekSet.size === 0 || weekSet.has(r.weekKey)) &&
            (!rangeFrom || r.dayKey >= rangeFrom) &&
            (!rangeTo || r.dayKey <= rangeTo)
    );

    $: filteredCowCount = new Set(filtered.map((r) => String(r.animal_number))).size;

    // ---- Tijd tussen melkingen ----
    $: ({ intervals, byRecordId: intervalByRecord } = computeIntervals(filtered));
    $: avgInterval = mean(intervals.map((i) => i.hours));

    // ---- Kerncijfers ----
    $: totalMilk = sum(filtered.map((r) => r.liters));
    // Aantal unieke (koe, dag)-combinaties: hiermee wordt de melkfrequentie
    // per koe per dag berekend, ongeacht hoeveel dagen data er zijn.
    $: cowDayCount = new Set(filtered.map((r) => `${r.animal_number}|${r.dayKey}`)).size;
    $: statCards = [
        { label: 'Aantal melkingen', value: fmt(filtered.length, 0), sub: `${filteredCowCount} koeien` },
        { label: 'Totale melk (L)', value: fmt(totalMilk, 0), sub: 'cumulatieve opbrengst' },
        {
            label: 'Gem. melk per melking (L)',
            value: fmt(filtered.length ? totalMilk / filtered.length : null, 2),
            sub: 'efficiëntie per melkbeurt'
        },
        {
            label: 'Gem. melkingen per koe per dag',
            value: fmt(cowDayCount ? filtered.length / cowDayCount : null, 2),
            sub: 'frequentie per dier per dag'
        },
        {
            label: 'Gem. tijd tussen melkingen (uur)',
            value: fmt(avgInterval, 1),
            sub: `gaten > ${MAX_INTERVAL_HOURS}u niet meegeteld`
        }
    ];

    // ---- Heatmaps (uur x dag) ----
    $: ({ countMatrix, avgLiters } = buildHeatmaps(filtered));

    // ---- Uur- en dagstatistieken ----
    const HOUR_LABELS = Array.from({ length: 24 }, (_, h) => `${h}:00`);

    function groupByHour(list) {
        const count = Array(24).fill(0);
        const liters = Array(24).fill(0);
        for (const r of list) {
            count[r.hour] += 1;
            liters[r.hour] += r.liters ?? 0;
        }
        return { count, liters };
    }

    $: hourly = groupByHour(filtered);

    $: hourChartData = {
        labels: HOUR_LABELS,
        datasets: [
            {
                type: 'bar',
                label: 'Aantal melkingen',
                data: hourly.count,
                backgroundColor: 'rgba(46, 139, 87, 0.55)',
                yAxisID: 'y'
            },
            {
                type: 'line',
                label: 'Gem. melk per melking (L)',
                data: hourly.count.map((c, h) => (c ? hourly.liters[h] / c : null)),
                borderColor: '#1d4ed8',
                backgroundColor: '#1d4ed8',
                pointRadius: 2,
                tension: 0.25,
                yAxisID: 'y1'
            }
        ]
    };

    $: dayGroups = (() => {
        const count = Array(7).fill(0);
        const liters = Array(7).fill(0);
        for (const r of filtered) {
            count[r.dayIdx] += 1;
            liters[r.dayIdx] += r.liters ?? 0;
        }
        return { count, liters };
    })();

    $: dayChartData = {
        labels: DAY_LABELS,
        datasets: [
            {
                type: 'bar',
                label: 'Aantal melkingen',
                data: dayGroups.count,
                backgroundColor: 'rgba(46, 139, 87, 0.55)',
                yAxisID: 'y'
            },
            {
                type: 'line',
                label: 'Totale melk (L)',
                data: dayGroups.liters,
                borderColor: '#1d4ed8',
                backgroundColor: '#1d4ed8',
                pointRadius: 3,
                tension: 0.25,
                yAxisID: 'y1'
            }
        ]
    };

    // ---- Totale productie per uur + cumulatief dagverloop ----
    $: cumulative = hourly.liters.reduce((acc, v) => {
        acc.push((acc.length ? acc[acc.length - 1] : 0) + v);
        return acc;
    }, []);

    $: productionChartData = {
        labels: HOUR_LABELS,
        datasets: [
            {
                type: 'bar',
                label: 'Totale melk per uur (L)',
                data: hourly.liters,
                backgroundColor: 'rgba(29, 78, 216, 0.5)',
                yAxisID: 'y'
            },
            {
                type: 'line',
                label: 'Cumulatief dagverloop (L)',
                data: cumulative,
                borderColor: '#e69500',
                backgroundColor: '#e69500',
                pointRadius: 0,
                tension: 0.2,
                yAxisID: 'y1'
            }
        ]
    };

    // ---- Verdeling tijd tussen melkingen ----
    const BIN_SIZE = 2;
    $: intervalBins = (() => {
        const bins = Array(MAX_INTERVAL_HOURS / BIN_SIZE).fill(0);
        for (const { hours } of intervals) {
            const idx = Math.min(bins.length - 1, Math.floor(hours / BIN_SIZE));
            bins[idx] += 1;
        }
        return bins;
    })();

    $: intervalDistData = {
        labels: intervalBins.map((_, i) => `${i * BIN_SIZE}–${(i + 1) * BIN_SIZE}u`),
        datasets: [
            {
                label: 'Aantal intervallen',
                data: intervalBins,
                backgroundColor: 'rgba(46, 139, 87, 0.55)'
            }
        ]
    };

    // ---- Ranglijst: gem. interval per koe ----
    $: intervalPerCow = (() => {
        const byCow = new Map();
        for (const { animal, hours } of intervals) {
            if (!byCow.has(animal)) {
                byCow.set(animal, []);
            }
            byCow.get(animal).push(hours);
        }
        return [...byCow.entries()]
            .map(([animal, list]) => ({ animal, avg: mean(list), n: list.length }))
            .filter((e) => e.n >= 2)
            .sort((a, b) => b.avg - a.avg)
            .slice(0, 15);
    })();

    $: intervalRankData = {
        labels: intervalPerCow.map((e) => `Koe ${e.animal}`),
        datasets: [
            {
                label: 'Gem. tijd tussen melkingen (uur)',
                data: intervalPerCow.map((e) => e.avg),
                backgroundColor: 'rgba(192, 57, 43, 0.55)'
            }
        ]
    };

    // ---- Trend per dag ----
    $: dailyTrend = (() => {
        const byDay = new Map();
        for (const r of filtered) {
            if (!byDay.has(r.dayKey)) {
                byDay.set(r.dayKey, { liters: 0, count: 0 });
            }
            const entry = byDay.get(r.dayKey);
            entry.liters += r.liters ?? 0;
            entry.count += 1;
        }
        const days = [...byDay.keys()].sort();
        return {
            labels: days,
            liters: days.map((d) => byDay.get(d).liters),
            counts: days.map((d) => byDay.get(d).count)
        };
    })();

    $: trendChartData = {
        labels: dailyTrend.labels,
        datasets: [
            {
                type: 'line',
                label: 'Totale melk per dag (L)',
                data: dailyTrend.liters,
                borderColor: '#2e8b57',
                backgroundColor: 'rgba(46, 139, 87, 0.15)',
                fill: true,
                pointRadius: 1,
                tension: 0.2,
                yAxisID: 'y'
            },
            {
                type: 'line',
                label: 'Aantal melkingen per dag',
                data: dailyTrend.counts,
                borderColor: '#1d4ed8',
                backgroundColor: '#1d4ed8',
                pointRadius: 1,
                tension: 0.2,
                yAxisID: 'y1'
            }
        ]
    };

    // ---- Statusverdeling ----
    $: statusCounts = (() => {
        const counts = new Map();
        for (const r of filtered) {
            counts.set(r.status, (counts.get(r.status) ?? 0) + 1);
        }
        return [...counts.entries()].sort((a, b) => b[1] - a[1]);
    })();

    $: statusChartData = {
        labels: statusCounts.map(([status]) => statusStyle(status).label),
        datasets: [
            {
                data: statusCounts.map(([, count]) => count),
                backgroundColor: statusCounts.map(([status]) => statusStyle(status).color)
            }
        ]
    };

    // ---- Weekvergelijking ----
    $: weekComparison = (() => {
        const byWeek = new Map();
        for (const r of filtered) {
            if (!byWeek.has(r.weekKey)) {
                byWeek.set(r.weekKey, { liters: 0, count: 0 });
            }
            const entry = byWeek.get(r.weekKey);
            entry.liters += r.liters ?? 0;
            entry.count += 1;
        }
        const keys = [...byWeek.keys()].sort();
        return {
            labels: keys,
            liters: keys.map((k) => byWeek.get(k).liters),
            counts: keys.map((k) => byWeek.get(k).count)
        };
    })();

    $: weekChartData = {
        labels: weekComparison.labels,
        datasets: [
            {
                label: 'Aantal melkingen',
                data: weekComparison.counts,
                backgroundColor: 'rgba(46, 139, 87, 0.55)',
                yAxisID: 'y'
            },
            {
                label: 'Totale melk (L)',
                data: weekComparison.liters,
                backgroundColor: 'rgba(29, 78, 216, 0.5)',
                yAxisID: 'y1'
            }
        ]
    };

    // ---- Recente melkingen ----
    $: recentRows = [...filtered].reverse().slice(0, 30);

    // ---- Chartopties ----
    const baseOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } }
    };

    const dualAxis = (leftTitle, rightTitle) => ({
        ...baseOptions,
        scales: {
            y: {
                beginAtZero: true,
                position: 'left',
                title: { display: true, text: leftTitle }
            },
            y1: {
                beginAtZero: true,
                position: 'right',
                grid: { drawOnChartArea: false },
                title: { display: true, text: rightTitle }
            }
        }
    });

    const singleAxis = (yTitle) => ({
        ...baseOptions,
        scales: { y: { beginAtZero: true, title: { display: true, text: yTitle } } }
    });

    const rankOptions = {
        ...baseOptions,
        indexAxis: 'y',
        scales: { x: { beginAtZero: true, title: { display: true, text: 'Uren' } } }
    };

    const donutOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { position: 'bottom' },
            tooltip: {
                callbacks: {
                    label: (ctx) => {
                        const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                        const pct = total ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                        return ` ${ctx.label}: ${ctx.parsed} (${pct}%)`;
                    }
                }
            }
        }
    };
</script>

<main>
    <header>
        <h1>Melkrobot Monitor</h1>
        <div class="header-status">
            <button type="button" class="refresh" on:click={load} disabled={loading}>
                {loading ? 'Bezig…' : 'Ververs nu'}
            </button>
            <span class="updated">
                Bijgewerkt: {clockLabel(lastUpdated)}
                {#if lastChecked && lastChecked !== lastUpdated}
                    · gecontroleerd: {clockLabel(lastChecked)}
                {/if}
            </span>
            {#if loadError}
                <span class="error">{loadError}</span>
            {/if}
        </div>
    </header>

    <section class="filters card">
        <MultiSelect
            label="Koeien"
            options={cowOptions}
            bind:selected={selectedCows}
            allLabel="Alle koeien"
            searchable
        />
        <MultiSelect
            label="Maanden"
            options={monthOptions}
            bind:selected={selectedMonths}
            allLabel="Alle maanden"
        />
        <MultiSelect
            label="Weken"
            options={weekOptions}
            bind:selected={selectedWeeks}
            allLabel="Alle weken"
            searchable
        />
        <div class="filter-group">
            <label for="from">Datumbereik</label>
            <div class="date-row">
                <input id="from" type="date" bind:value={dateFrom} />
                <span>t/m</span>
                <input type="date" bind:value={dateTo} />
            </div>
        </div>
        <div class="filter-group filter-footer">
            <button type="button" class="reset" on:click={resetFilters}>Alle filters wissen</button>
            <p class="filter-info">
                {fmt(filtered.length, 0)} van {fmt(enriched.length, 0)} melkingen geselecteerd
            </p>
        </div>
    </section>

    <section class="layout">
        <div class="charts">
            <div class="card wide">
                <h3>Heatmap: aantal melkingen per uur en dag</h3>
                <Heatmap matrix={countMatrix} unit="melkingen" decimals={0} />
            </div>
            <div class="card wide">
                <h3>Heatmap: gemiddelde melk (L) per uur en dag</h3>
                <Heatmap matrix={avgLiters} unit="L" decimals={1} />
            </div>

            <div class="card">
                <h3>Melkingen per uur van de dag</h3>
                <div class="chart">
                    <ChartBox type="bar" data={hourChartData} options={dualAxis('Aantal', 'Liters')} />
                </div>
            </div>
            <div class="card">
                <h3>Melkingen per dag van de week</h3>
                <div class="chart">
                    <ChartBox type="bar" data={dayChartData} options={dualAxis('Aantal', 'Liters')} />
                </div>
            </div>

            <div class="card">
                <h3>Totale productie per uur + cumulatief verloop</h3>
                <div class="chart">
                    <ChartBox
                        type="bar"
                        data={productionChartData}
                        options={dualAxis('Liters per uur', 'Cumulatief (L)')}
                    />
                </div>
            </div>
            <div class="card">
                <h3>Trend: dagopbrengst vs. aantal melkingen</h3>
                <div class="chart">
                    <ChartBox type="line" data={trendChartData} options={dualAxis('Liters', 'Aantal')} />
                </div>
            </div>

            <div class="card">
                <h3>Verdeling tijd tussen melkingen</h3>
                <div class="chart">
                    <ChartBox
                        type="bar"
                        data={intervalDistData}
                        options={singleAxis('Aantal intervallen')}
                    />
                </div>
            </div>
            <div class="card">
                <h3>Langste gem. tijd tussen melkingen per koe (top 15)</h3>
                <div class="chart">
                    <ChartBox type="bar" data={intervalRankData} options={rankOptions} />
                </div>
            </div>

            <div class="card">
                <h3>Status van melkingen</h3>
                <div class="chart donut">
                    <ChartBox type="doughnut" data={statusChartData} options={donutOptions} />
                </div>
            </div>
            <div class="card">
                <h3>Weekvergelijking</h3>
                <div class="chart">
                    <ChartBox type="bar" data={weekChartData} options={dualAxis('Aantal', 'Liters')} />
                </div>
            </div>

            <div class="card wide">
                <h3>Recente melkingen</h3>
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th>Tijdstip</th>
                                <th>Koe</th>
                                <th>Liters</th>
                                <th>Status</th>
                                <th>Tijd sinds vorige melking</th>
                            </tr>
                        </thead>
                        <tbody>
                            {#each recentRows as record (record.id)}
                                <tr>
                                    <td>{record.timestamp.replace('T', ' ')}</td>
                                    <td>{record.animal_number}</td>
                                    <td>{fmt(record.liters, 2)}</td>
                                    <td style="color: {statusStyle(record.status).color}">
                                        {statusStyle(record.status).label}
                                    </td>
                                    <td>
                                        {intervalByRecord.has(record.id)
                                            ? `${fmt(intervalByRecord.get(record.id), 1)} uur`
                                            : '–'}
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <aside class="stats">
            {#each statCards as card}
                <div class="card stat">
                    <span class="stat-label">{card.label}</span>
                    <span class="stat-value">{card.value}</span>
                    <span class="stat-sub">{card.sub}</span>
                </div>
            {/each}
        </aside>
    </section>
</main>

<style>
    :global(body) {
        margin: 0;
        font-family: system-ui, sans-serif;
        background: #f5f6f8;
        color: #1e2430;
    }

    main {
        max-width: 1400px;
        margin: 0 auto;
        padding: 1rem;
    }

    header {
        display: flex;
        align-items: baseline;
        gap: 1rem;
        flex-wrap: wrap;
        margin-bottom: 0.75rem;
    }

    h1 {
        margin: 0;
        font-size: 1.4rem;
    }

    .header-status {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        flex-wrap: wrap;
    }

    .refresh {
        padding: 0.35rem 0.7rem;
        font-size: 0.82rem;
        cursor: pointer;
        border: 1px solid #2e8b57;
        border-radius: 6px;
        background: #e8f5ee;
        color: #175e38;
        font-weight: 600;
    }

    .refresh:hover:not(:disabled) {
        background: #d6ecdf;
    }

    .refresh:disabled {
        opacity: 0.6;
        cursor: default;
    }

    .updated {
        font-size: 0.8rem;
        color: #6b7280;
    }

    h3 {
        margin: 0 0 0.6rem;
        font-size: 0.95rem;
    }

    .error {
        color: #c0392b;
        font-size: 0.9rem;
    }

    .card {
        background: white;
        border-radius: 8px;
        padding: 1rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    }

    .filters {
        display: flex;
        gap: 1.25rem;
        flex-wrap: wrap;
        align-items: flex-start;
        margin-bottom: 1rem;
        overflow: visible;
    }

    .filter-group {
        display: flex;
        flex-direction: column;
        gap: 0.35rem;
    }

    .filter-group label {
        font-weight: 600;
        font-size: 0.85rem;
    }

    .filter-footer {
        justify-content: flex-end;
        align-self: stretch;
        margin-left: auto;
    }

    .reset {
        align-self: flex-start;
        padding: 0.45rem 0.7rem;
        font-size: 0.85rem;
        cursor: pointer;
        border: 1px solid #d1d5db;
        border-radius: 6px;
        background: #f9fafb;
    }

    .reset:hover {
        background: #eef2f6;
    }

    .date-row {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.85rem;
    }

    .date-row input {
        padding: 0.35rem 0.5rem;
        border: 1px solid #d1d5db;
        border-radius: 6px;
        background: #f9fafb;
        font-size: 0.85rem;
    }

    .filter-info {
        margin: 0;
        font-size: 0.8rem;
        color: #6b7280;
    }

    .layout {
        display: grid;
        grid-template-columns: 1fr 240px;
        gap: 1rem;
        align-items: start;
    }

    .charts {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1rem;
    }

    .wide {
        grid-column: 1 / -1;
    }

    .chart {
        height: 300px;
        position: relative;
    }

    .chart.donut {
        height: 260px;
    }

    .stats {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        position: sticky;
        top: 1rem;
    }

    .stat {
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
    }

    .stat-label {
        font-size: 0.78rem;
        color: #6b7280;
        font-weight: 600;
    }

    .stat-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: #175e38;
    }

    .stat-sub {
        font-size: 0.72rem;
        color: #9aa3af;
    }

    .table-wrapper {
        max-height: 360px;
        overflow-y: auto;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85rem;
    }

    th,
    td {
        text-align: center;
        padding: 0.35rem 0.4rem;
        border-bottom: 1px solid #eceff3;
    }

    th {
        position: sticky;
        top: 0;
        background: white;
    }

    @media (max-width: 1100px) {
        .layout {
            grid-template-columns: 1fr;
        }

        .stats {
            position: static;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        }
    }

    @media (max-width: 800px) {
        .charts {
            grid-template-columns: 1fr;
        }
    }
</style>
