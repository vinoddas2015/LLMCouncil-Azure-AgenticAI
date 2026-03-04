"""
PPTX export v2 — lighter, more visual-friendly deck with optional AI hero images.

Notes:
- Microsoft Copilot / Prometheus APIs are not publicly exposed; Graph lacks AI slide-gen.
- Optional hero images use Google Imagen 3 via GOOGLE_API_KEY; fails gracefully if missing.
"""

import base64
import io
import os
import re
from typing import List, Dict, Any, Optional

import httpx
from pptx import Presentation
from pptx.util import Cm, Pt
from pptx.enum.text import PP_ALIGN, MSO_AUTO_SIZE
from pptx.dml.color import RGBColor

from .config import GOOGLE_API_KEY

# Brand colours
BAYER_GREEN = RGBColor(0x10, 0x85, 0x7F)
BAYER_DARK = RGBColor(0x1E, 0x29, 0x3B)
LIGHT_BG = RGBColor(0xF7, 0xFA, 0xFC)
GRAY_TEXT = RGBColor(0x55, 0x65, 0x81)

# Stage themes
STAGE_THEME = {
    1: {'bg': RGBColor(0xE7, 0xF3, 0xFF), 'accent': RGBColor(0x15, 0x65, 0xC0), 'title': 'Stage 1 — Model Responses'},
    2: {'bg': RGBColor(0xFF, 0xF4, 0xE6), 'accent': RGBColor(0xE6, 0x51, 0x00), 'title': 'Stage 2 — Peer Rankings'},
    3: {'bg': RGBColor(0xE8, 0xF5, 0xE9), 'accent': RGBColor(0x2E, 0x7D, 0x32), 'title': "Stage 3 — Chairman Synthesis"},
}

# Layout constants (16:9)
SLIDE_WIDTH = Cm(33.87)
SLIDE_HEIGHT = Cm(19.05)
MARGIN = Cm(1.2)
MAX_CHARS = 1200


def _strip_md(text: str) -> str:
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'', text)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    return text.strip()


def _generate_stage_image(prompt: str) -> Optional[bytes]:
    """Call Google Imagen to generate a base64 image. Returns PNG bytes or None on failure."""
    if not GOOGLE_API_KEY:
        return None

    url = "https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0:generateImage"
    headers = {"x-goog-api-key": GOOGLE_API_KEY, "Content-Type": "application/json"}
    payload = {
        "prompt": {"text": prompt[:500]},
        "aspectRatio": "16:9",
        "negativePrompt": "watermark, text, logo, words, artifacts",
    }

    try:
        with httpx.Client(timeout=40, verify=False) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            images = data.get("images") or data.get("generatedImages") or []
            if not images:
                return None
            b64 = images[0].get("image") or images[0].get("base64Data")
            if not b64:
                return None
            return base64.b64decode(b64)
    except Exception:
        return None


def _chunk(text: str, limit: int = MAX_CHARS) -> List[str]:
    if len(text) <= limit:
        return [text]
    out, buf, n = [], [], 0
    for line in text.split('\n'):
        ln = len(line) + 1
        if n + ln > limit and buf:
            out.append('\n'.join(buf))
            buf, n = [line], ln
        else:
            buf.append(line)
            n += ln
    if buf:
        out.append('\n'.join(buf))
    return out or [text]


def _add_title_slide(prs: Presentation, conversation: Dict[str, Any]):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    sw, sh = prs.slide_width, prs.slide_height

    # background
    bg = slide.shapes.add_shape(1, 0, 0, sw, sh)
    bg.fill.solid(); bg.fill.fore_color.rgb = BAYER_DARK; bg.line.fill.background()

    # accent band
    band = slide.shapes.add_shape(1, 0, Cm(7), sw, Cm(0.6))
    band.fill.solid(); band.fill.fore_color.rgb = BAYER_GREEN; band.line.fill.background()

    tb = slide.shapes.add_textbox(Cm(2.5), Cm(3.0), sw - Cm(5.0), Cm(3.5))
    tf = tb.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.text = conversation.get('title', 'LLM Council Report'); p.font.size = Pt(34); p.font.bold = True; p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF); p.alignment = PP_ALIGN.CENTER
    sp = tf.add_paragraph(); sp.text = 'Multi-Model Deliberation'; sp.font.size = Pt(16); sp.font.color.rgb = BAYER_GREEN; sp.alignment = PP_ALIGN.CENTER
    if conversation.get('created_at'):
        dp = tf.add_paragraph(); dp.text = f"Generated: {conversation['created_at']}"; dp.font.size = Pt(11); dp.font.color.rgb = RGBColor(0xBB, 0xBB, 0xBB); dp.alignment = PP_ALIGN.CENTER

    footer = slide.shapes.add_textbox(Cm(2.0), sh - Cm(1.5), sw - Cm(4.0), Cm(1.0))
    ft = footer.text_frame; fp = ft.paragraphs[0]; fp.text = 'Powered by Bayer myGenAssist'; fp.font.size = Pt(10); fp.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA); fp.alignment = PP_ALIGN.CENTER


def _add_section_slide(prs: Presentation, stage: int, headline: str, kicker: str = '', hero_image: Optional[bytes] = None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    theme = STAGE_THEME.get(stage, STAGE_THEME[1])
    sw, sh = prs.slide_width, prs.slide_height

    # gradient-ish bands using two rectangles
    top = slide.shapes.add_shape(1, 0, 0, sw, Cm(3.5))
    top.fill.solid(); top.fill.fore_color.rgb = theme['accent']; top.line.fill.background()
    body = slide.shapes.add_shape(1, 0, Cm(3.5), sw, sh - Cm(3.5))
    body.fill.solid(); body.fill.fore_color.rgb = theme['bg']; body.line.fill.background()

    tb = slide.shapes.add_textbox(MARGIN, Cm(1.2), sw - 2*MARGIN, Cm(2.2))
    tf = tb.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.text = headline; p.font.size = Pt(26); p.font.bold = True; p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF); p.alignment = PP_ALIGN.LEFT
    if kicker:
        kp = tf.add_paragraph(); kp.text = kicker; kp.font.size = Pt(14); kp.font.color.rgb = RGBColor(0xEE, 0xEE, 0xEE); kp.alignment = PP_ALIGN.LEFT

    # hero image (optional)
    if hero_image:
        try:
            stream = io.BytesIO(hero_image)
            img_width = sw - 2*MARGIN
            slide.shapes.add_picture(stream, MARGIN, Cm(3.9), width=img_width)
        except Exception:
            pass


def _add_card(slide, left, top, width, height, title: str, body: str, accent: RGBColor):
    rect = slide.shapes.add_shape(1, left, top, width, height)
    rect.fill.solid(); rect.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    rect.line.color.rgb = accent; rect.line.width = Pt(1.5)

    tb = slide.shapes.add_textbox(left + Cm(0.4), top + Cm(0.35), width - Cm(0.8), height - Cm(0.7))
    tf = tb.text_frame; tf.word_wrap = True; tf.auto_size = MSO_AUTO_SIZE.NONE
    h = tf.paragraphs[0]; h.text = title; h.font.size = Pt(14); h.font.bold = True; h.font.color.rgb = accent
    for line in body.split('\n'):
        p = tf.add_paragraph(); p.text = line.strip(); p.font.size = Pt(11); p.font.color.rgb = BAYER_DARK; p.space_after = Pt(3)


def _add_text_block(slide, left, top, width, height, text: str, accent: RGBColor):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame; tf.word_wrap = True; tf.auto_size = MSO_AUTO_SIZE.NONE
    for line in text.split('\n'):
        if not line.strip():
            p = tf.add_paragraph(); p.text = ''; p.space_after = Pt(4); continue
        p = tf.add_paragraph() if tf.paragraphs[0].text else tf.paragraphs[0]
        clean = line.strip()
        if clean.startswith('- '):
            p.text = '• ' + clean[2:]
        elif re.match(r'^\d+[\.\)]\s', clean):
            p.text = clean
        else:
            p.text = clean
        p.font.size = Pt(11)
        p.font.color.rgb = accent if p.text.startswith('•') else BAYER_DARK
        p.space_after = Pt(2)


def generate_pptx(conversation: Dict[str, Any]) -> bytes:
    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT

    _add_title_slide(prs, conversation)

    # Determine user question text (first user message)
    user_question = ""
    for msg in conversation.get('messages', []):
        if msg.get('role') == 'user' and msg.get('content'):
            user_question = _strip_md(msg.get('content', ''))
            break

    # Pre-generate hero images per stage (best effort)
    stage_hero_images: Dict[int, Optional[bytes]] = {}
    prompts = {
        1: f"Illustration, scientific, pharma brainstorm, stage 1 model responses about: {user_question}",
        2: f"Peer review, ranking board, collaborative evaluation, stage 2 for: {user_question}",
        3: f"Executive summary, synthesized decision, clear outcome, stage 3 for: {user_question}",
    }
    for stage, prompt in prompts.items():
        img = _generate_stage_image(prompt)
        stage_hero_images[stage] = img

    for msg in conversation.get('messages', []):
        if msg.get('role') == 'user':
            _add_section_slide(prs, 1, 'User Question', 'What was asked', hero_image=stage_hero_images.get(1))
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            _add_text_block(slide, MARGIN, MARGIN, prs.slide_width - 2*MARGIN, prs.slide_height - 2*MARGIN, _strip_md(msg.get('content','')), BAYER_DARK)
            continue

        stage1 = msg.get('stage1') or []
        if stage1:
            _add_section_slide(prs, 1, STAGE_THEME[1]['title'], 'Key model answers', hero_image=stage_hero_images.get(1))
            for resp in stage1:
                chunks = _chunk(_strip_md(resp.get('response','')))
                for idx, chunk in enumerate(chunks, start=1):
                    slide = prs.slides.add_slide(prs.slide_layouts[6])
                    _add_card(slide, MARGIN, MARGIN, prs.slide_width - 2*MARGIN, prs.slide_height - 2*MARGIN, f"{resp.get('model','Model')} ({idx}/{len(chunks)})", chunk, STAGE_THEME[1]['accent'])

        stage2 = msg.get('stage2') or []
        if stage2:
            _add_section_slide(prs, 2, STAGE_THEME[2]['title'], 'Peer evaluations', hero_image=stage_hero_images.get(2))
            for ranking in stage2:
                chunks = _chunk(_strip_md(ranking.get('response','')))
                for idx, chunk in enumerate(chunks, start=1):
                    slide = prs.slides.add_slide(prs.slide_layouts[6])
                    _add_card(slide, MARGIN, MARGIN, prs.slide_width - 2*MARGIN, prs.slide_height - 2*MARGIN, f"{ranking.get('model','Reviewer')} ({idx}/{len(chunks)})", chunk, STAGE_THEME[2]['accent'])

        stage3 = msg.get('stage3')
        if stage3:
            _add_section_slide(prs, 3, STAGE_THEME[3]['title'], 'Final synthesis', hero_image=stage_hero_images.get(3))
            chunks = _chunk(_strip_md(stage3.get('response','')))
            for idx, chunk in enumerate(chunks, start=1):
                slide = prs.slides.add_slide(prs.slide_layouts[6])
                _add_card(slide, MARGIN, MARGIN, prs.slide_width - 2*MARGIN, prs.slide_height - 2*MARGIN, f"{stage3.get('model','Chairman')} ({idx}/{len(chunks)})", chunk, STAGE_THEME[3]['accent'])

    # Closing
    closing = prs.slides.add_slide(prs.slide_layouts[6])
    sw, sh = prs.slide_width, prs.slide_height
    bg = closing.shapes.add_shape(1, 0, 0, sw, sh); bg.fill.solid(); bg.fill.fore_color.rgb = BAYER_DARK; bg.line.fill.background()
    band = closing.shapes.add_shape(1, 0, Cm(9.0), sw, Cm(0.4)); band.fill.solid(); band.fill.fore_color.rgb = BAYER_GREEN; band.line.fill.background()
    tb = closing.shapes.add_textbox(Cm(2.0), Cm(5.0), sw - Cm(4.0), Cm(4.0))
    tf = tb.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.text = 'End of Report'; p.font.size = Pt(28); p.font.bold = True; p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF); p.alignment = PP_ALIGN.CENTER
    sp = tf.add_paragraph(); sp.text = 'LLM Council — Multi-Model Deliberation'; sp.font.size = Pt(14); sp.font.color.rgb = BAYER_GREEN; sp.alignment = PP_ALIGN.CENTER
    sp2 = tf.add_paragraph(); sp2.text = 'Bayer myGenAssist Platform'; sp2.font.size = Pt(11); sp2.font.color.rgb = RGBColor(0xAA,0xAA,0xAA); sp2.alignment = PP_ALIGN.CENTER

    buf = io.BytesIO(); prs.save(buf); buf.seek(0); return buf.getvalue()


if __name__ == "__main__":
    # Minimal manual test when running `python -m backend.export_pptx`
    sample_conv = {
        "title": "Sample Council Run",
        "created_at": "2026-03-04",
        "messages": [
            {"role": "user", "content": "Summarize safety profile of Drug X vs placebo."},
            {"role": "assistant", "stage1": [
                {"model": "gemini-2.5-pro", "response": "**Efficacy**\n- Reduction in events..."},
                {"model": "claude-sonnet", "response": "**Safety**\n- Mild AEs..."},
            ], "stage2": [
                {"model": "gemini-2.5-pro", "response": "1. Response A\n2. Response B"}
            ], "stage3": {"model": "claude-opus", "response": "Final: balanced benefit-risk."}},
        ]
    }
    out = generate_pptx(sample_conv)
    with open("/tmp/export_sample.pptx", "wb") as f:
        f.write(out)
    print("Wrote /tmp/export_sample.pptx")