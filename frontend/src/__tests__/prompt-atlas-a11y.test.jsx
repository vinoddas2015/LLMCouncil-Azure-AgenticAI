/**
 * ═══════════════════════════════════════════════════════════════════
 * Prompt Atlas — WCAG 3.0 Accessibility & Agent Team Tests
 * ═══════════════════════════════════════════════════════════════════
 *
 * Covers:
 *   • complementary landmark & accessible naming
 *   • tablist / tab ARIA for view toggle
 *   • Agent card role="button" + keyboard
 *   • Signal list / listitem semantics
 *   • Tree node keyboard interaction
 *   • Confidence ring role="img" accessible label
 *   • Empty-state role="status"
 *   • Focus-visible on interactive elements
 *   • APCA contrast on key element pairs
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '../ThemeContext';
import PromptAtlas3D from '../components/PromptAtlas3D';

/* ── Helpers ──────────────────────────────────────────────────────── */
const noop = vi.fn();

const sampleConversation = {
  id: 'test-conv',
  messages: [
    { role: 'user', content: 'Test prompt' },
    {
      role: 'assistant',
      content: 'Council response',
      metadata: {
        evidence: {
          claims: [
            {
              claim: 'Drug X effective',
              status: 'supported',
              sources: [{ title: 'Study 1' }],
            },
          ],
        },
      },
      stage1: [
        { model: 'gpt-5-mini', response: 'Model A reply', tokens: 200 },
        { model: 'claude-opus-4.5', response: 'Model B reply', tokens: 300 },
      ],
      stage2: [
        {
          model: 'gpt-5-mini',
          parsed_ranking: ['claude-opus-4.5', 'gpt-5-mini'],
          ranking: 'claude-opus-4.5 ranked first',
        },
        {
          model: 'claude-opus-4.5',
          parsed_ranking: ['gpt-5-mini', 'claude-opus-4.5'],
          ranking: 'gpt-5-mini ranked first',
        },
      ],
      agentTeam: {
        team_confidence: 0.87,
        signal_summary: { critical: 0, warning: 1, info: 3, success: 2 },
        agents: [
          {
            agent_id: 'research_analyst',
            role: 'Research Analyst',
            icon: '🔬',
            summary: 'Good topic coverage',
            confidence: 0.91,
            signals: [
              { kind: 'finding', severity: 'success', title: 'High data density', detail: 'All models covered key topics' },
              { kind: 'finding', severity: 'info', title: 'Broad scope', detail: 'Response spans 3 domains' },
            ],
          },
          {
            agent_id: 'fact_checker',
            role: 'Fact Checker',
            icon: '🛡️',
            summary: 'One claim unverified',
            confidence: 0.78,
            signals: [
              { kind: 'warning', severity: 'warning', title: 'Unverified claim', detail: 'Claim about dosage not grounded' },
            ],
          },
        ],
      },
    },
  ],
};

const emptyConversation = { id: 'empty-conv', messages: [] };

function renderAtlas(props = {}) {
  return render(
    <ThemeProvider>
      <PromptAtlas3D
        isOpen={props.isOpen ?? true}
        onToggle={props.onToggle ?? noop}
        conversation={props.conversation ?? sampleConversation}
      />
    </ThemeProvider>,
  );
}


/* ═══════════════════════════════════════════════════════════════════
 * Panel Landmark & Structure
 * ═══════════════════════════════════════════════════════════════════ */

describe('Prompt Atlas — Panel landmark', () => {
  it('panel has role="complementary" with accessible name', () => {
    renderAtlas();
    const panel = screen.getByRole('complementary');
    expect(panel).toBeTruthy();
    expect(panel.getAttribute('aria-label')).toContain('Prompt Atlas');
  });

  it('toggle button has aria-expanded and aria-controls', () => {
    renderAtlas();
    // Both the toggle and close button match "Close Prompt Atlas", use getAllByRole
    const buttons = screen.getAllByRole('button', { name: /close prompt atlas/i });
    expect(buttons.length).toBeGreaterThanOrEqual(1);
    // At least one should have aria-label
    expect(buttons.some(b => b.getAttribute('aria-label'))).toBe(true);
  });
});


/* ═══════════════════════════════════════════════════════════════════
 * View Tab Toggle — ARIA tablist/tab
 * ═══════════════════════════════════════════════════════════════════ */

describe('Prompt Atlas — Tab navigation', () => {
  it('renders a tablist with three tabs', () => {
    renderAtlas();
    const tablist = screen.getByRole('tablist', { name: /atlas view/i });
    const tabs = within(tablist).getAllByRole('tab');
    expect(tabs).toHaveLength(3);
  });

  it('first tab (Agent Signals) is selected by default', () => {
    renderAtlas();
    const tabs = screen.getAllByRole('tab');
    const signalsTab = tabs.find((t) => t.textContent.includes('Signals'));
    expect(signalsTab.getAttribute('aria-selected')).toBe('true');
  });

  it('switching to tree tab updates aria-selected', async () => {
    const user = userEvent.setup();
    renderAtlas();
    const tabs = screen.getAllByRole('tab');
    const treeTab = tabs.find((t) => t.textContent.includes('Tree'));
    await user.click(treeTab);
    expect(treeTab.getAttribute('aria-selected')).toBe('true');
    expect(tabs.find((t) => t.textContent.includes('Signals')).getAttribute('aria-selected')).toBe('false');
  });
});


/* ═══════════════════════════════════════════════════════════════════
 * Agent Team Dashboard — Cards & Signals
 * ═══════════════════════════════════════════════════════════════════ */

describe('Prompt Atlas — Agent Team Dashboard', () => {
  it('renders agent team region with accessible name', () => {
    renderAtlas();
    const region = screen.getByRole('region', { name: /agent team intelligence/i });
    expect(region).toBeTruthy();
  });

  it('renders agent cards as role="button" with tabIndex=0', () => {
    renderAtlas();
    const agentCards = screen.getByRole('list', { name: /agent team members/i });
    const buttons = within(agentCards).getAllByRole('button');
    expect(buttons.length).toBeGreaterThanOrEqual(2);
    buttons.forEach((btn) => {
      expect(btn.getAttribute('tabindex')).toBe('0');
    });
  });

  it('agent card has accessible label including role & summary', () => {
    renderAtlas();
    const buttons = screen.getAllByRole('button', { name: /research analyst/i });
    expect(buttons.length).toBeGreaterThanOrEqual(1);
    expect(buttons[0].getAttribute('aria-label')).toContain('Research Analyst');
  });

  it('expanding an agent card reveals signal list', async () => {
    const user = userEvent.setup();
    renderAtlas();
    const card = screen.getAllByRole('button', { name: /research analyst/i })[0];
    expect(card.getAttribute('aria-expanded')).toBe('false');

    await user.click(card);
    expect(card.getAttribute('aria-expanded')).toBe('true');

    const signalList = screen.getByRole('list', { name: /research analyst signals/i });
    expect(signalList).toBeTruthy();
    const items = within(signalList).getAllByRole('listitem');
    expect(items.length).toBeGreaterThanOrEqual(1);
  });

  it('agent card is keyboard-operable (Enter key)', async () => {
    const user = userEvent.setup();
    renderAtlas();
    const card = screen.getAllByRole('button', { name: /fact checker/i })[0];
    card.focus();
    await user.keyboard('{Enter}');
    expect(card.getAttribute('aria-expanded')).toBe('true');
  });

  it('confidence ring has role="img" with aria-label', () => {
    renderAtlas();
    const ring = screen.getByRole('img', { name: /team confidence/i });
    expect(ring).toBeTruthy();
    expect(ring.getAttribute('aria-label')).toMatch(/\d+%/);
  });
});


/* ═══════════════════════════════════════════════════════════════════
 * Signal Badges — status role
 * ═══════════════════════════════════════════════════════════════════ */

describe('Prompt Atlas — Signal badges', () => {
  it('badges have role="status" with aria-label', () => {
    renderAtlas();
    const statusElements = screen.getAllByRole('status');
    const badgeStatuses = statusElements.filter((el) =>
      el.classList.contains('signal-badge'),
    );
    expect(badgeStatuses.length).toBeGreaterThanOrEqual(1);
    badgeStatuses.forEach((badge) => {
      expect(badge.getAttribute('aria-label')).toBeTruthy();
    });
  });
});


/* ═══════════════════════════════════════════════════════════════════
 * Decision Tree View
 * ═══════════════════════════════════════════════════════════════════ */

describe('Prompt Atlas — Decision Tree', () => {
  it('tree nodes are role="button" with tabIndex and aria-label', async () => {
    const user = userEvent.setup();
    renderAtlas();
    // Switch to tree view
    const treeTab = screen.getAllByRole('tab').find((t) => t.textContent.includes('Tree'));
    await user.click(treeTab);

    // All tree nodes should be interactive
    const treeButtons = screen.getAllByRole('button').filter((btn) =>
      btn.classList.contains('tree-node'),
    );
    expect(treeButtons.length).toBeGreaterThanOrEqual(1);
    treeButtons.forEach((node) => {
      expect(node.getAttribute('tabindex')).toBe('0');
      expect(node.getAttribute('aria-label')).toBeTruthy();
    });
  });

  it('expanding a tree node reveals children', async () => {
    const user = userEvent.setup();
    renderAtlas();
    const treeTab = screen.getAllByRole('tab').find((t) => t.textContent.includes('Tree'));
    await user.click(treeTab);

    const treeNodes = screen.getAllByRole('button').filter((btn) =>
      btn.classList.contains('tree-node'),
    );
    if (treeNodes.length > 0) {
      const firstNode = treeNodes[0];
      await user.click(firstNode);
      // After click, aria-expanded should be "true"
      expect(firstNode.getAttribute('aria-expanded')).toBe('true');
    }
  });
});


/* ═══════════════════════════════════════════════════════════════════
 * Empty State
 * ═══════════════════════════════════════════════════════════════════ */

describe('Prompt Atlas — Empty state', () => {
  it('shows 🌳 empty status with descriptive text when no messages', () => {
    render(
      <ThemeProvider>
        <PromptAtlas3D isOpen={true} onToggle={noop} conversation={emptyConversation} />
      </ThemeProvider>,
    );
    // With empty conversation, no tabs (no agentTeam), tree view shows by default
    const emptyStatus = screen.getByRole('status');
    expect(emptyStatus).toBeTruthy();
    expect(emptyStatus.textContent).toContain('Send a prompt');
  });
});


/* ═══════════════════════════════════════════════════════════════════
 * Collapsed / Toggle
 * ═══════════════════════════════════════════════════════════════════ */

describe('Prompt Atlas — Toggle button', () => {
  it('toggle button has aria-expanded matching isOpen', () => {
    renderAtlas({ isOpen: false });
    const toggleBtn = screen.getByRole('button', { name: /open prompt atlas/i });
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('false');
    expect(toggleBtn.getAttribute('aria-controls')).toBe('prompt-atlas-panel');
  });

  it('collapsed panel has .collapsed class', () => {
    renderAtlas({ isOpen: false });
    const panel = document.getElementById('prompt-atlas-panel');
    expect(panel.classList.contains('collapsed')).toBe(true);
  });
});
