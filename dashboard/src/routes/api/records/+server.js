import { json } from '@sveltejs/kit';
import { loadSettings } from '$lib/server/settings.js';
import { fetchAll } from '$lib/server/vault.js';

export async function GET() {
    const settings = loadSettings();
    const records = await fetchAll(settings, settings.base_path);
    return json({
        records,
        refresh_ms: settings.refresh_ms ?? 5000,
        yield_divisor: settings.yield_divisor ?? 1000
    });
}
