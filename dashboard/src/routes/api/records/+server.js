import { json } from '@sveltejs/kit';
import { createHash } from 'node:crypto';
import { loadSettings } from '$lib/server/settings.js';
import { fetchAll } from '$lib/server/vault.js';

// Light server cache: this stops several pollers or tabs from each draining the
// full eVault. The TTL is short relative to the client's refresh interval.
let cache = { at: 0, records: null, signature: null };

// Fingerprint of the dataset based on the record ids present. Changes as soon
// as a milking is added or disappears; milkings are immutable events, so
// in-place changes do not occur.
function signatureOf(records) {
    const ids = records
        .map((record) => record.id)
        .sort()
        .join('|');
    return createHash('sha1').update(ids).digest('hex');
}

export async function GET({ url }) {
    const settings = loadSettings();
    const ttlMs = settings.cache_ttl_ms ?? 15000;
    const now = Date.now();

    if (!cache.records || now - cache.at > ttlMs) {
        const records = await fetchAll(settings, settings.base_path);
        cache = { at: now, records, signature: signatureOf(records) };
    }

    const base = {
        signature: cache.signature,
        refresh_ms: settings.refresh_ms ?? 30000,
        yield_divisor: settings.yield_divisor ?? 1000,
        fetched_at: new Date(cache.at).toISOString()
    };

    // Client already has exactly this dataset: skip the payload, which saves
    // transfer as well as a full recalculation in the browser.
    const clientSignature = url.searchParams.get('sig');
    if (clientSignature && clientSignature === cache.signature) {
        return json({ ...base, unchanged: true, records: [] });
    }

    return json({ ...base, unchanged: false, records: cache.records });
}
