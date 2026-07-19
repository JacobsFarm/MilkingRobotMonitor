<script>
    import { formatArguments, toolLabel } from '$lib/tools.js';

    // The computations behind one answer, in the order they ran.
    export let calls = [];
    export let running = false;

    let open = false;

    // While the answer is still being worked out the trace is the only thing
    // on screen, so it opens itself; once the answer lands it collapses back
    // out of the way, still one click from being checked.
    $: if (running) open = true;
    $: if (!running && !calls.length) open = false;
</script>

{#if calls.length}
    <div class="trace" class:running>
        <button class="summary" on:click={() => (open = !open)} aria-expanded={open}>
            <span class="chevron" class:open>▸</span>
            <span class="count">
                {calls.length}
                {calls.length === 1 ? 'computation' : 'computations'}
            </span>
            <span class="note">every figure below comes from these</span>
        </button>

        {#if open}
            <ol class="calls">
                {#each calls as call, index}
                    <li class:active={running && index === calls.length - 1}>
                        <span class="label">{toolLabel(call.name)}</span>
                        <code>{call.name}({formatArguments(call.arguments)})</code>
                    </li>
                {/each}
            </ol>
        {/if}
    </div>
{/if}

<style>
    .trace {
        border-left: 3px solid var(--cc-gold);
        background: var(--cc-page-alt);
        border-radius: 0 var(--cc-radius) var(--cc-radius) 0;
        margin-bottom: 0.6rem;
        overflow: hidden;
    }

    .summary {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        width: 100%;
        padding: 0.5rem 0.8rem;
        background: none;
        border: none;
        cursor: pointer;
        font: inherit;
        text-align: left;
        color: var(--cc-green-deep);
    }

    .summary:hover {
        background: #38693810;
    }

    .chevron {
        color: var(--cc-gold);
        transition: transform 0.15s ease;
        font-size: 0.75rem;
    }

    .chevron.open {
        transform: rotate(90deg);
    }

    .count {
        font-weight: 700;
        font-size: 0.82rem;
    }

    .note {
        font-size: 0.78rem;
        color: var(--cc-ink-soft);
    }

    .calls {
        margin: 0;
        padding: 0 0.8rem 0.7rem 2rem;
        display: flex;
        flex-direction: column;
        gap: 0.45rem;
    }

    .calls li {
        font-size: 0.8rem;
    }

    .label {
        display: block;
        font-weight: 500;
        color: var(--cc-green-dark);
    }

    code {
        font-family: var(--cc-mono);
        font-size: 0.74rem;
        color: var(--cc-ink-soft);
        word-break: break-word;
    }

    /* The call still running gets the pulse, so a long tool round looks like
       progress rather than a freeze. */
    .calls li.active .label::after {
        content: '';
        display: inline-block;
        width: 6px;
        height: 6px;
        margin-left: 0.4rem;
        border-radius: 50%;
        background: var(--cc-gold);
        animation: pulse 1s ease-in-out infinite;
    }

    @keyframes pulse {
        0%, 100% { opacity: 0.25; }
        50% { opacity: 1; }
    }

    @media (prefers-reduced-motion: reduce) {
        .calls li.active .label::after { animation: none; opacity: 1; }
        .chevron { transition: none; }
    }
</style>
