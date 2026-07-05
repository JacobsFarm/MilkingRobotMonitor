<script>
    import { onDestroy, onMount } from 'svelte';
    import Chart from 'chart.js/auto';

    export let type = 'bar';
    export let data;
    export let options = {};

    let canvas;
    let chart;

    onMount(() => {
        chart = new Chart(canvas, { type, data, options });
    });

    $: if (chart) {
        chart.data = data;
        chart.options = options;
        chart.update('none');
    }

    onDestroy(() => {
        if (chart) {
            chart.destroy();
        }
    });
</script>

<canvas bind:this={canvas}></canvas>
