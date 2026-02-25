import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: process.env.PUBLIC_URL || '/',
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // Split heavy libraries into separate cacheable chunks
          '3dmol': ['3dmol'],
          'katex': ['katex', 'rehype-katex', 'remark-math'],
          'markdown': ['react-markdown', 'remark-gfm', 'rehype-raw'],
          'msal': ['@azure/msal-browser', '@azure/msal-react'],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/__tests__/setup.js',
    css: true,
    include: ['src/__tests__/**/*.{test,spec}.{js,jsx}'],
  },
  server: {
    // Proxy /api requests through Vite to the FastAPI backend.
    // This keeps all traffic on the same origin (localhost:5173),
    // which avoids Zscaler / corporate proxy interception of
    // cross-origin requests to localhost:8001.
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        // Needed for SSE streaming endpoints
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            // Ensure the connection stays alive for SSE
            proxyReq.setHeader('Connection', 'keep-alive');
          });
        },
      },
    },
  },
})
