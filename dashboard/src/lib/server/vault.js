import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';

export async function fetchAll(settings, basePath) {
    if (settings.vault?.mode === 'evault') {
        return fetchAllEVault(settings.vault, basePath);
    }
    return fetchAllLocal(settings.vault, basePath);
}

function fetchAllLocal(vault, basePath) {
    const directory = path.join(vault.local_path, ...basePath.split('/'));
    if (!existsSync(directory)) {
        return [];
    }
    const records = [];
    const files = readdirSync(directory)
        .filter((name) => name.endsWith('.json'))
        .sort();
    for (const name of files) {
        try {
            const content = JSON.parse(
                readFileSync(path.join(directory, name), 'utf-8')
            );
            records.push(...Object.values(content));
        } catch {
            continue;
        }
    }
    return records;
}

// ---------------------------------------------------------------------------
// MetaState W3DS eVault
//
// Flow (verified 2026-07 against the live production registry/eVault via
// GraphQL introspection, plus the prototype repo's web3-adapter EVaultClient):
// 1. Resolve the eVault endpoint of the configured w3id via the Registry:
//    GET {registry_url}/resolve?w3id=@... -> { uri }; the GraphQL endpoint is
//    always /graphql on that URI's origin.
// 2. Obtain a platform token: POST {registry_url}/platforms/certification
//    with { platform } -> { token } (optional expiresAt). Any platform name is
//    accepted; refreshed near expiry / on 401.
// 3. Every GraphQL call carries "Authorization: Bearer <token>" and
//    "X-ENAME: <w3id>" headers.
// 4. Fetch via the cursor-paginated metaEnvelopes query, filtered on the
//    ontologyId (the schema identifier — a plain logical name or a registered
//    Ontology W3ID — mapped per collection in settings under vault.schema_ids).
// ---------------------------------------------------------------------------

const TOKEN_REFRESH_MARGIN_MS = 5 * 60 * 1000;
// The eVault caps `first` at 100 per page regardless of what we ask, so a large
// collection means hundreds of paged requests against a rate-limited server.
const PAGE_SIZE = 100;
const MAX_RETRIES = 8;
const MAX_BACKOFF_MS = 30000;
// Hoe vaak een volledig geladen collectie op nieuwe records wordt gecontroleerd.
// Die controle is één request (zie COUNT_QUERY); alleen als de telling verandert
// volgt de dure herlezing. Daarom kan dit kort zijn: nieuwe uploads zijn snel
// zichtbaar zonder de server te belasten.
const FULL_REFRESH_MS = 2 * 60 * 1000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Server-side cache so the browser never triggers a fresh full page-through on
// every poll. Keyed by collection (basePath). Filled progressively on first
// load and atomically swapped on later refreshes.
const recordCache = new Map(); // basePath -> { records, fetchedAt, complete }
const refreshing = new Set(); // basePath currently being paged

const FETCH_QUERY = `
    query MetaEnvelopes($filter: MetaEnvelopeFilterInput, $first: Int, $after: String) {
        metaEnvelopes(filter: $filter, first: $first, after: $after) {
            edges { node { parsed } }
            pageInfo { hasNextPage endCursor }
        }
    }
`;

// Eén request die zegt hoeveel records de collectie telt. Alleen fetchen wat
// nieuw is kan niet: het filter kent geen datumveld en de volgorde loopt op de
// van de inhoud afgeleide UUID van elke envelope, dus nieuwe records komen
// verspreid door de reeks te staan in plaats van achteraan (geverifieerd tegen
// productie — hervatten vanaf een bewaarde cursor zou ze overslaan). Tellen is
// daarom de goedkope manier om te weten of een volledige herlezing nodig is.
const COUNT_QUERY = `
    query CountMetaEnvelopes($filter: MetaEnvelopeFilterInput) {
        metaEnvelopes(filter: $filter, first: 1) { totalCount }
    }
`;

let cachedEndpoint = null;
let cachedToken = null;
let tokenExpiresAt = null; // ms since epoch, or null

async function httpJson(url, { body, headers = {} } = {}) {
    const response = await fetch(url, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: body === undefined ? undefined : JSON.stringify(body)
    });
    if (!response.ok) {
        const error = new Error(`Request to ${url} failed (${response.status})`);
        error.status = response.status;
        const retryAfter = response.headers.get('retry-after');
        if (retryAfter) {
            error.retryAfter = Number(retryAfter);
        }
        throw error;
    }
    return response.json();
}

async function resolveEndpoint(vault) {
    if (cachedEndpoint) {
        return cachedEndpoint;
    }
    const registry = vault.registry_url.replace(/\/$/, '');
    const body = await httpJson(`${registry}/resolve?w3id=${encodeURIComponent(vault.w3id)}`);
    // Resolve response: { ename, uri, evault, ... }; "uri" is the eVault origin
    // (e.g. "http://host:4000"). "evault" is an id, not a URL.
    const uri = body.uri;
    if (!uri) {
        throw new Error(`Registry resolve returned no eVault URI for ${vault.w3id}`);
    }
    // GraphQL always lives at /graphql on the eVault's origin, ignoring any path
    // the resolved URI may carry (matches the web3-adapter EVaultClient).
    cachedEndpoint = new URL('/graphql', uri).toString();
    return cachedEndpoint;
}

async function getToken(vault) {
    const now = Date.now();
    if (cachedToken && (tokenExpiresAt === null || now < tokenExpiresAt - TOKEN_REFRESH_MARGIN_MS)) {
        return cachedToken;
    }
    const registry = vault.registry_url.replace(/\/$/, '');
    const body = await httpJson(`${registry}/platforms/certification`, {
        body: { platform: vault.platform ?? 'melkmonitor' }
    });
    cachedToken = body.token;
    let expiresAt = body.expiresAt ? Number(body.expiresAt) : null;
    // The adapter treats expiresAt as a Unix timestamp; normalize seconds to ms.
    if (expiresAt !== null && expiresAt < 1e12) {
        expiresAt *= 1000;
    }
    tokenExpiresAt = expiresAt;
    return cachedToken;
}

async function graphql(vault, query, variables) {
    const endpoint = await resolveEndpoint(vault);
    let tokenRefreshed = false;
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
        const headers = {
            Authorization: `Bearer ${await getToken(vault)}`,
            'X-ENAME': vault.w3id
        };
        let body;
        try {
            body = await httpJson(endpoint, { body: { query, variables }, headers });
        } catch (error) {
            if ((error.status === 401 || error.status === 403) && !tokenRefreshed) {
                cachedToken = null; // token expired or revoked: fetch a fresh one
                tokenRefreshed = true;
                continue;
            }
            // 429 Too Many Requests / 5xx are transient: back off and retry.
            const transient = error.status === 429 || (error.status >= 500 && error.status < 600);
            if (transient && attempt < MAX_RETRIES - 1) {
                // Honour the server's Retry-After (seconds) when given; else back off.
                const waitMs = Number.isFinite(error.retryAfter)
                    ? error.retryAfter * 1000 + 500
                    : Math.min(2 ** attempt * 1000, MAX_BACKOFF_MS);
                await sleep(waitMs);
                continue;
            }
            throw error;
        }
        if (body.errors) {
            throw new Error(JSON.stringify(body.errors));
        }
        return body.data;
    }
    throw new Error('GraphQL request failed after retries');
}

function schemaFor(vault, basePath) {
    // Zonder expliciete mapping is de collectienaam zelf de ontology-id (een
    // vaste string werkt — store en fetch moeten hem alleen eens zijn). Een in
    // de Ontology service geregistreerde W3ID mappen onder vault.schema_ids is
    // pas nodig voor interoperabiliteit met andere W3DS-platforms.
    const logical = basePath.split('/', 1)[0];
    return vault.schema_ids?.[logical] ?? logical;
}

// Laadstatus van een collectie, voor voortgangsweergave in de UI terwijl de
// achtergrond-fetch nog door de eVault-pagina's loopt.
export function collectionStatus(settings, basePath) {
    if (settings.vault?.mode !== 'evault') {
        return { complete: true, loaded: null, refreshing: false, fetchedAt: null };
    }
    const entry = recordCache.get(basePath);
    return {
        complete: entry?.complete ?? false,
        loaded: entry ? entry.records.length : 0,
        refreshing: refreshing.has(basePath),
        fetchedAt: entry?.fetchedAt ?? null
    };
}

// Returns immediately with whatever is cached (possibly a partial first load or
// an empty array), and kicks off a background page-through when the cache is
// missing, still filling, or stale. The browser polls on an interval, so the
// dashboard fills in progressively without any request blocking for minutes.
function fetchAllEVault(vault, basePath) {
    const entry = recordCache.get(basePath);
    const age = entry ? Date.now() - entry.fetchedAt : Infinity;
    const needsRefresh =
        !entry || !entry.complete || (entry.complete && age > FULL_REFRESH_MS);
    if (needsRefresh && !refreshing.has(basePath)) {
        refreshing.add(basePath);
        refreshEVault(vault, basePath).finally(() => refreshing.delete(basePath));
    }
    return entry ? entry.records : [];
}

async function refreshEVault(vault, basePath) {
    const existing = recordCache.get(basePath);
    const hadComplete = existing?.complete === true;
    const records = [];
    let after = null;
    try {
        const schemaId = schemaFor(vault, basePath);

        // Een volledige herlezing is honderden requests tegen een gelimiteerde
        // server. Als de telling gelijk is aan wat we al hebben, is de cache nog
        // exact en slaan we die hele ronde over.
        if (hadComplete) {
            const counted = await graphql(vault, COUNT_QUERY, {
                filter: { ontologyId: schemaId }
            });
            const total = counted.metaEnvelopes?.totalCount;
            if (Number.isFinite(total) && total === existing.records.length) {
                recordCache.set(basePath, { ...existing, fetchedAt: Date.now() });
                return;
            }
        }

        for (;;) {
            const data = await graphql(vault, FETCH_QUERY, {
                filter: { ontologyId: schemaId },
                first: PAGE_SIZE,
                after
            });
            const connection = data.metaEnvelopes;
            records.push(...connection.edges.map((edge) => edge.node.parsed));
            const done = !connection.pageInfo?.hasNextPage;
            // First load: publish partial results so the UI fills as it pages.
            // Re-load of an already-complete set: swap in only when fully done,
            // so the dashboard never briefly shows a shrunken dataset.
            if (!hadComplete || done) {
                recordCache.set(basePath, {
                    records: records.slice(),
                    fetchedAt: Date.now(),
                    complete: done
                });
            }
            if (done) {
                return;
            }
            after = connection.pageInfo.endCursor;
        }
    } catch (error) {
        console.error(`eVault refresh for '${basePath}' failed:`, error.message);
        // Leave any existing cache in place; a later poll retries.
    }
}
