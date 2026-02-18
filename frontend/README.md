# LLM Council MGA — Frontend

React 19 + Vite 7 frontend for the LLM Council multi-model deliberation platform.

## Quick Start

```bash
npm install
npm run dev          # http://localhost:5173
```

## Architecture

- **ThemeContext.jsx** — Day/Night mode provider (`localStorage` + `prefers-color-scheme`)
- **App.jsx** — Main shell, SSE handler, ARIA landmarks (`<nav>`, `<main>`, `<aside>`)
- **components/** — 18 UI components with per-component CSS
- **__tests__/** — 89 WCAG 3.0 accessibility tests (reusable via `a11y-utils.js`)

## Accessibility (WCAG 3.0)

Contrast verified with the **APCA** algorithm (Lc ≥ 90 body text, ≥ 75 large text, ≥ 45 non-text). Full dual-theme system (Day/Night), keyboard navigation, ARIA landmarks, dialog/listbox/menu patterns, skip-to-content, reduced motion, high contrast mode, CVD-safe palette, and 24×24 px minimum target sizes.

## Testing

```bash
npm test             # Run all 89 a11y tests
npm run test:a11y    # Verbose reporter
npm run test:watch   # Watch mode
```

## Scripts

| Script | Description |
|--------|-------------|
| `npm run dev` | Start Vite dev server (port 5173) |
| `npm run build` | Production build → `dist/` |
| `npm run preview` | Preview production build |
| `npm run lint` | ESLint |
| `npm test` | Vitest — run all tests |
| `npm run test:a11y` | Vitest — verbose accessibility tests |
| `npm run test:watch` | Vitest — watch mode |
