"""
DOCX export v2 — per-model contextual images via multi-provider image_gen.

Every model response gets its own AI-generated illustration alongside text.
Section banners keep hero images. All images generated in parallel for speed.
"""

import io
import re
from typing import Optional, Dict, List

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT

from .image_gen import (
    generate_images_parallel_sync,
    build_slide_prompt,
    build_section_prompt,
)


def _strip_markdown(text: str) -> str:
    """Lightly strip markdown formatting for plain-text paragraphs."""
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'[Image: \1]', text)
    return text


def _add_markdown_runs(paragraph, text: str):
    """Parse bold/italic in *text* and add formatted runs to *paragraph*."""
    parts = re.split(r'(\*\*[^*]+?\*\*)', text)
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        else:
            sub_parts = re.split(r'(\*[^*]+?\*)', part)
            for sp in sub_parts:
                if sp.startswith('*') and sp.endswith('*') and len(sp) > 2:
                    run = paragraph.add_run(sp[1:-1])
                    run.italic = True
                else:
                    paragraph.add_run(sp)


def _set_cell_shading(cell, hex_color: str):
    """Apply background shading to a table cell."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    shading = OxmlElement('w:shd')
    shading.set(qn('w:val'), 'clear')
    shading.set(qn('w:color'), 'auto')
    shading.set(qn('w:fill'), hex_color)
    cell._tc.get_or_add_tcPr().append(shading)


BAYER_GREEN = RGBColor(0x10, 0x85, 0x7F)
BAYER_DARK = RGBColor(0x1E, 0x29, 0x3B)
STAGE_COLORS = {
    1: 'E8F4FD',   # light blue
    2: 'FFF3E0',   # light amber
    3: 'E8F5E9',   # light green
}

MODEL_ACCENT = {
    1: RGBColor(0x0D, 0x47, 0xA1),
    2: RGBColor(0xBF, 0x36, 0x0C),
    3: RGBColor(0x1B, 0x5E, 0x20),
}


def _add_image_to_doc(doc: Document, image_bytes: Optional[bytes],
                      width: Cm = Cm(12), center: bool = True):
    """Insert an image into the document if bytes are available."""
    if not image_bytes:
        return
    try:
        doc.add_picture(io.BytesIO(image_bytes), width=width)
        if center:
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    except Exception:
        pass


def _add_model_response(doc: Document, model_name: str, text: str,
                        accent: RGBColor, image: Optional[bytes] = None):
    """Add a model's response with optional contextual image."""
    # Model name header
    mp = doc.add_paragraph()
    mr = mp.add_run(model_name)
    mr.bold = True
    mr.font.size = Pt(11)
    mr.font.color.rgb = accent

    # Contextual image for this model
    if image:
        _add_image_to_doc(doc, image, width=Cm(10), center=True)
        doc.add_paragraph('')  # spacer

    # Response text with formatting
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('###'):
            doc.add_heading(line.lstrip('#').strip(), level=4)
        elif line.startswith('##'):
            doc.add_heading(line.lstrip('#').strip(), level=3)
        elif line.startswith('#'):
            doc.add_heading(line.lstrip('#').strip(), level=3)
        elif line.startswith('- ') or line.startswith('* '):
            p = doc.add_paragraph(style='List Bullet')
            _add_markdown_runs(p, line[2:])
        elif re.match(r'^\d+[\.\)]\s', line):
            p = doc.add_paragraph(style='List Number')
            _add_markdown_runs(p, re.sub(r'^\d+[\.\)]\s', '', line))
        else:
            p = doc.add_paragraph()
            _add_markdown_runs(p, line)

    doc.add_paragraph('')  # spacer between models


def _collect_image_prompts(conversation: dict, user_question: str) -> Dict[str, str]:
    """Collect all image prompts for the document.

    Returns {key: prompt_text} — 'hero', 'stage1_banner', 'stage2_banner',
    'stage3_banner', 's1_<model>', 's2_<model>', 's3_<model>'
    """
    prompts: Dict[str, str] = {}

    # Document hero
    prompts['hero'] = f"Executive summary illustration, pharma presentation cover: {user_question[:200]}"

    # Stage banners
    prompts['stage1_banner'] = build_section_prompt(1, user_question)
    prompts['stage2_banner'] = build_section_prompt(2, user_question)
    prompts['stage3_banner'] = build_section_prompt(3, user_question)

    # Per-model images
    for msg in conversation.get('messages', []):
        if msg.get('role') == 'user':
            continue

        for resp in (msg.get('stage1') or []):
            model = resp.get('model', 'model')
            key = f's1_{model}'
            if key not in prompts:
                prompts[key] = build_slide_prompt(
                    model, _strip_markdown(resp.get('response', '')), 1, user_question)

        for ranking in (msg.get('stage2') or []):
            model = ranking.get('model', 'reviewer')
            key = f's2_{model}'
            if key not in prompts:
                prompts[key] = build_slide_prompt(
                    model, _strip_markdown(ranking.get('response', '')), 2, user_question)

        stage3 = msg.get('stage3')
        if stage3:
            model = stage3.get('model', 'chairman')
            key = f's3_{model}'
            if key not in prompts:
                prompts[key] = build_slide_prompt(
                    model, _strip_markdown(stage3.get('response', '')), 3, user_question)

    return prompts


def generate_docx(conversation: dict) -> bytes:
    """Build a DOCX file from a conversation dict and return raw bytes."""
    doc = Document()

    # ── Page setup (A4) ──────────────────────────────────────────
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)

    # ── Styles ───────────────────────────────────────────────────
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(11)
    font.color.rgb = BAYER_DARK

    # ── Title ────────────────────────────────────────────────────
    title_para = doc.add_heading(
        conversation.get('title', 'LLM Council Conversation'), level=0)
    for run in title_para.runs:
        run.font.color.rgb = BAYER_GREEN

    created = conversation.get('created_at', '')
    if created:
        meta = doc.add_paragraph()
        meta.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = meta.add_run(f'Created: {created}')
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    doc.add_paragraph('')  # spacer

    # ── Extract user question ────────────────────────────────────
    user_question = ""
    for msg in conversation.get('messages', []):
        if msg.get('role') == 'user' and msg.get('content'):
            user_question = msg.get('content', '')
            break

    # ── Generate ALL images in parallel ──────────────────────────
    all_prompts = _collect_image_prompts(conversation, user_question)

    # Banner images at 16:9, per-model images at 1:1 (for inline display)
    banner_keys = {'hero', 'stage1_banner', 'stage2_banner', 'stage3_banner'}
    banner_prompts = {k: v for k, v in all_prompts.items() if k in banner_keys}
    model_prompts = {k: v for k, v in all_prompts.items() if k not in banner_keys}

    banner_images = generate_images_parallel_sync(
        banner_prompts, aspect_ratio="16:9", max_concurrent=3)
    model_images = generate_images_parallel_sync(
        model_prompts, aspect_ratio="1:1", max_concurrent=4)

    all_images: Dict[str, Optional[bytes]] = {**banner_images, **model_images}

    # ── Hero image ───────────────────────────────────────────────
    _add_image_to_doc(doc, all_images.get('hero'), width=Cm(15))
    if all_images.get('hero'):
        doc.add_paragraph('')

    # ── Messages ─────────────────────────────────────────────────
    for msg in conversation.get('messages', []):
        if msg.get('role') == 'user':
            h = doc.add_heading('User', level=1)
            for run in h.runs:
                run.font.color.rgb = RGBColor(0x1A, 0x73, 0xE8)
            for line in msg.get('content', '').split('\n'):
                p = doc.add_paragraph()
                _add_markdown_runs(p, line)

        else:
            h = doc.add_heading('Council Response', level=1)
            for run in h.runs:
                run.font.color.rgb = BAYER_GREEN

            # ── Stage 1 ─────────────────────────────────────────
            stage1 = msg.get('stage1')
            if stage1:
                sh = doc.add_heading('Stage 1 \u2014 Individual Model Responses', level=2)
                for run in sh.runs:
                    run.font.color.rgb = RGBColor(0x15, 0x65, 0xC0)

                _add_image_to_doc(doc, all_images.get('stage1_banner'), width=Cm(15))

                for resp in stage1:
                    model_name = resp.get('model', 'Unknown')
                    _add_model_response(
                        doc, model_name,
                        resp.get('response', 'No response'),
                        MODEL_ACCENT[1],
                        image=all_images.get(f's1_{model_name}'),
                    )

            # ── Stage 2 ─────────────────────────────────────────
            stage2 = msg.get('stage2')
            if stage2:
                sh = doc.add_heading('Stage 2 \u2014 Peer Rankings', level=2)
                for run in sh.runs:
                    run.font.color.rgb = RGBColor(0xE6, 0x51, 0x00)

                _add_image_to_doc(doc, all_images.get('stage2_banner'), width=Cm(15))

                for ranking in stage2:
                    model_name = ranking.get('model', 'Unknown')
                    _add_model_response(
                        doc, model_name,
                        ranking.get('response', 'No ranking'),
                        MODEL_ACCENT[2],
                        image=all_images.get(f's2_{model_name}'),
                    )

            # ── Stage 3 ─────────────────────────────────────────
            stage3 = msg.get('stage3')
            if stage3:
                sh = doc.add_heading("Stage 3 \u2014 Chairman's Final Synthesis", level=2)
                for run in sh.runs:
                    run.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)

                _add_image_to_doc(doc, all_images.get('stage3_banner'), width=Cm(15))

                chairman = stage3.get('model', 'Chairman')
                _add_model_response(
                    doc, chairman,
                    stage3.get('response', 'No synthesis'),
                    MODEL_ACCENT[3],
                    image=all_images.get(f's3_{chairman}'),
                )

        # Horizontal rule between messages
        doc.add_paragraph('\u2500' * 60)

    # ── Footer ───────────────────────────────────────────────────
    footer_para = doc.add_paragraph()
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer_para.add_run('Generated by LLM Council \u2014 Bayer myGenAssist')
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()
