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

let cachedToken = null;

async function graphql(endpoint, query, variables, token = null) {
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
        headers.Authorization = `Bearer ${token}`;
    }
    const response = await fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify({ query, variables })
    });
    const body = await response.json();
    if (body.errors) {
        throw new Error(JSON.stringify(body.errors));
    }
    return body.data;
}

async function authenticate(vault) {
    if (cachedToken) {
        return cachedToken;
    }
    const epassport = JSON.parse(readFileSync(vault.epassport_path, 'utf-8'));
    const data = await graphql(
        vault.endpoint,
        'mutation Login($ePassport: String!) { login(ePassport: $ePassport) { token } }',
        { ePassport: epassport.credential ?? '' }
    );
    cachedToken = data.login.token;
    return cachedToken;
}

async function fetchAllEVault(vault, basePath) {
    const token = await authenticate(vault);
    const data = await graphql(
        vault.endpoint,
        `query Fetch($ontology: String!, $term: String!) {
            findMetaEnvelopesBySearchTerm(ontology: $ontology, term: $term) { parsed }
        }`,
        { ontology: vault.ontology ?? basePath, term: basePath },
        token
    );
    return data.findMetaEnvelopesBySearchTerm.map((envelope) => envelope.parsed);
}
