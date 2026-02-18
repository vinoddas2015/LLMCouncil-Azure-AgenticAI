/**
 * ═══════════════════════════════════════════════════════════════════
 * WCAG 3.0 Accessibility Test Utilities  (reusable)
 * ═══════════════════════════════════════════════════════════════════
 *
 * Provides helpers that any component test can import to verify
 * WCAG 3.0 conformance: APCA contrast, focus management, ARIA
 * semantics, landmark structure, and keyboard operability.
 */

/**
 * Parse a hex colour string to { r, g, b }.
 */
export function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  const bigint = parseInt(clean, 16);
  return {
    r: (bigint >> 16) & 255,
    g: (bigint >> 8) & 255,
    b: bigint & 255,
  };
}

/**
 * sRGB → Y (linearised luminance) per APCA/WCAG 3.0.
 */
export function sRGBtoY({ r, g, b }) {
  const linearize = (c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126729 * linearize(r) + 0.7151522 * linearize(g) + 0.0721750 * linearize(b);
}

/**
 * APCA (Advanced Perceptual Contrast Algorithm) — Lc value.
 * Returns absolute value; negative means reversed polarity (light-on-dark).
 * Lc thresholds:
 *   ≥ 90  body text
 *   ≥ 75  large text / headlines
 *   ≥ 60  sub-text, placeholders
 *   ≥ 45  non-text (icons, focus rings, borders)
 *   ≥ 30  decorative / disabled UI
 */
export function calcAPCA(textHex, bgHex) {
  const txtY = sRGBtoY(hexToRgb(textHex));
  const bgY = sRGBtoY(hexToRgb(bgHex));

  const Ytext = txtY > 0 ? txtY : 0;
  const Ybg = bgY > 0 ? bgY : 0;

  // SAPC 0.0.98G-4g
  const normBG = Math.pow(Ybg, 0.56);
  const normTXT = Math.pow(Ytext, 0.57);

  let SAPC;
  if (Ybg > Ytext) {
    // dark text on light bg
    SAPC = (normBG - normTXT) * 1.14;
  } else {
    // light text on dark bg
    SAPC = (normBG - normTXT) * 1.14;
  }

  if (Math.abs(SAPC) < 0.1) return 0;
  return Math.abs(SAPC) * 100;
}

/**
 * Assert all interactive elements under `container` have accessible
 * names (via aria-label, aria-labelledby, or visible text content).
 */
export function assertAccessibleNames(container) {
  const interactives = container.querySelectorAll(
    'button, [role="button"], [role="switch"], a[href], input, select, textarea, [role="menuitem"]'
  );
  const failures = [];
  interactives.forEach((el) => {
    const name =
      el.getAttribute('aria-label') ||
      el.getAttribute('aria-labelledby') ||
      el.getAttribute('title') ||
      el.textContent?.trim();
    if (!name) {
      failures.push({
        element: el.tagName,
        outerHTML: el.outerHTML.slice(0, 120),
      });
    }
  });
  return failures;
}

/**
 * Assert that all images under `container` have non-empty alt text
 * or are explicitly decorative (alt="", role="presentation").
 */
export function assertImageAlts(container) {
  const imgs = container.querySelectorAll('img');
  const failures = [];
  imgs.forEach((img) => {
    const alt = img.getAttribute('alt');
    const role = img.getAttribute('role');
    if (alt === null && role !== 'presentation' && role !== 'none') {
      failures.push({ src: img.src, outerHTML: img.outerHTML.slice(0, 120) });
    }
  });
  return failures;
}

/**
 * Assert that headings are in descending order (h1 → h2 → h3 …).
 * Returns an array of violations.
 */
export function assertHeadingOrder(container) {
  const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
  const violations = [];
  let prevLevel = 0;
  headings.forEach((h) => {
    const level = parseInt(h.tagName[1], 10);
    if (level > prevLevel + 1 && prevLevel !== 0) {
      violations.push({
        expected: `h${prevLevel + 1}`,
        got: h.tagName.toLowerCase(),
        text: h.textContent?.trim(),
      });
    }
    prevLevel = level;
  });
  return violations;
}

/**
 * Verify minimum tap/click target size (WCAG 2.5.8 — 24 × 24 CSS px).
 * Note: jsdom doesn't compute layout, so we check the CSS min-height/width
 * properties or data attributes. This is a lightweight heuristic.
 */
export function assertMinTargetSize(container, minPx = 24) {
  const targets = container.querySelectorAll('button, [role="button"], [role="switch"], a[href]');
  const belowMinimum = [];
  targets.forEach((el) => {
    // In jsdom we can't reliably measure rendered size;
    // check that explicit inline dimensions aren't below threshold.
    const w = el.style?.width ? parseInt(el.style.width) : null;
    const h = el.style?.height ? parseInt(el.style.height) : null;
    if ((w !== null && w < minPx) || (h !== null && h < minPx)) {
      belowMinimum.push({ element: el.outerHTML.slice(0, 120), width: w, height: h });
    }
  });
  return belowMinimum;
}

/**
 * Collect all ARIA landmark roles from the container.
 */
export function getLandmarks(container) {
  const roles = ['banner', 'navigation', 'main', 'complementary', 'contentinfo', 'region', 'search'];
  const found = {};
  roles.forEach((role) => {
    const els = container.querySelectorAll(`[role="${role}"]`);
    // also check semantic elements
    const semanticMap = {
      banner: 'header',
      navigation: 'nav',
      main: 'main',
      complementary: 'aside',
      contentinfo: 'footer',
      search: 'search',
    };
    const semantic = container.querySelectorAll(semanticMap[role] || 'never-match');
    found[role] = els.length + semantic.length;
  });
  return found;
}
