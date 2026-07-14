// This dashboard is a live, client-polled view of the eVault (data is fetched in
// onMount and refreshed on an interval), so there is nothing meaningful to render
// on the server. Disabling SSR makes that explicit: no server-side fetch, no
// hydration mismatch, and it silences SvelteKit's "fetch during SSR" hint.
export const ssr = false;
