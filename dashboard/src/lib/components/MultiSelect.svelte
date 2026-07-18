<script>
    export let label;
    export let options = []; // [{ value, label }]
    export let selected = []; // bind: selected values, empty = all
    export let allLabel = 'All';
    export let searchable = false;

    let open = false;
    let search = '';
    let root;

    $: normalizedSearch = search.trim().toLowerCase();
    $: visible = options.filter(
        (option) => !normalizedSearch || option.label.toLowerCase().includes(normalizedSearch)
    );

    $: summary =
        selected.length === 0
            ? allLabel
            : selected.length === 1
              ? options.find((o) => o.value === selected[0])?.label ?? selected[0]
              : `${selected.length} selected`;

    function toggle(value) {
        selected = selected.includes(value)
            ? selected.filter((v) => v !== value)
            : [...selected, value];
    }

    function clear() {
        selected = [];
        search = '';
    }

    function handleClickOutside(event) {
        if (open && root && !root.contains(event.target)) {
            open = false;
        }
    }
</script>

<svelte:window on:click={handleClickOutside} />

<div class="multiselect" bind:this={root}>
    <span class="field-label">{label}</span>
    <button type="button" class="trigger" class:active={selected.length > 0} on:click={() => (open = !open)}>
        <span class="summary">{summary}</span>
        <span class="caret">{open ? '▴' : '▾'}</span>
    </button>
    {#if open}
        <div class="panel">
            {#if searchable}
                <input class="search" type="text" placeholder="Search…" bind:value={search} />
            {/if}
            <button type="button" class="clear" on:click={clear} disabled={selected.length === 0}>
                {allLabel}
            </button>
            <div class="options">
                {#each visible as option (option.value)}
                    <label class="option">
                        <input
                            type="checkbox"
                            checked={selected.includes(option.value)}
                            on:change={() => toggle(option.value)}
                        />
                        <span>{option.label}</span>
                    </label>
                {:else}
                    <p class="empty">No results</p>
                {/each}
            </div>
        </div>
    {/if}
</div>

<style>
    .multiselect {
        position: relative;
        display: flex;
        flex-direction: column;
        gap: 0.35rem;
        min-width: 11rem;
    }

    .field-label {
        font-weight: 600;
        font-size: 0.85rem;
    }

    .trigger {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.5rem;
        padding: 0.45rem 0.7rem;
        font-size: 0.9rem;
        border: 1px solid #d1d5db;
        border-radius: 6px;
        background: #f9fafb;
        cursor: pointer;
        text-align: left;
    }

    .trigger:hover {
        background: #eef2f6;
    }

    .trigger.active {
        border-color: #2e8b57;
        background: #e8f5ee;
    }

    .summary {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .caret {
        color: #6b7280;
        font-size: 0.75rem;
    }

    .panel {
        position: absolute;
        top: 100%;
        left: 0;
        z-index: 20;
        margin-top: 0.3rem;
        width: 100%;
        min-width: 13rem;
        background: white;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        box-shadow: 0 6px 18px rgba(0, 0, 0, 0.12);
        padding: 0.5rem;
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }

    .search {
        padding: 0.35rem 0.5rem;
        font-size: 0.85rem;
        border: 1px solid #d1d5db;
        border-radius: 5px;
    }

    .clear {
        padding: 0.3rem 0.5rem;
        font-size: 0.8rem;
        border: 1px solid #d1d5db;
        border-radius: 5px;
        background: #f9fafb;
        cursor: pointer;
    }

    .clear:disabled {
        opacity: 0.5;
        cursor: default;
    }

    .options {
        max-height: 14rem;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
    }

    .option {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.25rem 0.3rem;
        font-size: 0.88rem;
        border-radius: 4px;
        cursor: pointer;
    }

    .option:hover {
        background: #f1f5f3;
    }

    .empty {
        margin: 0.3rem;
        font-size: 0.8rem;
        color: #9aa3af;
    }
</style>
