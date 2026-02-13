/**
 * ExportToolbar — Reusable export button bar for capturing DOM elements
 * as high-resolution PNG / JPG images, optimised for A4 print layout.
 *
 * Usage:
 *   <ExportToolbar targetRef={myRef} filenamePrefix="infographic" />
 *
 * Renders two export buttons (PNG / JPG) and handles:
 *   1. Temporarily applying a white-background "print" class to the target
 *   2. html2canvas capture at 2× device-pixel-ratio for crisp A4 output
 *   3. Triggering a browser download of the resulting image
 */

import { useState, useCallback } from 'react';
import html2canvas from 'html2canvas-pro';
import './ExportToolbar.css';

const A4_WIDTH_PX  = 794;   // 210 mm @ 96 dpi
const A4_HEIGHT_PX = 1123;  // 297 mm @ 96 dpi

/**
 * Capture a DOM element and download as an image file.
 *
 * @param {HTMLElement} element  – DOM node to capture
 * @param {'png'|'jpg'} format  – output format
 * @param {string} filename     – download filename (without extension)
 */
async function captureAndDownload(element, format, filename) {
  if (!element) return;

  // 1. Apply print-optimised class temporarily
  element.classList.add('export-print-mode');

  // Small delay to let the browser reflow with print styles
  await new Promise((r) => setTimeout(r, 120));

  try {
    const scale = window.devicePixelRatio >= 2 ? 2 : 3; // crisp output for A4
    const canvas = await html2canvas(element, {
      scale,
      useCORS: true,
      allowTaint: true,
      backgroundColor: '#ffffff',
      width: Math.max(element.scrollWidth, A4_WIDTH_PX),
      windowWidth: Math.max(element.scrollWidth, A4_WIDTH_PX),
      logging: false,
    });

    // 2. Convert to blob and trigger download
    const mimeType = format === 'jpg' ? 'image/jpeg' : 'image/png';
    const quality  = format === 'jpg' ? 0.92 : undefined;

    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a   = document.createElement('a');
        a.href     = url;
        a.download = `${filename}.${format}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      },
      mimeType,
      quality,
    );
  } finally {
    element.classList.remove('export-print-mode');
  }
}

export default function ExportToolbar({ targetRef, filenamePrefix = 'export' }) {
  const [busy, setBusy] = useState(false);

  const handleExport = useCallback(
    async (format) => {
      if (busy || !targetRef?.current) return;
      setBusy(true);
      try {
        const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
        await captureAndDownload(targetRef.current, format, `${filenamePrefix}_${ts}`);
      } finally {
        setBusy(false);
      }
    },
    [busy, targetRef, filenamePrefix],
  );

  return (
    <div className="export-toolbar">
      <button
        className="export-btn export-btn-png"
        onClick={() => handleExport('png')}
        disabled={busy}
        title="Export as PNG (A4 print-ready)"
      >
        {busy ? '⏳' : '🖼️'} PNG
      </button>
      <button
        className="export-btn export-btn-jpg"
        onClick={() => handleExport('jpg')}
        disabled={busy}
        title="Export as JPG (A4 print-ready)"
      >
        {busy ? '⏳' : '📷'} JPG
      </button>
    </div>
  );
}
