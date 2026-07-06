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
// Flow (verified against docs.w3ds.metastate.foundation and the prototype
// repo's web3-adapter EVaultClient, 2026-07):
// 1. Resolve the eVault endpoint of the configured w3id via the Registry:
//    GET {registry_url}/resolve?w3id=@... -> eVault URI; GraphQL at /graphql.
// 2. Obtain a platform token: POST {registry_url}/platforms/certification
//    with { platform } -> { token, expiresAt }. Refreshed near expiry.
// 3. Every GraphQL call carries "Authorization: Bearer <token>" and
//    "X-ENAME: <w3id>" headers.
// 4. Fetch via the cursor-paginated metaEnvelopes query, filtered on the
//    ontology (the W3ID/schemaId of the pre-registered JSON Schema, mapped
//    per logical collection in settings under vault.schema_ids).
// ---------------------------------------------------------------------------

const TOKEN_REFRESH_MARGIN_MS = 5 * 60 * 1000;
const PAGE_SIZE = 500;

const FETCH_QUERY = `
    query MetaEnvelopes($filter: MetaEnvelopeFilterInput, $first: Int, $after: String) {
        metaEnvelopes(filter: $filter, first: $first, after: $after) {
            edges { node { parsed } }
            pageInfo { hasNextPage endCursor }
        }
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
    // TODO(evault): verify the exact response shape of /resolve against a
    // test registry; the adapter reads the eVault URI from it.
    const uri = body.uri ?? body.evault ?? body.endpoint;
    if (!uri) {
        throw new Error(`Registry resolve returned no eVault URI for ${vault.w3id}`);
    }
    const trimmed = uri.replace(/\/$/, '');
    cachedEndpoint = trimmed.endsWith('/graphql') ? trimmed : `${trimmed}/graphql`;
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
    for (let attempt = 1; attempt <= 2; attempt++) {
        const headers = {
            Authorization: `Bearer ${await getToken(vault)}`,
            'X-ENAME': vault.w3id
        };
        let body;
        try {
            body = await httpJson(endpoint, { body: { query, variables }, headers });
        } catch (error) {
            if ((error.status === 401 || error.status === 403) && attempt === 1) {
                cachedToken = null; // token expired or revoked: fetch a fresh one
                continue;
            }
            throw error;
        }
        if (body.errors) {
            throw new Error(JSON.stringify(body.errors));
        }
        return body.data;
    }
}

function schemaFor(vault, basePath) {
    const logical = basePath.split('/', 1)[0];
    const schemaId = vault.schema_ids?.[logical];
    if (!schemaId) {
        throw new Error(
            `No schema id configured for '${logical}'. Register the JSON Schema in the ` +
                'Ontology service and add its W3ID under vault.schema_ids in settings.json.'
        );
    }
    return schemaId;
}

async function fetchAllEVault(vault, basePath) {
    const schemaId = schemaFor(vault, basePath);
    const records = [];
    let after = null;
    for (;;) {
        const data = await graphql(vault, FETCH_QUERY, {
            // TODO(evault): verify the filter field name (ontologyId vs ontology)
            // against the deployed eVault schema.
            filter: { ontologyId: schemaId },
            first: PAGE_SIZE,
            after
        });
        const connection = data.metaEnvelopes;
        records.push(...connection.edges.map((edge) => edge.node.parsed));
        if (!connection.pageInfo?.hasNextPage) {
            return records;
        }
        after = connection.pageInfo.endCursor;
    }
}
