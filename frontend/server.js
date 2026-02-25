/**
 * Minimal Express server to serve the Vite-built SPA on Azure App Service.
 * 
 * Azure App Service (Node.js) runs this as the entry point.
 * All non-file routes are redirected to index.html for client-side routing.
 */
const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 8080;

// Serve static files from the Vite build output
app.use(express.static(path.join(__dirname, 'dist'), {
  // Cache static assets aggressively (Vite uses content hashing)
  maxAge: '1y',
  immutable: true,
}));

// Don't cache index.html itself (so deployments take effect immediately)
app.get('/', (req, res) => {
  res.set('Cache-Control', 'no-cache, no-store, must-revalidate');
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

// SPA fallback: serve index.html for all non-file routes
// Express 5 requires named wildcard params (path-to-regexp v8)
app.get('/{*path}', (req, res) => {
  res.set('Cache-Control', 'no-cache, no-store, must-revalidate');
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`LLM Council Frontend running on port ${PORT}`);
});
