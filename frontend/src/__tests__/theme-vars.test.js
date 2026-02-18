/**
 * ═══════════════════════════════════════════════════════════════════
 * CSS Variable — Theme Completeness Tests
 * ═══════════════════════════════════════════════════════════════════
 *
 * Ensures both [data-theme="dark"] and [data-theme="light"] define
 * ALL required CSS custom properties so no component falls back to
 * an unthemed or invisible state.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

const indexCss = readFileSync(
  resolve(__dirname, '..', 'index.css'),
  'utf-8'
);

const REQUIRED_VARS = [
  '--bg-primary',
  '--bg-secondary',
  '--bg-surface',
  '--bg-elevated',
  '--bg-input',
  '--text-primary',
  '--text-secondary',
  '--text-muted',
  '--accent-primary',
  '--accent-hover',
  '--accent-strong',
  '--border-default',
  '--border-accent',
  '--border-focus',
  '--error',
  '--warning',
  '--success',
];

/**
 * Extract the CSS block for a given selector.
 */
function extractBlock(css, selector) {
  const escapedSelector = selector.replace(/[[\]"]/g, '\\$&');
  const re = new RegExp(`${escapedSelector}\\s*\\{([^}]+)\\}`, 's');  
  const match = css.match(re);
  return match ? match[1] : '';
}

describe('CSS variable completeness — Dark theme', () => {
  const rootBlock = extractBlock(indexCss, ':root');
  const darkBlock = extractBlock(indexCss, '[data-theme="dark"]');
  const combined = rootBlock + darkBlock;

  REQUIRED_VARS.forEach((v) => {
    it(`defines ${v}`, () => {
      expect(combined).toContain(v);
    });
  });
});

describe('CSS variable completeness — Light theme', () => {
  const lightBlock = extractBlock(indexCss, '[data-theme="light"]');

  REQUIRED_VARS.forEach((v) => {
    it(`defines ${v}`, () => {
      expect(lightBlock).toContain(v);
    });
  });
});

describe('Reduced motion media query', () => {
  it('index.css contains prefers-reduced-motion rule', () => {
    expect(indexCss).toContain('prefers-reduced-motion: reduce');
  });
});

describe('Forced-colors / High Contrast support', () => {
  it('index.css contains forced-colors media query', () => {
    expect(indexCss).toContain('forced-colors: active');
  });
});

describe('Focus visible rule', () => {
  it('index.css defines :focus-visible outline with border-focus var', () => {
    expect(indexCss).toContain(':focus-visible');
    expect(indexCss).toContain('var(--border-focus)');
  });
});
