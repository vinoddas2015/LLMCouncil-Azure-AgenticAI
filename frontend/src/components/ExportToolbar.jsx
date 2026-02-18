/**
 * ExportToolbar — Reusable export button bar for capturing DOM elements
 * as high-resolution PNG images and A4 PDF documents.
 *
 * Usage:
 *   <ExportToolbar targetRef={myRef} filenamePrefix="infographic" />
 *
 * Renders two export buttons (PNG / PDF) and handles:
 *   1. Temporarily applying a white-background "print" class to the target
 *   2. html2canvas capture at 2× device-pixel-ratio for crisp A4 output
 *   3. PNG → direct browser download
 *   4. PDF → jsPDF A4 document with the captured image scaled to fit
 */

import { useState, useCallback } from 'react';
import html2canvas from 'html2canvas-pro';
import { jsPDF } from 'jspdf';
import './ExportToolbar.css';

const A4_WIDTH_PX  = 794;   // 210 mm @ 96 dpi
const A4_HEIGHT_PX = 1123;  // 297 mm @ 96 dpi

/**
 * Capture a DOM element as a canvas.
 */
async function captureElement(element) {
  if (!element) return null;

  // Apply print-optimised class temporarily
  element.classList.add('export-print-mode');
  await new Promise((r) => setTimeout(r, 350));

  try {
    const scale = window.devicePixelRatio >= 2 ? 2 : 3;
    const canvas = await html2canvas(element, {
      scale,
      useCORS: true,
      allowTaint: true,
      backgroundColor: '#ffffff',
      width: Math.max(element.scrollWidth, A4_WIDTH_PX),
      windowWidth: Math.max(element.scrollWidth, A4_WIDTH_PX),
      logging: false,
    });
    return canvas;
  } finally {
    element.classList.remove('export-print-mode');
  }
}

/**
 * Capture multiple child sections as individual canvases for multi-page export.
 * If the target contains `.sg-graph-page` and `.sg-callouts` children, captures each
 * separately so the PDF can place them on different pages with optimised scaling.
 * Falls back to single-capture if those sections aren't present.
 */
async function capturePages(element) {
  if (!element) return [];

  element.classList.add('export-print-mode');
  await new Promise((r) => setTimeout(r, 400));

  const sections = [];
  const graphPage = element.querySelector('.sg-graph-page');
  const calloutsPage = element.querySelector('.sg-callouts');

  try {
    const scale = window.devicePixelRatio >= 2 ? 2 : 3;
    const opts = { scale, useCORS: true, allowTaint: true, backgroundColor: '#ffffff', logging: false };

    if (graphPage) {
      const c = await html2canvas(graphPage, {
        ...opts,
        width: Math.max(graphPage.scrollWidth, A4_WIDTH_PX),
        windowWidth: Math.max(graphPage.scrollWidth, A4_WIDTH_PX),
      });
      sections.push(c);
    }

    if (calloutsPage) {
      const c = await html2canvas(calloutsPage, {
        ...opts,
        width: Math.max(calloutsPage.scrollWidth, A4_WIDTH_PX),
        windowWidth: Math.max(calloutsPage.scrollWidth, A4_WIDTH_PX),
      });
      sections.push(c);
    }

    // Fallback: grab entire element if no sub-sections found
    if (sections.length === 0) {
      const c = await html2canvas(element, {
        ...opts,
        width: Math.max(element.scrollWidth, A4_WIDTH_PX),
        windowWidth: Math.max(element.scrollWidth, A4_WIDTH_PX),
      });
      sections.push(c);
    }

    return sections;
  } finally {
    element.classList.remove('export-print-mode');
  }
}

/**
 * Download a canvas as PNG.
 */
function downloadPNG(canvas, filename) {
  canvas.toBlob((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filename}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 'image/png');
}

/**
 * Download a canvas as a PDF (A4, landscape or portrait auto-detected).
 * Accepts a single canvas or array of canvases (multi-page).
 */
function downloadPDF(canvasOrPages, filename) {
  const pages = Array.isArray(canvasOrPages) ? canvasOrPages : [canvasOrPages];
  if (pages.length === 0) return;

  // Determine orientation from the first (and typically widest) page
  const first = pages[0];
  const orientation = first.width > first.height ? 'landscape' : 'portrait';
  const pdf = new jsPDF({ orientation, unit: 'mm', format: 'a4' });

  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  const margin = 8; // mm
  const usableW = pageW - margin * 2;
  const usableH = pageH - margin * 2;

  pages.forEach((canvas, idx) => {
    if (idx > 0) pdf.addPage(orientation === 'landscape' ? 'l' : 'p');

    const imgData = canvas.toDataURL('image/png');
    const imgW = canvas.width;
    const imgH = canvas.height;

    // Scale image to fit within usable area
    const ratio = Math.min(usableW / imgW, usableH / imgH);
    const pdfW = imgW * ratio;
    const pdfH = imgH * ratio;

    // Centre on page
    const x = (pageW - pdfW) / 2;
    const y = (pageH - pdfH) / 2;

    pdf.addImage(imgData, 'PNG', x, y, pdfW, pdfH);
  });

  pdf.save(`${filename}.pdf`);
}

export default function ExportToolbar({ targetRef, filenamePrefix = 'export' }) {
  const [busy, setBusy] = useState(false);

  const handleExport = useCallback(
    async (format) => {
      if (busy || !targetRef?.current) return;
      setBusy(true);
      try {
        const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
        const fname = `${filenamePrefix}_${ts}`;

        if (format === 'pdf') {
          // Multi-page PDF: capture graph + callout sections separately
          const pages = await capturePages(targetRef.current);
          if (pages.length > 0) downloadPDF(pages, fname);
        } else {
          // PNG: single full-element capture
          const canvas = await captureElement(targetRef.current);
          if (canvas) downloadPNG(canvas, fname);
        }
      } finally {
        setBusy(false);
      }
    },
    [busy, targetRef, filenamePrefix],
  );

  return (
    <div className="export-toolbar" onClick={(e) => e.stopPropagation()}>
      <button
        className="export-btn export-btn-png"
        onClick={(e) => { e.stopPropagation(); handleExport('png'); }}
        disabled={busy}
        title="Export as PNG (A4 print-ready)"
      >
        {busy ? '⏳' : '🖼️'} PNG
      </button>
      <button
        className="export-btn export-btn-pdf"
        onClick={(e) => { e.stopPropagation(); handleExport('pdf'); }}
        disabled={busy}
        title="Export as PDF (A4 document)"
      >
        {busy ? '⏳' : '📄'} PDF
      </button>
    </div>
  );
}
