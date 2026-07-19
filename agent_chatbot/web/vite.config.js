import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// The Python chatbot server has no CORS headers on purpose, so in development
// /api is proxied to it and everything stays same-origin -- exactly as it is
// in production, where that same server also serves this build.
export default defineConfig({
    plugins: [sveltekit()],
    server: {
        host: true,
        port: 5174,
        proxy: {
            '/api': {
                target: 'http://127.0.0.1:8420',
                changeOrigin: true
            }
        }
    }
});
