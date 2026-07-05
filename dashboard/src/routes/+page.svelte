<script>
    import { onDestroy, onMount } from 'svelte';
    import Chart from 'chart.js/auto';

    const STATUS_STYLES = {
        OK: { color: '#2e8b57', label: 'Successful milking' },
        '!': { color: '#e69500', label: 'Incomplete milking' },
        '#': { color: '#c0392b', label: 'Failed milking' }
    };

    let records = {};
    let animals = [];
    let selected = '';
    let refreshMs = 5000;
    let yieldDivisor = 1000;
    let chart;
    let canvasElement;
    let timer;
    let loadError = '';

    function litersOf(record) {
        if (typeof record.yield_raw === 'number') {
            return record.yield_raw / yieldDivisor;
        }
        if (typeof record.yield_liters === 'number') {
            return record.yield_liters;
        }
        return null;
    }

    function statusStyle(status) {
        return STATUS_STYLES[status] ?? STATUS_STYLES['#'];
    }

    async function load() {
        try {
            const response = await fetch('/api/records');
            if (!response.ok) {
                loadError = `Vault request failed (${response.status})`;
                return;
            }
            const payload = await response.json();
            refreshMs = payload.refresh_ms ?? refreshMs;
            yieldDivisor = payload.yield_divisor ?? yieldDivisor;
            const next = { ...records };
            for (const record of payload.records) {
                next[record.id] = record;
            }
            records = next;
            animals = [...new Set(Object.values(records).map((r) => String(r.animal_number)))].sort();
            if (!selected && animals.length) {
                selected = animals[0];
            }
            loadError = '';
        } catch (error) {
            loadError = String(error);
        }
    }

    $: rows = Object.values(records)
        .filter((record) => String(record.animal_number) === selected)
        .sort((a, b) => a.timestamp.localeCompare(b.timestamp));

    $: latest = rows.length ? rows[rows.length - 1] : null;

    $: recentRows = [...rows].reverse().slice(0, 40);

    $: if (chart && selected) {
        chart.data.labels = rows.map((record) => record.timestamp.replace('T', ' '));
        chart.data.datasets[0].data = rows.map((record) => litersOf(record));
        chart.data.datasets[0].label = `Milk yield (liters) — animal ${selected}`;
        chart.update();
    }

    onMount(async () => {
        chart = new Chart(canvasElement, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Milk yield (liters)',
                        data: [],
                        borderColor: '#2e8b57',
                        backgroundColor: 'rgba(46, 139, 87, 0.15)',
                        pointRadius: 2,
                        tension: 0.15,
                        fill: true
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { ticks: { maxTicksLimit: 12 } },
                    y: { title: { display: true, text: 'Liters' } }
                }
            }
        });
        await load();
        timer = setInterval(load, refreshMs);
    });

    onDestroy(() => {
        if (timer) {
            clearInterval(timer);
        }
        if (chart) {
            chart.destroy();
        }
    });
</script>

<main>
    <header>
        <h1>Milk Monitor</h1>
        <div class="toolbar">
            <label for="animal">Animal</label>
            <select id="animal" bind:value={selected}>
                {#each animals as animal}
                    <option value={animal}>{animal}</option>
                {/each}
            </select>
            {#if latest}
                <span class="light" style="background: {statusStyle(latest.status).color}"></span>
                <span class="status-text">
                    {statusStyle(latest.status).label}: {litersOf(latest)?.toFixed(2)} L
                    at {latest.timestamp.replace('T', ' ')}
                </span>
            {:else}
                <span class="status-text">Waiting for data</span>
            {/if}
            {#if loadError}
                <span class="error">{loadError}</span>
            {/if}
        </div>
    </header>

    <section class="content">
        <div class="chart">
            <canvas bind:this={canvasElement}></canvas>
        </div>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Liters</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {#each recentRows as record (record.id)}
                        <tr>
                            <td>{record.timestamp.replace('T', ' ')}</td>
                            <td>{litersOf(record)?.toFixed(2)}</td>
                            <td style="color: {statusStyle(record.status).color}">
                                {record.status}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
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
        max-width: 1200px;
        margin: 0 auto;
        padding: 1rem;
    }

    h1 {
        margin: 0 0 0.5rem;
        font-size: 1.4rem;
    }

    .toolbar {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        flex-wrap: wrap;
        margin-bottom: 1rem;
    }

    select {
        padding: 0.3rem 0.5rem;
        font-size: 1rem;
    }

    .light {
        width: 16px;
        height: 16px;
        border-radius: 50%;
        display: inline-block;
    }

    .status-text {
        font-size: 0.95rem;
    }

    .error {
        color: #c0392b;
        font-size: 0.9rem;
    }

    .content {
        display: grid;
        grid-template-columns: 2fr 1fr;
        gap: 1rem;
    }

    .chart {
        background: white;
        border-radius: 8px;
        padding: 1rem;
        height: 420px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    }

    .table-wrapper {
        background: white;
        border-radius: 8px;
        padding: 0.5rem;
        max-height: 420px;
        overflow-y: auto;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
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

    @media (max-width: 800px) {
        .content {
            grid-template-columns: 1fr;
        }
    }
</style>
