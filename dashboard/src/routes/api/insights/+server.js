import { json } from '@sveltejs/kit';
import { loadSettings } from '$lib/server/settings.js';
import { fetchAll } from '$lib/server/vault.js';

export async function GET() {
    const settings = loadSettings();
    const insightsPath = settings.insights_path ?? 'milking_insights';
    let insights = [];
    try {
        insights = await fetchAll(settings, insightsPath);
    } catch {
        insights = [];
    }
    return json({ insights });
}
