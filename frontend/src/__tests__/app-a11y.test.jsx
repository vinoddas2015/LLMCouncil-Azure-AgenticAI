/**
 * ═══════════════════════════════════════════════════════════════════
 * App Layout — WCAG 3.0 Structural & Landmark Tests
 * ═══════════════════════════════════════════════════════════════════
 *
 * Verifies ARIA landmarks, skip-navigation, heading hierarchy,
 * accessible names on interactive elements, and image alt texts.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ThemeProvider } from '../ThemeContext';
import App from '../App';
import {
  assertAccessibleNames,
  assertImageAlts,
  assertHeadingOrder,
  getLandmarks,
} from './a11y-utils';

// Mock the API module to avoid network calls
vi.mock('../api', () => ({
  api: {
    listConversations: vi.fn().mockResolvedValue([]),
    getConversation: vi.fn().mockResolvedValue({ messages: [] }),
    createConversation: vi.fn().mockResolvedValue({ id: 'test', created_at: new Date().toISOString() }),
    getModels: vi.fn().mockResolvedValue({ models: [], defaults: { council_models: [], chairman_model: '' } }),
    sendMessageStream: vi.fn(),
    enhancePrompt: vi.fn(),
    exportConversation: vi.fn(),
    deleteConversation: vi.fn(),
  },
}));

function renderApp() {
  return render(
    <ThemeProvider>
      <App />
    </ThemeProvider>
  );
}

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme');
  window.localStorage.clear();
});

describe('App — WCAG 3.0 Landmarks', () => {
  it('contains a <nav> landmark', () => {
    const { container } = renderApp();
    const landmarks = getLandmarks(container);
    expect(landmarks.navigation).toBeGreaterThanOrEqual(1);
  });

  it('contains a <main> landmark', () => {
    const { container } = renderApp();
    const landmarks = getLandmarks(container);
    expect(landmarks.main).toBeGreaterThanOrEqual(1);
  });

  it('contains an <aside> (complementary) landmark', () => {
    const { container } = renderApp();
    const landmarks = getLandmarks(container);
    expect(landmarks.complementary).toBeGreaterThanOrEqual(1);
  });

  it('has a region for emergency controls', () => {
    const { container } = renderApp();
    const region = container.querySelector('[role="region"][aria-label*="Emergency"]') ||
                   container.querySelector('[role="region"][aria-label*="emergency"]');
    expect(region).toBeInTheDocument();
  });
});

describe('App — Skip Navigation', () => {
  it('renders a skip-to-content link', () => {
    renderApp();
    const skipLink = screen.getByText(/skip to main content/i);
    expect(skipLink).toBeInTheDocument();
    expect(skipLink).toHaveAttribute('href', '#main-content');
  });

  it('links to an element that exists in the DOM', () => {
    const { container } = renderApp();
    const target = container.querySelector('#main-content');
    expect(target).toBeInTheDocument();
  });
});

describe('App — Accessible Names', () => {
  it('every interactive element has an accessible name', () => {
    const { container } = renderApp();
    const failures = assertAccessibleNames(container);
    expect(failures).toEqual([]);
  });
});

describe('App — Image Accessibility', () => {
  it('all images have alt text or are marked decorative', () => {
    const { container } = renderApp();
    const failures = assertImageAlts(container);
    expect(failures).toEqual([]);
  });
});

describe('App — Heading Hierarchy', () => {
  it('headings are in descending order without skipping levels', () => {
    const { container } = renderApp();
    const violations = assertHeadingOrder(container);
    expect(violations).toEqual([]);
  });
});
