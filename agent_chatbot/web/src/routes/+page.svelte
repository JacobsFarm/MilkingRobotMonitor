<script>
    import { onMount, tick } from 'svelte';
    import Composer from '$lib/components/Composer.svelte';
    import Message from '$lib/components/Message.svelte';
    import { SessionExpired, ask, createSession, fetchHealth } from '$lib/api.js';

    // The page owns the transcript; every number in it was computed by
    // app/tools.py on the other side of /api/ask.
    let messages = [];
    let health = null;
    let startupError = '';
    let busy = false;
    let sessionId = null;
    let transcript;
    let composer;

    // Openers that show the range of the tool catalogue rather than the
    // easiest question -- one standing-analysis question, one comparison, one
    // lactation question, one about the vault itself.
    const SUGGESTIONS = [
        'Is anything wrong with the herd?',
        'Which cows dropped the most this month?',
        'How did cows between 60 and 100 days in milk develop over the last 3 months?',
        'What data is in the vault?'
    ];

    onMount(async () => {
        try {
            health = await fetchHealth();
            sessionId = await createSession();
            // The composer is disabled until there is a session, and a
            // disabled field cannot take focus -- so wait for that render.
            await tick();
            composer?.focus();
        } catch (error) {
            startupError = error.message;
        }
    });

    async function scrollDown() {
        await tick();
        transcript?.scrollTo({ top: transcript.scrollHeight, behavior: 'smooth' });
    }

    async function send(question) {
        if (busy || !sessionId) return;
        busy = true;

        messages = [
            ...messages,
            { role: 'user', content: question, calls: [] },
            { role: 'assistant', content: '', calls: [], running: true }
        ];
        const turn = messages.length - 1;
        scrollDown();

        const onTool = (name, args) => {
            messages[turn].calls = [...messages[turn].calls, { name, arguments: args }];
            messages = messages;
            scrollDown();
        };

        try {
            let answer;
            try {
                answer = await ask(sessionId, question, { onTool });
            } catch (error) {
                if (!(error instanceof SessionExpired)) throw error;
                // The server dropped the conversation (restart, or too many
                // tabs). Start a new one and ask again -- without the history,
                // which is the one thing worth saying out loud.
                sessionId = await createSession();
                messages[turn].calls = [];
                answer = await ask(sessionId, question, { onTool });
            }
            messages[turn].content = answer;
        } catch (error) {
            messages[turn].role = 'error';
            messages[turn].content = error.message;
        } finally {
            messages[turn].running = false;
            messages = messages;
            busy = false;
            scrollDown();
            await tick(); // the send button re-enables first, then takes focus
            composer?.focus();
        }
    }

    async function reset() {
        if (busy) return;
        try {
            sessionId = await createSession();
            messages = [];
            await tick();
            composer?.focus();
        } catch (error) {
            startupError = error.message;
        }
    }

    $: offline = health && !health.ollama_available;
    $: ready = Boolean(sessionId) && !startupError;
</script>

<!-- The title lives in app.html: there is one route, and with SSR off that is
     also what shows while the bundle loads. -->
<main>
    <div class="status-bar">
        {#if health}
            <span class="pill" class:warn={offline}>
                <span class="dot"></span>
                {offline ? 'Ollama not reachable' : health.model}
            </span>
            {#if health.data_until}
                <span class="meta">data up to {health.data_until}</span>
            {/if}
        {/if}
        {#if messages.length}
            <button class="reset" on:click={reset} disabled={busy}>New conversation</button>
        {/if}
    </div>

    {#if startupError}
        <div class="notice error">
            <strong>The chatbot server is not answering.</strong>
            <span>{startupError} — start it with <code>python serve.py</code>.</span>
        </div>
    {:else if offline}
        <div class="notice warn">
            <strong>Ollama is not running.</strong>
            <span>
                Start it with <code>ollama serve</code> and make sure the model is
                pulled: <code>ollama pull {health.model}</code>.
            </span>
        </div>
    {/if}

    <div class="transcript" bind:this={transcript}>
        {#if !messages.length}
            <section class="welcome">
                <h1 class="cc-display">Ask your herd</h1>
                <p class="lead">
                    Every answer is built from your own eVault. The model picks the
                    computations; Python does the arithmetic — so you can always see
                    which calculation produced which number.
                </p>

                <div class="suggestions">
                    {#each SUGGESTIONS as suggestion}
                        <button on:click={() => send(suggestion)} disabled={!ready || busy}>
                            {suggestion}
                        </button>
                    {/each}
                </div>

                {#if health?.collections?.length}
                    <p class="collections">
                        Reading {health.collections.length} collections:
                        {health.collections.join(', ')}
                    </p>
                {/if}
            </section>
        {/if}

        {#each messages as message}
            <Message
                role={message.role}
                content={message.content}
                calls={message.calls}
                running={message.running}
            />
        {/each}
    </div>

    <div class="composer-wrap">
        <Composer
            bind:this={composer}
            {busy}
            disabled={!ready}
            on:ask={(event) => send(event.detail)}
        />
    </div>
</main>

<style>
    main {
        flex: 1;
        display: flex;
        flex-direction: column;
        width: 100%;
        max-width: 860px;
        margin: 0 auto;
        padding: 1rem 1.25rem 1.5rem;
        min-height: 0;
    }

    .status-bar {
        display: flex;
        align-items: center;
        gap: 0.7rem;
        margin-bottom: 0.9rem;
        flex-wrap: wrap;
    }

    .pill {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.25rem 0.7rem;
        border-radius: var(--cc-radius-pill);
        background: #38693814;
        border: 1px solid #38693833;
        font-size: 0.76rem;
        font-weight: 500;
        color: var(--cc-green-dark);
    }

    .pill.warn {
        background: #bf810014;
        border-color: #bf810040;
        color: #8a5e00;
    }

    .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--cc-teal);
    }

    .pill.warn .dot {
        background: var(--cc-gold);
    }

    .meta {
        font-size: 0.76rem;
        color: var(--cc-ink-soft);
    }

    .reset {
        margin-left: auto;
        padding: 0.3rem 0.75rem;
        font: inherit;
        font-size: 0.76rem;
        font-weight: 500;
        color: var(--cc-green-dark);
        background: var(--cc-surface);
        border: 1px solid var(--cc-border);
        border-radius: var(--cc-radius-pill);
        cursor: pointer;
    }

    .reset:hover:not(:disabled) {
        border-color: var(--cc-green);
    }

    .reset:disabled {
        opacity: 0.5;
        cursor: default;
    }

    .notice {
        padding: 0.8rem 1rem;
        border-radius: var(--cc-radius);
        margin-bottom: 1rem;
        font-size: 0.85rem;
        line-height: 1.5;
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
    }

    .notice.warn {
        background: #fdf8ec;
        border: 1px solid #e6cf9a;
        color: #6b4a00;
    }

    .notice.error {
        background: #fdf5f3;
        border: 1px solid #e0bcb2;
        color: #7a2d1e;
    }

    .notice code {
        font-family: var(--cc-mono);
        font-size: 0.8rem;
        background: #00000010;
        padding: 0.05rem 0.3rem;
        border-radius: 4px;
    }

    .transcript {
        flex: 1;
        overflow-y: auto;
        padding-right: 0.3rem;
        min-height: 0;
    }

    .welcome {
        padding: 2.5rem 0 1rem;
        text-align: center;
    }

    h1 {
        margin: 0 0 0.6rem;
        font-size: 2.6rem;
        color: var(--cc-green);
    }

    .lead {
        margin: 0 auto 1.8rem;
        max-width: 52ch;
        font-size: 0.95rem;
        line-height: 1.6;
        color: var(--cc-ink-soft);
    }

    .suggestions {
        display: flex;
        flex-direction: column;
        gap: 0.55rem;
        max-width: 34rem;
        margin: 0 auto;
    }

    .suggestions button {
        padding: 0.7rem 1rem;
        text-align: left;
        font: inherit;
        font-size: 0.88rem;
        color: var(--cc-ink);
        background: var(--cc-surface);
        border: 1px solid var(--cc-border);
        border-radius: var(--cc-radius);
        cursor: pointer;
        transition: border-color 0.15s ease, transform 0.15s ease;
    }

    .suggestions button:hover:not(:disabled) {
        border-color: var(--cc-green);
        transform: translateX(2px);
    }

    .suggestions button:disabled {
        opacity: 0.55;
        cursor: default;
    }

    .collections {
        margin: 1.8rem 0 0;
        font-size: 0.76rem;
        color: var(--cc-ink-soft);
    }

    .composer-wrap {
        padding-top: 1rem;
    }

    @media (prefers-reduced-motion: reduce) {
        .suggestions button:hover:not(:disabled) { transform: none; }
    }

    @media (max-width: 640px) {
        main { padding: 0.75rem 0.85rem 1rem; }
        h1 { font-size: 2rem; }
        .welcome { padding-top: 1.5rem; }
    }
</style>
