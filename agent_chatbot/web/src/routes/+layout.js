// A static build with no server half of its own: everything the page shows
// comes from the Python server at runtime, so there is nothing to render or
// prerender ahead of time.
export const ssr = false;
export const prerender = false;
