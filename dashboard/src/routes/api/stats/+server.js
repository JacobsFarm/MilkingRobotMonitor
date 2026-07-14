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

    const base = {
        signature,
        // Laadvoortgang van de eVault-achtergrondfetch, voor de UI-banner.
        progress: collectionStatus(settings, settings.base_path ?? 'milking_controle_data'),
        refresh_ms: settings.refresh_ms ?? 30000,
        fetched_at: new Date().toISOString()
    };

    if (url.searchParams.get('sig') === signature) {
        return json({ ...base, unchanged: true });
    }
    return json({ ...base, unchanged: false, stats });
}
