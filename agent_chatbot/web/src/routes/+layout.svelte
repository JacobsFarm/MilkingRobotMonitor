<script>
    import '$lib/theme.css';

    // The frame: CowCatcher's green bar on top, ink footer below, everything
    // in between is the conversation.
</script>

<div class="shell">
    <nav>
        <a class="logo cc-display" href="/">
            Melkmonitor <span class="accent">Chat</span>
        </a>
        <span class="claim">Your barn · your data · your questions</span>
    </nav>

    <slot />

    <footer>
        <div class="footer-inner">
            <div>
                <p class="brand cc-display">Melkmonitor</p>
                <p class="tagline">
                    Ask your eVault anything. Every figure is computed in Python,
                    worded by a model that runs on your own machine.
                </p>
            </div>
            <p class="local">
                <span class="dot"></span>
                Nothing leaves the farm
            </p>
        </div>
    </footer>
</div>

<style>
    .shell {
        display: flex;
        flex-direction: column;
        min-height: 100vh;
    }

    nav {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
        padding: 1rem 2rem;
        background: var(--cc-green);
        box-shadow: var(--cc-shadow);
        position: sticky;
        top: 0;
        z-index: 100;
    }

    .logo {
        font-size: 1.5rem;
        color: #f6f9f6;
        text-decoration: none;
        letter-spacing: 1px;
    }

    .accent {
        color: var(--cc-gold);
    }

    .claim {
        font-size: 0.78rem;
        color: #f6f9f6b3;
        letter-spacing: 0.02em;
    }

    footer {
        background: var(--cc-ink);
        border-top: 4px solid var(--cc-green);
        margin-top: auto;
    }

    .footer-inner {
        max-width: 1100px;
        margin: 0 auto;
        padding: 2rem;
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 2rem;
        flex-wrap: wrap;
    }

    .brand {
        margin: 0 0 0.3rem;
        font-size: 1.8rem;
        color: var(--cc-gold);
    }

    .tagline {
        margin: 0;
        max-width: 46ch;
        font-size: 0.85rem;
        line-height: 1.5;
        color: #f6f9f6b3;
    }

    .local {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        margin: 0;
        font-size: 0.8rem;
        font-weight: 500;
        color: #f6f9f6;
    }

    .dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--cc-teal);
    }

    @media (max-width: 640px) {
        nav {
            padding: 0.85rem 1rem;
        }

        .claim {
            display: none;
        }
    }
</style>
