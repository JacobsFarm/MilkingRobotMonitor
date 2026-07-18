<script>
    import { onDestroy, onMount } from 'svelte';
    import ChartBox from '$lib/components/ChartBox.svelte';
    import Heatmap from '$lib/components/Heatmap.svelte';
    import MultiSelect from '$lib/components/MultiSelect.svelte';
    import { DAY_LABELS, fmt, monthLabel, weekLabel } from '$lib/format.js';

    // Deze pagina is puur presentatie: alle statistiek wordt op de server
    // berekend (lib/server/aggregate.js) en komt kant-en-klaar binnen via
    // /api/stats. Filters gaan als query-parameters mee naar de server.

    const STATUS_STYLES = {
        OK: { color: '#2e8b57', label: 'Geslaagd' },
        '!': { color: '#e69500', label: 'Mislukt' },
        '#': { color: '#c0392b', label: 'Fout' }
    };

    const EMPTY_STATS = {
        options: { cows: [], months: [], weeks: [] },
        filtered: { count: 0, of: 0 },
        totals: {
            count: 0,
            cowCount: 0,
            totalLiters: 0,
            avgPerMilking: null,
            milkingsPerCowDay: null,
            avgIntervalHours: null
        },
        heatmaps: {
            count: Array.from({ length: 7 }, () => Array(24).fill(null)),
            avgLiters: Array.from({ length: 7 }, () => Array(24).fill(null))
        },
        hourly: {
            count: Array(24).fill(0),
            totalLiters: Array(24).fill(0),
            avgPerMilking: Array(24).fill(null),
            cumulative: Array(24).fill(0)
        },
        weekday: { count: Array(7).fill(0), totalLiters: Array(7).fill(0) },
        intervals: { bins: Array(12).fill(0), binHours: 2, maxHours: 24, perCowTop: [] },
        dailyTrend: { labels: [], liters: [], counts: [] },
        status: [],
        weekly: { labels: [], counts: [], liters: [] },
        recent: [],
        feed: { available: false },
        production: { available: false }
    };

    let stats = EMPTY_STATS;
    let progress = { complete: true, loaded: null };
    let refreshMs = 30000;
    let loadError = '';
    let loading = false;

    // AI-bevindingen: door de agent (apart post-platform) in de eVault
    // geschreven; het dashboard leest ze alleen.
    let insights = [];
    let insightsDate = null;

    // Slimme poll: de signature dekt dataset + filters; bij een match stuurt
    // de server een lege "unchanged"-respons in plaats van dezelfde cijfers.
    let lastSignature = '';
    let lastLoadedFilterKey = null;
    let lastUpdated = null;
    let lastChecked = null;

    let mounted = false;
    let pollTimer = null;
    let debounceTimer = null;

    // Filters
    let selectedCows = [];
    let selectedMonths = [];
    let selectedWeeks = [];
    let dateFrom = '';
    let dateTo = '';

    $: filterKey = JSON.stringify([
        [...selectedCows].sort(),
        [...selectedMonths].sort(),
        [...selectedWeeks].sort(),
        dateFrom,
        dateTo
    ]);
    $: if (mounted) {
        onFiltersChanged(filterKey);
    }

    function onFiltersChanged(key) {
        if (key === lastLoadedFilterKey) {
            return;
        }
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(load, 250);
    }

    function buildQuery() {
        const params = new URLSearchParams();
        if (selectedCows.length) params.set('cows', selectedCows.join(','));
        if (selectedMonths.length) params.set('months', selectedMonths.join(','));
        if (selectedWeeks.length) params.set('weeks', selectedWeeks.join(','));
        if (dateFrom) params.set('from', dateFrom);
        if (dateTo) params.set('to', dateTo);
        if (lastSignature) params.set('sig', lastSignature);
        const query = params.toString();
        return query ? `?${query}` : '';
    }

    async function loadInsights() {
        try {
            const response = await fetch('/api/insights');
            if (!response.ok) {
                return;
            }
            const payload = await response.json();
            insights = payload.insights ?? [];
            insightsDate = payload.analysis_date ?? null;
        } catch {
            // Bevindingen zijn optioneel: bij een fout blijft de vorige lijst staan.
        }
    }

    async function load() {
        if (loading) {
            return;
        }
        loading = true;
        loadInsights();
        const requestedKey = filterKey;
        try {
            const response = await fetch(`/api/stats${buildQuery()}`);
            if (!response.ok) {
                loadError = `Vault request failed (${response.status})`;
                return;
            }
            const payload = await response.json();
            refreshMs = payload.refresh_ms ?? refreshMs;
            progress = payload.progress ?? progress;
            lastChecked = new Date();
            lastSignature = payload.signature ?? '';
            lastLoadedFilterKey = requestedKey;
            if (!payload.unchanged && payload.stats) {
                stats = payload.stats;
                lastUpdated = new Date();
            }
            loadError = '';
        } catch (error) {
            loadError = String(error);
        } finally {
            loading = false;
            if (filterKey !== requestedKey) {
                // Filters zijn tijdens het laden veranderd: meteen opnieuw.
                load();
            } else {
                schedulePoll();
            }
        }
    }

    function schedulePoll() {
        clearTimeout(pollTimer);
        // Tijdens het vullen van de eVault-cache vaker verversen, zodat de
        // grafieken zichtbaar vollopen; daarna het normale interval.
        const wait = progress?.complete === false ? 4000 : refreshMs;
        pollTimer = setTimeout(load, wait);
    }

    onMount(() => {
        lastLoadedFilterKey = filterKey;
        mounted = true;
        load();
    });

    onDestroy(() => {
        clearTimeout(pollTimer);
        clearTimeout(debounceTimer);
    });

    function clockLabel(date) {
        return date
            ? date.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            : '–';
    }

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

    // ---- AI-bevindingen (presentatie) ----
    const INSIGHT_TYPE_LABELS = {
        herd_yield_change: 'Kudde-opbrengst',
        herd_failure_rate: 'Mislukte melkingen',
        cow_yield_drop: 'Opbrengst gedaald',
        cow_yield_rise: 'Opbrengst gestegen',
        cow_interval_rise: 'Langere tussenpozen',
        cow_feed_left: 'Voer laten staan',
        herd_feed_efficiency_change: 'Voerefficiëntie',
        cow_speed_drop: 'Melksnelheid gedaald'
    };

    function insightTypeLabel(insight) {
        return INSIGHT_TYPE_LABELS[insight.type] ?? insight.type;
    }

    function insightEvidence(insight) {
        const e = insight.evidence ?? {};
        const parts = [];
        if (e.baseline_liters_per_day != null && e.recent_liters_per_day != null) {
            parts.push(
                `${fmt(e.baseline_liters_per_day, 1)} → ${fmt(e.recent_liters_per_day, 1)} L/dag`
            );
        } else if (e.baseline_avg_interval_hours != null && e.recent_avg_interval_hours != null) {
            parts.push(
                `${fmt(e.baseline_avg_interval_hours, 1)}u → ${fmt(e.recent_avg_interval_hours, 1)}u tussen melkingen`
            );
        } else if (e.failed != null && e.total != null) {
            parts.push(`${fmt(e.failed, 0)} van ${fmt(e.total, 0)} melkingen niet normaal afgerond`);
        } else if (e.not_finished != null && e.feedings != null) {
            parts.push(`${fmt(e.not_finished, 0)} van ${fmt(e.feedings, 0)} voerbeurten niet leeg`);
        } else if (e.baseline_liters_per_kg != null && e.recent_liters_per_kg != null) {
            parts.push(
                `${fmt(e.baseline_liters_per_kg, 2)} → ${fmt(e.recent_liters_per_kg, 2)} L melk per kg voer`
            );
        } else if (e.previous_speed_kg_min != null && e.latest_speed_kg_min != null) {
            parts.push(
                `${fmt(e.previous_speed_kg_min, 2)} → ${fmt(e.latest_speed_kg_min, 2)} kg/min (rapport ${dmy(e.latest_report)})`
            );
        }
        if (e.recent_days_measured != null) {
            parts.push(`gemeten op ${e.recent_days_measured} dagen`);
        } else if (e.recent_intervals_measured != null) {
            parts.push(`${e.recent_intervals_measured} tussenpozen gemeten`);
        }
        return parts.join(' · ');
    }

    function dmy(isoDate) {
        if (typeof isoDate !== 'string' || isoDate.length < 10) return isoDate ?? '–';
        const [year, month, day] = isoDate.slice(0, 10).split('-');
        return `${day}-${month}-${year}`;
    }

    // Alle bevindingen van één analyse delen dezelfde meetperiode.
    $: insightPeriod = insights.find((i) => i.period)?.period ?? null;
    // De vensters zijn verankerd op de nieuwste melking in de eVault, niet op
    // de analysedatum: loopt de data achter, dan hoort dat zichtbaar te zijn.
    $: insightsStaleDays =
        insightPeriod && insightsDate
            ? Math.round(
                  (new Date(insightsDate) - new Date(insightPeriod.data_until)) / 86400000
              )
            : 0;

    function focusInsightCow(insight) {
        const animal = insight.scope?.animal_number;
        if (animal != null) {
            // Filtert het hele dashboard op deze koe; de grafieken laden opnieuw.
            selectedCows = [String(animal)];
        }
    }

    // ---- Filteropties (waarden van de server, labels hier) ----
    $: cowOptions = stats.options.cows.map((cow) => ({ value: cow, label: `Koe ${cow}` }));
    $: monthOptions = stats.options.months.map((month) => ({
        value: month,
        label: monthLabel(month)
    }));
    $: weekOptions = stats.options.weeks.map((week) => ({ value: week, label: weekLabel(week) }));

    // ---- Kerncijfers ----
    $: extraCards = [
        ...(stats.feed.available && stats.feed.totals.litersPerKg != null
            ? [
                  {
                      label: 'Voerefficiëntie (L melk / kg voer)',
                      value: fmt(stats.feed.totals.litersPerKg, 2),
                      sub: `over ${stats.feed.totals.overlapDays} dagen met beide metingen`
                  }
              ]
            : []),
        ...(stats.production.available && stats.production.latest.avgSpeed != null
            ? [
                  {
                      label: 'Gem. melksnelheid (kg/min)',
                      value: fmt(stats.production.latest.avgSpeed, 2),
                      sub: `rapport ${dmy(stats.production.latestDate)} · ${stats.production.latest.cowCount} koeien`
                  }
              ]
            : [])
    ];
    $: statCards = [
        {
            label: 'Aantal melkingen',
            value: fmt(stats.totals.count, 0),
            sub: `${stats.totals.cowCount} koeien`
        },
        {
            label: 'Totale melk (L)',
            value: fmt(stats.totals.totalLiters, 0),
            sub: 'cumulatieve opbrengst'
        },
        {
            label: 'Gem. melk per melking (L)',
            value: fmt(stats.totals.avgPerMilking, 2),
            sub: 'efficiëntie per melkbeurt'
        },
        {
            label: 'Gem. melkingen per koe per dag',
            value: fmt(stats.totals.milkingsPerCowDay, 2),
            sub: 'frequentie per dier per dag'
        },
        {
            label: 'Gem. tijd tussen melkingen (uur)',
            value: fmt(stats.totals.avgIntervalHours, 1),
            sub: `gaten > ${stats.intervals.maxHours}u niet meegeteld`
        }
    ];

    // ---- Grafiekdata (alleen vormgeving; cijfers komen van de server) ----
    const HOUR_LABELS = Array.from({ length: 24 }, (_, h) => `${h}:00`);

    $: hourChartData = {
        labels: HOUR_LABELS,
        datasets: [
            {
                type: 'bar',
                label: 'Aantal melkingen',
                data: stats.hourly.count,
                backgroundColor: 'rgba(46, 139, 87, 0.55)',
                yAxisID: 'y'
            },
            {
                type: 'line',
                label: 'Gem. melk per melking (L)',
                data: stats.hourly.avgPerMilking,
                borderColor: '#1d4ed8',
                backgroundColor: '#1d4ed8',
                pointRadius: 2,
                tension: 0.25,
                yAxisID: 'y1'
            }
        ]
    };

    $: dayChartData = {
        labels: DAY_LABELS,
        datasets: [
            {
                type: 'bar',
                label: 'Aantal melkingen',
                data: stats.weekday.count,
                backgroundColor: 'rgba(46, 139, 87, 0.55)',
                yAxisID: 'y'
            },
            {
                type: 'line',
                label: 'Totale melk (L)',
                data: stats.weekday.totalLiters,
                borderColor: '#1d4ed8',
                backgroundColor: '#1d4ed8',
                pointRadius: 3,
                tension: 0.25,
                yAxisID: 'y1'
            }
        ]
    };

    $: productionChartData = {
        labels: HOUR_LABELS,
        datasets: [
            {
                type: 'bar',
                label: 'Totale melk per uur (L)',
                data: stats.hourly.totalLiters,
                backgroundColor: 'rgba(29, 78, 216, 0.5)',
                yAxisID: 'y'
            },
            {
                type: 'line',
                label: 'Cumulatief dagverloop (L)',
                data: stats.hourly.cumulative,
                borderColor: '#e69500',
                backgroundColor: '#e69500',
                pointRadius: 0,
                tension: 0.2,
                yAxisID: 'y1'
            }
        ]
    };

    $: intervalDistData = {
        labels: stats.intervals.bins.map(
            (_, i) => `${i * stats.intervals.binHours}–${(i + 1) * stats.intervals.binHours}u`
        ),
        datasets: [
            {
                label: 'Aantal intervallen',
                data: stats.intervals.bins,
                backgroundColor: 'rgba(46, 139, 87, 0.55)'
            }
        ]
    };

    $: intervalRankData = {
        labels: stats.intervals.perCowTop.map((e) => `Koe ${e.animal}`),
        datasets: [
            {
                label: 'Gem. tijd tussen melkingen (uur)',
                data: stats.intervals.perCowTop.map((e) => e.avg),
                backgroundColor: 'rgba(192, 57, 43, 0.55)'
            }
        ]
    };

    $: trendChartData = {
        labels: stats.dailyTrend.labels,
        datasets: [
            {
                type: 'line',
                label: 'Totale melk per dag (L)',
                data: stats.dailyTrend.liters,
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
                data: stats.dailyTrend.counts,
                borderColor: '#1d4ed8',
                backgroundColor: '#1d4ed8',
                pointRadius: 1,
                tension: 0.2,
                yAxisID: 'y1'
            }
        ]
    };

    $: statusChartData = {
        labels: stats.status.map(({ status }) => statusStyle(status).label),
        datasets: [
            {
                data: stats.status.map(({ count }) => count),
                backgroundColor: stats.status.map(({ status }) => statusStyle(status).color)
            }
        ]
    };

    $: weekChartData = {
        labels: stats.weekly.labels,
        datasets: [
            {
                label: 'Aantal melkingen',
                data: stats.weekly.counts,
                backgroundColor: 'rgba(46, 139, 87, 0.55)',
                yAxisID: 'y'
            },
            {
                label: 'Totale melk (L)',
                data: stats.weekly.liters,
                backgroundColor: 'rgba(29, 78, 216, 0.5)',
                yAxisID: 'y1'
            }
        ]
    };

    // ---- Voer × melk (server joint op dag; zelfde filters als de rest) ----
    $: feedMilkChartData = stats.feed.available
        ? {
              labels: stats.feed.dailyTrend.labels,
              datasets: [
                  {
                      type: 'bar',
                      label: 'Voergift per dag (kg)',
                      data: stats.feed.dailyTrend.feedKg,
                      backgroundColor: 'rgba(180, 83, 9, 0.45)',
                      yAxisID: 'y'
                  },
                  {
                      type: 'line',
                      label: 'Melkgift per dag (L)',
                      data: stats.feed.dailyTrend.milkLiters,
                      borderColor: '#2e8b57',
                      backgroundColor: '#2e8b57',
                      pointRadius: 1,
                      tension: 0.2,
                      spanGaps: false,
                      yAxisID: 'y1'
                  }
              ]
          }
        : null;

    $: efficiencyChartData = stats.feed.available
        ? {
              labels: stats.feed.dailyTrend.labels,
              datasets: [
                  {
                      type: 'line',
                      label: 'Efficiëntie (L melk per kg voer)',
                      data: stats.feed.dailyTrend.efficiency,
                      borderColor: '#1d4ed8',
                      backgroundColor: '#1d4ed8',
                      pointRadius: 1,
                      tension: 0.2,
                      spanGaps: false,
                      yAxisID: 'y'
                  },
                  {
                      type: 'line',
                      label: 'Restvoer (% voerbeurten niet leeg)',
                      data: stats.feed.dailyTrend.leftoverPct,
                      borderColor: '#c0392b',
                      backgroundColor: '#c0392b',
                      pointRadius: 1,
                      tension: 0.2,
                      spanGaps: false,
                      yAxisID: 'y1'
                  }
              ]
          }
        : null;

    $: leftoversChartData = stats.feed.available
        ? {
              labels: stats.feed.leftovers.topCows.map((c) => `Koe ${c.animal}`),
              datasets: [
                  {
                      label: 'Voerbeurten niet leeggegeten',
                      data: stats.feed.leftovers.topCows.map((c) => c.notFinished),
                      backgroundColor: 'rgba(192, 57, 43, 0.55)'
                  }
              ]
          }
        : null;

    // ---- Productie-snapshots (melksnelheid is robot-authoritatief) ----
    $: speedScatterData = stats.production.available
        ? {
              datasets: [
                  {
                      label: 'Koe (nieuwste rapport)',
                      data: stats.production.points
                          .filter((p) => p.speed != null && p.milk24 != null)
                          .map((p) => ({ x: p.speed, y: p.milk24, animal: p.animal })),
                      backgroundColor: 'rgba(29, 78, 216, 0.7)'
                  }
              ]
          }
        : null;

    $: lactationScatterData = stats.production.available
        ? {
              datasets: [
                  {
                      label: 'Koe (nieuwste rapport)',
                      data: stats.production.points
                          .filter((p) => p.lactationDays != null && p.milk24 != null)
                          .map((p) => ({ x: p.lactationDays, y: p.milk24, animal: p.animal })),
                      backgroundColor: 'rgba(46, 139, 87, 0.7)'
                  }
              ]
          }
        : null;

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

    const leftoverRankOptions = {
        ...baseOptions,
        indexAxis: 'y',
        scales: {
            x: {
                beginAtZero: true,
                ticks: { precision: 0 },
                title: { display: true, text: 'Voerbeurten niet leeg' }
            }
        }
    };

    const scatterOptions = (xTitle, yTitle) => ({
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                callbacks: {
                    label: (ctx) =>
                        ` Koe ${ctx.raw.animal}: ${ctx.parsed.x} ${xTitle}, ${ctx.parsed.y} ${yTitle}`
                }
            }
        },
        scales: {
            x: { title: { display: true, text: xTitle } },
            y: { beginAtZero: true, title: { display: true, text: yTitle } }
        }
    });

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
            {#if progress && progress.complete === false}
                <span class="progress">
                    eVault laden: {fmt(progress.loaded ?? 0, 0)} records binnen…
                </span>
            {/if}
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
                {fmt(stats.filtered.count, 0)} van {fmt(stats.filtered.of, 0)} melkingen geselecteerd
            </p>
        </div>
    </section>

    <section class="layout">
        <div class="charts">
            {#if insights.length}
                <div class="card wide">
                    <div class="insights-head">
                        <h3>AI-bevindingen</h3>
                        <span class="insights-meta">
                            analyse van {dmy(insightsDate)} · {insights.length} bevindingen
                            {#if insightPeriod}
                                · meetperiode {dmy(insightPeriod.data_from)} t/m {dmy(
                                    insightPeriod.data_until
                                )}, vergeleken met {dmy(insightPeriod.baseline_from)} t/m {dmy(
                                    insightPeriod.data_from
                                )}
                            {/if}
                        </span>
                        {#if insightsStaleDays > 2}
                            <span class="insights-stale">
                                ⚠ nieuwste melking in de eVault is van {dmy(
                                    insightPeriod.data_until
                                )} — de data loopt {insightsStaleDays} dagen achter
                            </span>
                        {/if}
                    </div>
                    <ul class="insight-list">
                        {#each insights as insight (insight.id)}
                            <li class="insight {insight.severity}">
                                <div class="insight-top">
                                    <span class="insight-badge {insight.severity}">
                                        {insight.severity === 'high' ? 'Hoog' : 'Let op'}
                                    </span>
                                    <span class="insight-kind">{insightTypeLabel(insight)}</span>
                                    {#if insight.scope?.animal_number != null}
                                        <button
                                            type="button"
                                            class="cow-link"
                                            title="Filter het dashboard op deze koe"
                                            on:click={() => focusInsightCow(insight)}
                                        >
                                            koe {insight.scope.animal_number} →
                                        </button>
                                    {/if}
                                </div>
                                <p class="insight-title">{insight.title}</p>
                                {#if insight.body}
                                    <p class="insight-body">{insight.body}</p>
                                {/if}
                                <p class="insight-evidence">
                                    {insightEvidence(insight)}
                                    {#if insight.evidence?.change_pct != null}
                                        ({insight.evidence.change_pct > 0 ? '+' : ''}{fmt(
                                            insight.evidence.change_pct,
                                            1
                                        )}%)
                                    {/if}
                                    {#if insight.model}
                                        · {insight.model}
                                    {/if}
                                </p>
                            </li>
                        {/each}
                    </ul>
                </div>
            {/if}

            <div class="card wide">
                <h3>Heatmap: aantal melkingen per uur en dag</h3>
                <Heatmap matrix={stats.heatmaps.count} unit="melkingen" decimals={0} />
            </div>
            <div class="card wide">
                <h3>Heatmap: gemiddelde melk (L) per uur en dag</h3>
                <Heatmap matrix={stats.heatmaps.avgLiters} unit="L" decimals={1} />
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

            {#if stats.feed.available}
                <div class="card wide">
                    <h3>Voergift vs. melkgift per dag</h3>
                    <div class="chart">
                        <ChartBox
                            type="bar"
                            data={feedMilkChartData}
                            options={dualAxis('Voer (kg)', 'Melk (L)')}
                        />
                    </div>
                </div>

                <div class="card">
                    <h3>Voerefficiëntie & restvoer per dag</h3>
                    <div class="chart">
                        <ChartBox
                            type="line"
                            data={efficiencyChartData}
                            options={dualAxis('L melk / kg voer', 'Restvoer %')}
                        />
                    </div>
                </div>
                <div class="card">
                    <h3>Restvoer per koe (mogelijk vroeg ziektesignaal)</h3>
                    <div class="chart">
                        <ChartBox
                            type="bar"
                            data={leftoversChartData}
                            options={leftoverRankOptions}
                        />
                    </div>
                </div>
            {/if}

            {#if stats.production.available}
                <div class="card">
                    <h3>
                        Melksnelheid vs. dagproductie per koe (rapport
                        {dmy(stats.production.latestDate)})
                    </h3>
                    <div class="chart">
                        <ChartBox
                            type="scatter"
                            data={speedScatterData}
                            options={scatterOptions('kg/min', 'kg per 24u')}
                        />
                    </div>
                </div>
                <div class="card">
                    <h3>Lactatiecurve: dagen in lactatie vs. dagproductie</h3>
                    <div class="chart">
                        <ChartBox
                            type="scatter"
                            data={lactationScatterData}
                            options={scatterOptions('dagen in lactatie', 'kg per 24u')}
                        />
                    </div>
                </div>
            {/if}

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
                            {#each stats.recent as record (record.id)}
                                <tr>
                                    <td>{record.timestamp.replace('T', ' ')}</td>
                                    <td>{record.animal_number}</td>
                                    <td>{fmt(record.liters, 2)}</td>
                                    <td style="color: {statusStyle(record.status).color}">
                                        {statusStyle(record.status).label}
                                    </td>
                                    <td>
                                        {record.intervalHours != null
                                            ? `${fmt(record.intervalHours, 1)} uur`
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
            {#each [...statCards, ...extraCards] as card}
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

    .progress {
        font-size: 0.8rem;
        color: #b45309;
        font-weight: 600;
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

    .insights-head {
        display: flex;
        align-items: baseline;
        gap: 0.75rem;
        flex-wrap: wrap;
    }

    .insights-meta {
        font-size: 0.76rem;
        color: #6b7280;
    }

    .insights-stale {
        flex-basis: 100%;
        font-size: 0.78rem;
        font-weight: 600;
        color: #b45309;
    }

    .insight-list {
        list-style: none;
        margin: 0;
        padding: 0;
        max-height: 340px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .insight {
        border: 1px solid #eceff3;
        border-left-width: 4px;
        border-radius: 6px;
        padding: 0.5rem 0.7rem;
    }

    .insight.high {
        border-left-color: #c0392b;
    }

    .insight.medium {
        border-left-color: #e69500;
    }

    .insight-top {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .insight-badge {
        font-size: 0.68rem;
        font-weight: 700;
        padding: 0.1rem 0.45rem;
        border-radius: 999px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }

    .insight-badge.high {
        background: #fdecea;
        color: #c0392b;
    }

    .insight-badge.medium {
        background: #fef5e7;
        color: #b45309;
    }

    .insight-kind {
        font-size: 0.76rem;
        font-weight: 600;
        color: #6b7280;
    }

    .cow-link {
        margin-left: auto;
        border: none;
        background: none;
        color: #175e38;
        font-size: 0.78rem;
        font-weight: 600;
        cursor: pointer;
        padding: 0.1rem 0.3rem;
    }

    .cow-link:hover {
        text-decoration: underline;
    }

    .insight-title {
        margin: 0.3rem 0 0;
        font-size: 0.88rem;
        font-weight: 600;
    }

    .insight-body {
        margin: 0.25rem 0 0;
        font-size: 0.82rem;
        color: #374151;
    }

    .insight-evidence {
        margin: 0.3rem 0 0;
        font-size: 0.74rem;
        color: #6b7280;
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
