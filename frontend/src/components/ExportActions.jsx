/**
 * ExportActions — In-chat export buttons for individual council responses.
 *
 * Renders a compact action bar beneath a completed council response
 * offering DOCX and PPTX downloads.
 */

import { useState, useCallback } from 'react';
import { api } from '../api';
import './ExportActions.css';

export default function ExportActions({ conversationId }) {
  const [busy, setBusy] = useState(null); // null | 'docx' | 'pptx'

  const handleExport = useCallback(async (format) => {
    if (busy || !conversationId) return;
    setBusy(format);
    try {
      const exportData = await api.exportConversation(conversationId, format);
      if (exportData.blob) {
        const url = URL.createObjectURL(exportData.blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = exportData.filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      console.error(`Export ${format} failed:`, err);
    } finally {
      setBusy(null);
    }
  }, [busy, conversationId]);

  if (!conversationId) return null;

  return (
    <div className="export-actions" role="toolbar" aria-label="Export conversation">
      <span className="export-actions-label">Export:</span>
      <button
        className="export-action-btn export-action-docx"
        onClick={() => handleExport('docx')}
        disabled={!!busy}
        title="Download as Word document (.docx)"
        aria-label="Export as Word document"
      >
        {busy === 'docx' ? '⏳' : '📄'} DOCX
      </button>
      <button
        className="export-action-btn export-action-pptx"
        onClick={() => handleExport('pptx')}
        disabled={!!busy}
        title="Download as PowerPoint presentation (.pptx)"
        aria-label="Export as PowerPoint presentation"
      >
        {busy === 'pptx' ? '⏳' : '📊'} PPTX
      </button>
    </div>
  );
}
