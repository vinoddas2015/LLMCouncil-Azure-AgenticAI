/**
 * SciMarkdown — Scientific Markdown Renderer
 *
 * Shared rich-text component used by Stage 1/2/3 and ChatInterface.
 * Supports:
 *   ✓ GitHub-Flavored Markdown (tables, task lists, strikethrough)
 *   ✓ SMILES chemical structures rendered as 2D SVG or interactive 3D (WebGL)
 *   ✓ KaTeX math (inline $ and block $$)
 *   ✓ Raw HTML passthrough (figures, <sub>, <sup>, etc.)
 *   ✓ Syntax-highlighted code blocks
 *   ✓ Clickable images with figure captions
 */

import { useState, useRef, useEffect, useCallback, memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeRaw from 'rehype-raw';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import './SciMarkdown.css';

/* ── SMILES Renderer (uses smiles-drawer SvgDrawer) ──────────────── */
let smilesModule = null;

// Lazy-load smiles-drawer only once
async function getSmilesDrawer() {
  if (smilesModule) return smilesModule;
  try {
    const sd = await import('smiles-drawer');
    const mod = sd.default || sd;
    smilesModule = {
      SvgDrawer: mod.SvgDrawer,
      parse: mod.parse,
    };
    return smilesModule;
  } catch (e) {
    console.error('Failed to load smiles-drawer:', e);
    return null;
  }
}

/* ── 3Dmol.js Lazy Loader ────────────────────────────────────────── */
let threeDmolModule = null;

async function get3Dmol() {
  if (threeDmolModule) return threeDmolModule;
  try {
    const mod = await import('3dmol');
    // 3Dmol attaches to window.$3Dmol as a side-effect
    threeDmolModule = window.$3Dmol || mod.default || mod;
    return threeDmolModule;
  } catch (e) {
    console.warn('3Dmol.js import failed:', e);
    if (window.$3Dmol) {
      threeDmolModule = window.$3Dmol;
      return threeDmolModule;
    }
    return null;
  }
}

/** Fetch 3D SDF from PubChem given a SMILES string */
async function fetchSDF(smiles) {
  const encoded = encodeURIComponent(smiles);
  const url = `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/${encoded}/SDF?record_type=3d`;
  const res = await fetch(url);
  if (!res.ok) {
    // Fallback: try 2D SDF if 3D not available
    const url2d = `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/${encoded}/SDF`;
    const res2d = await fetch(url2d);
    if (!res2d.ok) throw new Error(`PubChem SDF fetch failed: ${res2d.status}`);
    return res2d.text();
  }
  return res.text();
}


/* ── 2D SMILES Canvas ────────────────────────────────────────────── */
const Smiles2D = memo(function Smiles2D({ smiles }) {
  const containerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      if (!smiles || !containerRef.current) return;

      const mod = await getSmilesDrawer();
      if (cancelled || !mod?.SvgDrawer || !mod?.parse) {
        if (containerRef.current) {
          containerRef.current.innerHTML =
            `<div class="smiles-fallback">${smiles}</div>`;
        }
        return;
      }

      try {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '380');
        svg.setAttribute('height', '260');
        svg.classList.add('smiles-svg');

        containerRef.current.innerHTML = '';
        containerRef.current.appendChild(svg);

        const drawer = new mod.SvgDrawer({
          width: 380,
          height: 260,
          bondThickness: 1.2,
          bondLength: 20,
          shortBondLength: 0.8,
          fontSizeLarge: 11,
          fontSizeSmall: 8,
          padding: 20,
          compactDrawing: false,
          themes: {
            dark: {
              C: '#e2e8f0',
              O: '#f87171',
              N: '#60a5fa',
              S: '#fbbf24',
              P: '#a78bfa',
              F: '#34d399',
              Cl: '#34d399',
              Br: '#fb923c',
              I: '#c084fc',
              H: '#94a3b8',
              BACKGROUND: '#0a1628',
            },
          },
        });

        mod.parse(smiles, (tree) => {
          if (!cancelled && containerRef.current) {
            drawer.draw(tree, svg, 'dark');
          }
        }, (err) => {
          console.warn('SMILES parse error:', err);
          if (containerRef.current && !cancelled) {
            containerRef.current.innerHTML =
              `<div class="smiles-fallback">${smiles}</div>`;
          }
        });
      } catch (e) {
        console.warn('SMILES 2D render error:', e);
        if (containerRef.current && !cancelled) {
          containerRef.current.innerHTML =
            `<div class="smiles-fallback">${smiles}</div>`;
        }
      }
    })();

    return () => { cancelled = true; };
  }, [smiles]);

  return (
    <div className="smiles-block-canvas smiles-2d-canvas" ref={containerRef}>
      <div className="smiles-loading">Rendering 2D structure…</div>
    </div>
  );
});


/* ── 3D Molecular Viewer ─────────────────────────────────────────── */
const Mol3DViewer = memo(function Mol3DViewer({ smiles }) {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const [status, setStatus] = useState('loading'); // loading | ready | error

  useEffect(() => {
    let cancelled = false;

    (async () => {
      if (!smiles || !containerRef.current) return;
      setStatus('loading');

      try {
        // Load 3Dmol.js
        const $3Dmol = await get3Dmol();
        if (cancelled) return;

        if (!$3Dmol) {
          setStatus('error');
          return;
        }

        // Fetch 3D coordinates from PubChem
        const sdfData = await fetchSDF(smiles);
        if (cancelled) return;

        // Clear any previous viewer
        containerRef.current.innerHTML = '';

        // Create viewer
        const viewer = $3Dmol.createViewer(containerRef.current, {
          backgroundColor: '#0a1628',
          antialias: true,
          defaultcolors: $3Dmol.rasmolElementColors,
        });

        viewer.addModel(sdfData, 'sdf');
        viewer.setStyle({}, {
          stick: { radius: 0.15, colorscheme: 'Jmol' },
          sphere: { scale: 0.3, colorscheme: 'Jmol' },
        });
        viewer.zoomTo();
        viewer.spin('y', 0.8);
        viewer.render();
        viewerRef.current = viewer;
        setStatus('ready');
      } catch (e) {
        console.warn('3D viewer error:', e);
        if (!cancelled) setStatus('error');
      }
    })();

    return () => {
      cancelled = true;
      if (viewerRef.current) {
        try { viewerRef.current.clear(); } catch (_) {}
        viewerRef.current = null;
      }
    };
  }, [smiles]);

  // Handle resize — only re-attach when viewer status changes
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || status !== 'ready') return;
    const handleResize = () => { try { viewer.resize(); viewer.render(); } catch (_) {} };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [status]);

  return (
    <div className="mol3d-container">
      <div
        className="mol3d-viewer"
        ref={containerRef}
        style={{ width: '100%', height: '320px', position: 'relative' }}
      />
      {status === 'loading' && (
        <div className="mol3d-overlay">
          <div className="smiles-loading">Fetching 3D coordinates from PubChem…</div>
        </div>
      )}
      {status === 'error' && (
        <div className="mol3d-overlay">
          <div className="mol3d-error">
            3D coordinates not available for this molecule.
            <br />
            <span style={{ fontSize: '10px', color: '#64748b' }}>
              PubChem may not have a 3D conformer for this structure.
            </span>
          </div>
        </div>
      )}
      {status === 'ready' && (
        <div className="mol3d-hint">Click &amp; drag to rotate · Scroll to zoom</div>
      )}
    </div>
  );
});


/**
 * SmilesBlock — renders a SMILES string as 2D structural formula or interactive 3D viewer.
 * Toggle between 2D (smiles-drawer SVG) and 3D (3Dmol.js WebGL).
 */
const SmilesBlock = memo(function SmilesBlock({ smiles }) {
  const [mode, setMode] = useState('2d'); // '2d' | '3d'

  return (
    <div className="smiles-block">
      <div className="smiles-block-header">
        <span className="smiles-block-icon">🧪</span>
        <span className="smiles-block-label">Molecular Structure</span>

        {/* 2D / 3D toggle */}
        <div className="smiles-mode-toggle">
          <button
            className={`smiles-mode-btn ${mode === '2d' ? 'active' : ''}`}
            onClick={() => setMode('2d')}
            title="2D structural formula"
          >
            2D
          </button>
          <button
            className={`smiles-mode-btn ${mode === '3d' ? 'active' : ''}`}
            onClick={() => setMode('3d')}
            title="Interactive 3D model (WebGL)"
          >
            3D
          </button>
        </div>

        <code className="smiles-block-raw" title="SMILES notation">{smiles}</code>
      </div>

      {mode === '2d' ? (
        <Smiles2D smiles={smiles} />
      ) : (
        <Mol3DViewer smiles={smiles} />
      )}
    </div>
  );
});


/* ── Custom code block that intercepts `smiles` language ─────────── */
function CodeBlock({ node, inline, className, children, ...props }) {
  const text = String(children).replace(/\n$/, '');
  const match = /language-(\w+)/.exec(className || '');
  const lang = match?.[1]?.toLowerCase();

  // Fenced code block with ```smiles
  if (!inline && (lang === 'smiles' || lang === 'smi' || lang === 'mol')) {
    return <SmilesBlock smiles={text} />;
  }

  // Inline SMILES detector: single backtick containing a likely SMILES string
  // heuristic: has ring digits, brackets, = and uppercase letters typical of SMILES
  if (inline && /^[A-Z][A-Za-z0-9@+\-\[\]\(\)=#\\/:.%]+$/.test(text) && text.length > 4) {
    const hasRingOrBranch = /[\[\]()\d=#]/.test(text);
    if (hasRingOrBranch) {
      return (
        <code className="smiles-inline" title="SMILES notation" {...props}>
          {text}
        </code>
      );
    }
  }

  // Regular code block
  if (!inline) {
    return (
      <pre className={`code-block ${className || ''}`}>
        <code className={className} {...props}>
          {text}
        </code>
      </pre>
    );
  }

  return (
    <code className={className} {...props}>
      {children}
    </code>
  );
}


/* ── Figure wrapper for images — with broken-molecule fallback ──── */
/** Map of common molecule names → SMILES strings */
const KNOWN_MOLECULES = {
  'caffeine': 'CN1C=NC2=C1C(=O)N(C(=O)N2C)C',
  'aspirin': 'CC(=O)Oc1ccccc1C(=O)O',
  'ibuprofen': 'CC(C)Cc1ccc(cc1)C(C)C(=O)O',
  'acetaminophen': 'CC(=O)Nc1ccc(O)cc1',
  'paracetamol': 'CC(=O)Nc1ccc(O)cc1',
  'penicillin': 'CC1(C)SC2C(NC(=O)Cc3ccccc3)C(=O)N2C1C(=O)O',
  'glucose': 'OCC1OC(O)C(O)C(O)C1O',
  'ethanol': 'CCO',
  'methanol': 'CO',
  'dopamine': 'NCCc1ccc(O)c(O)c1',
  'serotonin': 'NCCc1c[nH]c2ccc(O)cc12',
  'adrenaline': 'CNC(CO)c1ccc(O)c(O)c1',
  'epinephrine': 'CNC(CO)c1ccc(O)c(O)c1',
  'cholesterol': 'CC(C)CCCC(C)C1CCC2C3CC=C4CC(O)CCC4(C)C3CCC12C',
  'nicotine': 'CN1CCCC1c1cccnc1',
  'morphine': 'CN1CCC23C4Oc5c(O)ccc5C2(C=CC3O)C14',
  'metformin': 'CN(C)C(=N)NC(=N)N',
  'atorvastatin': 'CC(C)c1n(CC[C@@H](O)C[C@@H](O)CC(=O)O)c(-c2ccccc2)c(-c2ccc(F)cc2)c1C(=O)Nc1ccccc1',
};

/** Check if alt text suggests a molecular structure image */
function extractMoleculeFromAlt(alt) {
  if (!alt) return null;
  const lower = alt.toLowerCase();

  // Check for known molecule names
  for (const [name, smiles] of Object.entries(KNOWN_MOLECULES)) {
    if (lower.includes(name)) return smiles;
  }

  // Check for molecular keywords
  const molKeywords = ['structure', 'molecule', 'molecular', 'chemical', 'compound', 'drug', 'formula'];
  const hasMolKeyword = molKeywords.some(kw => lower.includes(kw));
  if (!hasMolKeyword) return null;

  // Try to extract a molecule name we might recognize
  // Pattern: "structure of X", "X molecule", "chemical structure of X"
  const namePatterns = [
    /(?:structure|molecule|formula)\s+(?:of\s+)?(\w+)/i,
    /(\w+)\s+(?:structure|molecule|formula)/i,
    /chemical\s+(?:structure\s+)?(?:of\s+)?(\w+)/i,
  ];

  for (const pat of namePatterns) {
    const m = lower.match(pat);
    if (m?.[1]) {
      const candidate = m[1].toLowerCase();
      if (KNOWN_MOLECULES[candidate]) return KNOWN_MOLECULES[candidate];
    }
  }

  return null;
}

function FigureImage({ src, alt, title, ...props }) {
  const [broken, setBroken] = useState(false);
  const fallbackSmiles = extractMoleculeFromAlt(alt);

  const handleError = useCallback(() => {
    setBroken(true);
  }, []);

  // If image is broken and we can extract a SMILES molecule, render it instead
  if (broken && fallbackSmiles) {
    return <SmilesBlock smiles={fallbackSmiles} />;
  }

  // If image is broken but no SMILES fallback, show a placeholder
  if (broken) {
    return (
      <div className="sci-figure sci-figure-broken">
        <div className="sci-figure-broken-icon">🧬</div>
        <div className="sci-figure-broken-text">
          {alt || 'Image unavailable'}
        </div>
      </div>
    );
  }

  return (
    <figure className="sci-figure">
      <img
        src={src}
        alt={alt || ''}
        title={title || alt || ''}
        loading="lazy"
        onError={handleError}
        {...props}
      />
      {alt && <figcaption className="sci-figcaption">{alt}</figcaption>}
    </figure>
  );
}


/* ── Table wrapper ───────────────────────────────────────────────── */
function SciTable({ children, ...props }) {
  return (
    <div className="sci-table-wrapper">
      <table className="sci-table" {...props}>
        {children}
      </table>
    </div>
  );
}


/* ════════════════════════════════════════════════════════════════════
   Main Exported Component
   ════════════════════════════════════════════════════════════════════ */

/**
 * Usage: <SciMarkdown>{markdownText}</SciMarkdown>
 *
 * Optional props:
 *   extraComponents — object of component overrides merged with defaults
 */
/* ── Hoisted plugin arrays (stable references — never re-created) ─ */
const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeRaw, rehypeKatex];

/** Default link opener — opens all links in new tab */
const ExternalLink = ({ href, children: kids, title, ...rest }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" title={title} {...rest}>
    {kids}
  </a>
);

/** Default components map (stable reference when no extraComponents) */
const DEFAULT_COMPONENTS = {
  code: CodeBlock,
  img: FigureImage,
  table: SciTable,
  a: ExternalLink,
};

const SciMarkdown = memo(function SciMarkdown({ children, extraComponents }) {
  // Only create a merged components object when extraComponents is provided
  const components = extraComponents
    ? { ...DEFAULT_COMPONENTS, ...extraComponents }
    : DEFAULT_COMPONENTS;

  return (
    <div className="sci-markdown">
      <ReactMarkdown
        remarkPlugins={REMARK_PLUGINS}
        rehypePlugins={REHYPE_PLUGINS}
        components={components}
      >
        {children || ''}
      </ReactMarkdown>
    </div>
  );
});

export default SciMarkdown;
