<script>
    import { DAY_LABELS, fmt } from '$lib/format.js';

    export let matrix; // 7 rows (Mon..Sun) x 24 columns (0..23), null = no data
    export let unit = '';
    export let decimals = 0;

    $: maxValue = Math.max(0, ...matrix.flat().filter((v) => v != null));

    function cellColor(value) {
        if (value == null || maxValue === 0) {
            return '#f1f3f6';
        }
        const t = value / maxValue;
        // from light green to dark green
        const from = [232, 245, 238];
        const to = [23, 94, 56];
        const rgb = from.map((f, i) => Math.round(f + (to[i] - f) * t));
        return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
    }

    function textColor(value) {
        if (value == null || maxValue === 0) {
            return '#b6bdc7';
        }
        return value / maxValue > 0.55 ? '#ffffff' : '#1e2430';
    }
</script>

<div class="heatmap">
    <div class="corner"></div>
    {#each Array(24) as _, hour}
        <div class="hour-label">{hour}</div>
    {/each}
    {#each DAY_LABELS as day, d}
        <div class="day-label">{day}</div>
        {#each matrix[d] as value}
            <div
                class="cell"
                style="background: {cellColor(value)}; color: {textColor(value)}"
                title={value == null ? 'No milkings' : `${day} — ${fmt(value, decimals)} ${unit}`}
            >
                {value == null ? '' : fmt(value, decimals)}
            </div>
        {/each}
    {/each}
</div>

<style>
    .heatmap {
        display: grid;
        grid-template-columns: 2.2rem repeat(24, 1fr);
        gap: 2px;
        font-size: 0.62rem;
    }

    .corner {
        grid-column: 1;
    }

    .hour-label,
    .day-label {
        display: flex;
        align-items: center;
        justify-content: center;
        color: #6b7280;
        font-weight: 600;
    }

    .cell {
        aspect-ratio: 1.35;
        min-width: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 3px;
        overflow: hidden;
        white-space: nowrap;
    }
</style>
