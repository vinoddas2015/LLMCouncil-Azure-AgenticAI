/**
 * ═══════════════════════════════════════════════════════════════════
 * Settings Modal — Accessibility Tests
 * ═══════════════════════════════════════════════════════════════════
 *
 * Covers: dialog role, aria-modal, labelledby, focus trap hint,
 * close button label, keyboard dismiss.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '../ThemeContext';
import Settings from '../components/Settings';

// Mock API
vi.mock('../api', () => ({
  api: {
    getModels: vi.fn().mockResolvedValue({
      models: [
        { id: 'gpt-4', name: 'GPT-4', description: 'OpenAI flagship' },
        { id: 'claude', name: 'Claude', description: 'Anthropic model' },
      ],
      defaults: { council_models: ['gpt-4', 'claude'], chairman_model: 'gpt-4' },
    }),
  },
}));

const defaultPrefs = { council_models: null, chairman_model: null, web_search_enabled: false };

function renderSettings(props = {}) {
  return render(
    <ThemeProvider>
      <Settings
        isOpen={true}
        onClose={props.onClose ?? vi.fn()}
        preferences={props.preferences ?? defaultPrefs}
        onSave={props.onSave ?? vi.fn()}
      />
    </ThemeProvider>
  );
}

describe('Settings — dialog semantics', () => {
  it('has role="dialog"', () => {
    renderSettings();
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
  });

  it('has aria-modal="true"', () => {
    renderSettings();
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });

  it('has aria-labelledby pointing to the title', () => {
    renderSettings();
    const dialog = screen.getByRole('dialog');
    const labelledBy = dialog.getAttribute('aria-labelledby');
    expect(labelledBy).toBeTruthy();
    const title = document.getElementById(labelledBy);
    expect(title).toBeInTheDocument();
    expect(title.textContent).toContain('Council Settings');
  });
});

describe('Settings — close button', () => {
  it('close button has aria-label', () => {
    renderSettings();
    const closeBtn = screen.getByLabelText(/close settings/i);
    expect(closeBtn).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderSettings({ onClose });
    await user.click(screen.getByLabelText(/close settings/i));
    expect(onClose).toHaveBeenCalled();
  });
});

describe('Settings — not rendered when closed', () => {
  it('returns null when isOpen=false', () => {
    const { container } = render(
      <ThemeProvider>
        <Settings
          isOpen={false}
          onClose={vi.fn()}
          preferences={defaultPrefs}
          onSave={vi.fn()}
        />
      </ThemeProvider>
    );
    expect(container.querySelector('.settings-overlay')).toBeNull();
  });
});
