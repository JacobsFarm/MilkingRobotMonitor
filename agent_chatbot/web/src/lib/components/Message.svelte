<script>
    import ToolTrace from './ToolTrace.svelte';

    // One turn. `role` is 'user' | 'assistant' | 'error'; assistant turns carry
    // the tool calls that produced them.
    export let role = 'assistant';
    export let content = '';
    export let calls = [];
    export let running = false;
</script>

<article class="turn {role}">
    {#if role !== 'user'}
        <div class="who cc-display">{role === 'error' ? 'Problem' : 'Melkmonitor'}</div>
    {/if}

    <div class="bubble">
        {#if role === 'assistant'}
            <ToolTrace {calls} {running} />
        {/if}

        {#if content}
            <!-- The system prompt asks the model for plain text, so it is
                 rendered as plain text: no markdown parsing, no HTML, nothing
                 a model can emit that turns into markup. -->
            <p class="text">{content}</p>
        {:else if running}
            <p class="thinking">
                <span></span><span></span><span></span>
                Working it out…
            </p>
        {/if}
    </div>
</article>

<style>
    .turn {
        display: flex;
        flex-direction: column;
        margin-bottom: 1.4rem;
    }

    .turn.user {
        align-items: flex-end;
    }

    .who {
        font-size: 0.8rem;
        color: var(--cc-green);
        margin-bottom: 0.3rem;
    }

    .turn.error .who {
        color: #a13b2a;
    }

    .bubble {
        max-width: 90%;
        padding: 0.85rem 1.05rem;
        border-radius: var(--cc-radius);
        background: var(--cc-surface);
        border: 1px solid var(--cc-border);
        box-shadow: var(--cc-shadow-soft);
    }

    .turn.user .bubble {
        background: var(--cc-green);
        border-color: var(--cc-green);
        color: #f6f9f6;
        border-bottom-right-radius: 4px;
        max-width: 80%;
    }

    .turn.assistant .bubble {
        border-bottom-left-radius: 4px;
    }

    .turn.error .bubble {
        background: #fdf5f3;
        border-color: #e0bcb2;
        color: #7a2d1e;
    }

    .text {
        margin: 0;
        /* Answers name cows line by line; the model's own line breaks are the
           structure, so they are kept. */
        white-space: pre-wrap;
        line-height: 1.55;
        font-size: 0.95rem;
    }

    .thinking {
        display: flex;
        align-items: center;
        gap: 0.25rem;
        margin: 0;
        font-size: 0.9rem;
        color: var(--cc-ink-soft);
    }

    .thinking span {
        width: 5px;
        height: 5px;
        border-radius: 50%;
        background: var(--cc-green);
        animation: bounce 1.2s ease-in-out infinite;
    }

    .thinking span:nth-child(2) { animation-delay: 0.15s; }
    .thinking span:nth-child(3) { animation-delay: 0.3s; margin-right: 0.4rem; }

    @keyframes bounce {
        0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
        40% { opacity: 1; transform: translateY(-3px); }
    }

    @media (prefers-reduced-motion: reduce) {
        .thinking span { animation: none; opacity: 0.6; }
    }

    @media (max-width: 640px) {
        .bubble, .turn.user .bubble { max-width: 100%; }
    }
</style>
