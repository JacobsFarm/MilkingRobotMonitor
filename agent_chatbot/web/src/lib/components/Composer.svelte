<script>
    import { createEventDispatcher, tick } from 'svelte';

    export let busy = false;
    export let disabled = false;
    export let placeholder = 'Ask about your herd…';

    const dispatch = createEventDispatcher();
    let value = '';
    let field;

    // Grows with the question instead of scrolling inside three lines; farmers
    // ask long, specific questions.
    async function autosize() {
        await tick();
        if (!field) return;
        field.style.height = 'auto';
        field.style.height = `${Math.min(field.scrollHeight, 180)}px`;
    }

    function submit() {
        const question = value.trim();
        if (!question || busy || disabled) return;
        dispatch('ask', question);
        value = '';
        autosize();
    }

    function onKeydown(event) {
        // Enter sends, Shift+Enter breaks the line -- the convention every
        // chat app has trained people into.
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submit();
        }
    }

    export function focus() {
        field?.focus();
    }
</script>

<form class="composer" on:submit|preventDefault={submit}>
    <textarea
        bind:this={field}
        bind:value
        on:input={autosize}
        on:keydown={onKeydown}
        {placeholder}
        {disabled}
        rows="1"
        aria-label="Your question"
    ></textarea>

    <button type="submit" disabled={busy || disabled || !value.trim()} aria-label="Send question">
        {#if busy}
            <span class="spinner" aria-hidden="true"></span>
        {:else}
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path d="M3 20.5 21 12 3 3.5 3 10l12 2-12 2z" fill="currentColor" />
            </svg>
        {/if}
    </button>
</form>

<p class="hint">
    Enter sends · Shift+Enter adds a line · ask in any language
</p>

<style>
    .composer {
        display: flex;
        align-items: flex-end;
        gap: 0.5rem;
        padding: 0.45rem 0.45rem 0.45rem 1rem;
        background: var(--cc-surface);
        border: 1px solid var(--cc-border);
        border-radius: var(--cc-radius-lg);
        box-shadow: var(--cc-shadow-soft);
        transition: border-color 0.15s ease;
    }

    .composer:focus-within {
        border-color: var(--cc-green);
    }

    textarea {
        flex: 1;
        border: none;
        outline: none;
        resize: none;
        background: transparent;
        font-family: var(--cc-body);
        font-size: 0.95rem;
        line-height: 1.5;
        color: var(--cc-ink);
        padding: 0.5rem 0;
        max-height: 180px;
    }

    textarea::placeholder {
        color: var(--cc-ink-soft);
    }

    button {
        flex: 0 0 auto;
        display: grid;
        place-items: center;
        width: 40px;
        height: 40px;
        border: none;
        border-radius: 50%;
        background: var(--cc-green);
        color: #f6f9f6;
        cursor: pointer;
        transition: background 0.15s ease;
    }

    button:hover:not(:disabled) {
        background: var(--cc-green-dark);
    }

    button:disabled {
        background: var(--cc-border);
        cursor: default;
    }

    .spinner {
        width: 16px;
        height: 16px;
        border: 2px solid #ffffff66;
        border-top-color: #f6f9f6;
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .hint {
        margin: 0.5rem 0 0;
        text-align: center;
        font-size: 0.75rem;
        color: var(--cc-ink-soft);
    }

    @media (prefers-reduced-motion: reduce) {
        .spinner { animation-duration: 2s; }
    }
</style>
