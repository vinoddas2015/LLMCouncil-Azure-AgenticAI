/**
 * ThemeToggle — Accessible Day / Night mode toggle switch.
 *
 * WCAG 3.0 compliant:
 *   - role="switch" with aria-checked
 *   - Visible focus ring (APCA Lc ≥ 45 on focus indicator)
 *   - Screen-reader label describes current state
 *   - Keyboard operable (Space / Enter)
 *   - prefers-reduced-motion honoured via CSS
 */
import { useTheme } from '../ThemeContext';
import './ThemeToggle.css';

export default function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <button
      className={`theme-toggle ${isDark ? 'theme-toggle--dark' : 'theme-toggle--light'}`}
      onClick={toggleTheme}
      role="switch"
      aria-checked={isDark}
      aria-label={isDark ? 'Switch to Day mode' : 'Switch to Night mode'}
      title={isDark ? 'Switch to Day mode' : 'Switch to Night mode'}
    >
      <span className="theme-toggle__track" aria-hidden="true">
        <span className="theme-toggle__icons">
          <span className="theme-toggle__icon theme-toggle__icon--sun">☀️</span>
          <span className="theme-toggle__icon theme-toggle__icon--moon">🌙</span>
        </span>
        <span className="theme-toggle__thumb" />
      </span>
      <span className="theme-toggle__label">
        {isDark ? 'Night' : 'Day'}
      </span>
    </button>
  );
}
