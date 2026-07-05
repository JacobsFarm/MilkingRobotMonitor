import { json } from '@sveltejs/kit';
import { createHash } from 'node:crypto';
import { loadSettings } from '$lib/server/settings.js';
import { fetchAll } from '$lib/server/vault.js';

// Lichte server-cache: meerdere pollers of tabbladen trekken zo niet elk de
// volledige eVault leeg. De TTL is kort t.o.v. het ververs-interval van de client.
let cache = { at: 0, records: null, signature: null };

// Vingerafdruk van de dataset op basis van de aanwezige record-id's. Verandert
// zodra er een melking bijkomt of verdwijnt; melkingen zijn onveranderlijke
// gebeurtenissen dus wijzigingen-in-plaats komen niet voor.
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

    // Client heeft al exact deze dataset: sla de payload over, scheelt transfer
    // én een volledige herberekening in de browser.
    const clientSignature = url.searchParams.get('sig');
    if (clientSignature && clientSignature === cache.signature) {
        return json({ ...base, unchanged: true, records: [] });
    }

    return json({ ...base, unchanged: false, records: cache.records });
}
