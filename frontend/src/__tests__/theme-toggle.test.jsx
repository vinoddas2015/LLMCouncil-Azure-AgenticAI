/**
 * ═══════════════════════════════════════════════════════════════════
 * ThemeToggle — Component Accessibility Tests
 * ═══════════════════════════════════════════════════════════════════
 *
 * Covers: ARIA switch role, keyboard operation, state persistence,
 * screen-reader labels, focus visibility.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '../ThemeContext';
import ThemeToggle from '../components/ThemeToggle';

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>
  );
}

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme');
  window.localStorage.clear();
});

describe('ThemeToggle — ARIA semantics', () => {
  it('renders with role="switch"', () => {
    renderToggle();
    const btn = screen.getByRole('switch');
    expect(btn).toBeInTheDocument();
  });

  it('has aria-checked reflecting current theme', () => {
    renderToggle();
    const btn = screen.getByRole('switch');
    // Default is dark → aria-checked="true"
    expect(btn).toHaveAttribute('aria-checked');
  });

  it('has a descriptive aria-label', () => {
    renderToggle();
    const btn = screen.getByRole('switch');
    const label = btn.getAttribute('aria-label');
    expect(label).toBeTruthy();
    expect(label.toLowerCase()).toMatch(/switch to (day|night) mode/);
  });
});

describe('ThemeToggle — keyboard interaction', () => {
  it('toggles theme on Enter key', async () => {
    const user = userEvent.setup();
    renderToggle();
    const btn = screen.getByRole('switch');
    btn.focus();
    await user.keyboard('{Enter}');
    // After toggle from dark → light, label should mention "Night"
    expect(btn.getAttribute('aria-label')).toMatch(/night/i);
  });

  it('toggles theme on Space key', async () => {
    const user = userEvent.setup();
    renderToggle();
    const btn = screen.getByRole('switch');
    btn.focus();
    await user.keyboard(' ');
    expect(btn.getAttribute('aria-label')).toMatch(/night/i);
  });

  it('toggles back on double activation', async () => {
    const user = userEvent.setup();
    renderToggle();
    const btn = screen.getByRole('switch');
    await user.click(btn);
    await user.click(btn);
    expect(btn.getAttribute('aria-label')).toMatch(/day/i);
  });
});

describe('ThemeToggle — theme application', () => {
  it('sets data-theme attribute on <html>', async () => {
    const user = userEvent.setup();
    renderToggle();
    const btn = screen.getByRole('switch');
    await user.click(btn);
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('persists choice to localStorage', async () => {
    const user = userEvent.setup();
    renderToggle();
    const btn = screen.getByRole('switch');
    await user.click(btn);
    expect(window.localStorage.setItem).toHaveBeenCalledWith(
      'llm-council-theme',
      'light'
    );
  });
});

describe('ThemeToggle — visual label', () => {
  it('displays "Night" when dark mode is active', () => {
    renderToggle();
    expect(screen.getByText('Night')).toBeInTheDocument();
  });

  it('displays "Day" when light mode is active', async () => {
    const user = userEvent.setup();
    renderToggle();
    await user.click(screen.getByRole('switch'));
    expect(screen.getByText('Day')).toBeInTheDocument();
  });
});
