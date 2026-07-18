import { json } from '@sveltejs/kit';
import { loadSettings } from '$lib/server/settings.js';
import { fetchAll } from '$lib/server/vault.js';

const SEVERITY_RANK = { high: 0, medium: 1 };

// Insights accumulate in the vault (one batch per analysis day, the agent
// dedups within a day). The dashboard shows the most recent analysis run;
// older batches stay in the vault as history.
export async function GET() {
    const settings = loadSettings();
    const insightsPath = settings.insights_path ?? 'milking_insights';
    let all = [];
    try {
        all = await fetchAll(settings, insightsPath);
    } catch {
        all = [];
    }

    const dated = all.filter((record) => record && record.id && typeof record.created_at === 'string');
    if (!dated.length) {
        return json({ insights: [], analysis_date: null, total: all.length });
    }

    // Elke analyse-run stempelt al zijn bevindingen met dezelfde created_at, en
    // nieuw geüploade data levert een nieuwe run op. Filteren op de exacte
    // laatste created_at geeft dus precies één batch — de meest recente.
    const latestRun = dated.reduce(
        (max, record) => (record.created_at > max ? record.created_at : max),
        ''
    );
    const byId = new Map();
    for (const record of dated) {
        if (record.created_at === latestRun) {
            byId.set(record.id, record);
        }
    }
    const latest = [...byId.values()].sort(
        (a, b) =>
            (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9) ||
            String(a.type).localeCompare(String(b.type)) ||
            String(a.title).localeCompare(String(b.title))
    );

    return json({
        insights: latest,
        analysis_date: latestRun.slice(0, 10),
        analysed_at: latestRun,
        total: all.length
    });
}
