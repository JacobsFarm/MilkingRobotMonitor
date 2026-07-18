import { json } from '@sveltejs/kit';
import { loadSettings } from '$lib/server/settings.js';
import { collectionStatus } from '$lib/server/vault.js';
import { getMilkingStats, normalizeFilters } from '$lib/server/aggregate.js';

// Statistics API: the browser sends its filters as query parameters and gets
// ready-made aggregates back (computed and memoized on the server). With `sig`
// (the previous signature) the server answers `unchanged: true` without a
// payload for as long as dataset and filters stayed the same.
export async function GET({ url }) {
    const settings = loadSettings();
    const filters = normalizeFilters(url.searchParams);
    const { signature, stats } = await getMilkingStats(settings, filters);

    // Load progress across all collections together, for the UI banner.
    const statuses = [
        settings.base_path ?? 'milking_controle_data',
        settings.feed_path ?? 'feed_distribution_data',
        settings.production_path ?? 'milking_production_data'
    ].map((path) => collectionStatus(settings, path));

    const base = {
        signature,
        progress: {
            complete: statuses.every((s) => s.complete),
            loaded: statuses.reduce((acc, s) => acc + (s.loaded ?? 0), 0)
        },
        refresh_ms: settings.refresh_ms ?? 30000,
        fetched_at: new Date().toISOString()
    };

    if (url.searchParams.get('sig') === signature) {
        return json({ ...base, unchanged: true });
    }
    return json({ ...base, unchanged: false, stats });
}
