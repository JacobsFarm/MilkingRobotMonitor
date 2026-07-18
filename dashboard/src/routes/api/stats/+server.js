import { json } from '@sveltejs/kit';
import { loadSettings } from '$lib/server/settings.js';
import { collectionStatus } from '$lib/server/vault.js';
import { getMilkingStats, normalizeFilters } from '$lib/server/aggregate.js';

// Statistieken-API: de browser stuurt zijn filters als query-parameters en
// krijgt kant-en-klare aggregaten terug (berekend en gememoized op de server).
// Met `sig` (de vorige signature) antwoordt de server `unchanged: true` zonder
// payload zolang dataset én filters gelijk bleven.
export async function GET({ url }) {
    const settings = loadSettings();
    const filters = normalizeFilters(url.searchParams);
    const { signature, stats } = await getMilkingStats(settings, filters);

    // Laadvoortgang over alle collecties samen, voor de UI-banner.
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
