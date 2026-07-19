import adapter from '@sveltejs/adapter-static';

// Static, not adapter-node like the dashboard: this frontend has no server
// logic of its own. Every answer comes from the Python server (app/server.py),
// which also serves this build in production -- one process, one origin.
export default {
    kit: {
        adapter: adapter({ fallback: 'index.html' }),
        prerender: { entries: [] }
    }
};
