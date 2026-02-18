/**
 * ═══════════════════════════════════════════════════════════════════
 * Sidebar — Accessibility Tests
 * ═══════════════════════════════════════════════════════════════════
 *
 * Covers ARIA listbox/option, keyboard navigation, menu semantics,
 * theme toggle presence, and accessible names.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '../ThemeContext';
import Sidebar from '../components/Sidebar';
import { assertAccessibleNames } from './a11y-utils';

const mockConversations = [
  { id: 'c1', title: 'First chat', message_count: 3, created_at: '2026-01-01' },
  { id: 'c2', title: 'Second chat', message_count: 7, created_at: '2026-01-02' },
];

const noop = vi.fn();

function renderSidebar(props = {}) {
  return render(
    <ThemeProvider>
      <Sidebar
        conversations={props.conversations ?? mockConversations}
        currentConversationId={props.currentConversationId ?? 'c1'}
        onSelectConversation={props.onSelectConversation ?? noop}
        onNewConversation={props.onNewConversation ?? noop}
        onOpenSettings={props.onOpenSettings ?? noop}
        onExportConversation={props.onExportConversation ?? noop}
        onDeleteConversation={props.onDeleteConversation ?? noop}
      />
    </ThemeProvider>
  );
}

describe('Sidebar — ARIA listbox / option', () => {
  it('conversation list has role="listbox"', () => {
    renderSidebar();
    const listbox = screen.getByRole('listbox');
    expect(listbox).toBeInTheDocument();
  });

  it('each conversation has role="option"', () => {
    renderSidebar();
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(2);
  });

  it('active conversation has aria-selected="true"', () => {
    renderSidebar({ currentConversationId: 'c1' });
    const options = screen.getAllByRole('option');
    const active = options.find((o) => o.getAttribute('aria-selected') === 'true');
    expect(active).toBeTruthy();
    expect(active.textContent).toContain('First chat');
  });
});

describe('Sidebar — keyboard navigation', () => {
  it('conversation items are focusable with Tab', () => {
    renderSidebar();
    const options = screen.getAllByRole('option');
    options.forEach((opt) => {
      expect(opt.getAttribute('tabindex')).toBe('0');
    });
  });

  it('selects conversation on Enter key', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    renderSidebar({ onSelectConversation: onSelect });
    const option = screen.getAllByRole('option')[1];
    option.focus();
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith('c2');
  });

  it('selects conversation on Space key', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    renderSidebar({ onSelectConversation: onSelect });
    const option = screen.getAllByRole('option')[0];
    option.focus();
    await user.keyboard(' ');
    expect(onSelect).toHaveBeenCalledWith('c1');
  });
});

describe('Sidebar — menu accessibility', () => {
  it('menu button has aria-haspopup="menu"', () => {
    renderSidebar();
    const menuBtns = screen.getAllByLabelText(/actions for/i);
    expect(menuBtns.length).toBeGreaterThan(0);
    menuBtns.forEach((btn) => {
      expect(btn).toHaveAttribute('aria-haspopup', 'menu');
    });
  });

  it('menu items have role="menuitem" when expanded', async () => {
    const user = userEvent.setup();
    renderSidebar();
    const menuBtn = screen.getAllByLabelText(/actions for/i)[0];
    await user.click(menuBtn);
    const menuitems = screen.getAllByRole('menuitem');
    expect(menuitems.length).toBeGreaterThanOrEqual(2);
  });
});

describe('Sidebar — ThemeToggle presence', () => {
  it('renders the Day/Night toggle', () => {
    renderSidebar();
    const toggle = screen.getByRole('switch');
    expect(toggle).toBeInTheDocument();
  });
});

describe('Sidebar — accessible names', () => {
  it('all interactive elements have accessible names', () => {
    const { container } = renderSidebar();
    const failures = assertAccessibleNames(container);
    expect(failures).toEqual([]);
  });
});

describe('Sidebar — empty state', () => {
  it('shows a status message when no conversations exist', () => {
    renderSidebar({ conversations: [] });
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent(/no conversations/i);
  });
});
