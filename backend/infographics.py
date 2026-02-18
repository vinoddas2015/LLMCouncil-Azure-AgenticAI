"""
Infographic extraction from Chairman Stage 3 responses.

Parses structured JSON infographic data from the chairman's output
and provides a fallback auto-extraction when the chairman doesn't
include the infographic block.

DESIGN RULE: Infographics MUST always be generated for every council
response unless the user explicitly requests "no infographic".
The auto-extractor uses progressively broader heuristics to guarantee
at least a minimal infographic is returned.
"""

import json
import re
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("llm_council.infographics")


def extract_infographic(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Extract infographic JSON from a chairman's response.

    Looks for a ```infographic ... ``` code block in the response.
    Falls back to auto-extraction from the response content.

    Args:
        response_text: The full chairman response text.

    Returns:
        Dict with infographic data, or None if extraction fails.
    """
    # 1. Try to extract explicit ```infographic block
    infographic = _parse_infographic_block(response_text)
    if infographic:
        logger.info("[Infographic] Extracted explicit infographic block")
        return _validate_and_clean(infographic)

    # 2. Fallback: auto-extract key data from the response
    logger.info("[Infographic] No explicit block found — auto-extracting")
    return _auto_extract(response_text)


def strip_infographic_block(response_text: str) -> str:
    """Remove the ```infographic ... ``` block from the response text.

    This prevents the raw JSON from being rendered in the markdown output.
    """
    return re.sub(
        r'```infographic\s*\n.*?```',
        '',
        response_text,
        flags=re.DOTALL,
    ).strip()


def _parse_infographic_block(text: str) -> Optional[Dict[str, Any]]:
    """Parse a ```infographic JSON block."""
    match = re.search(
        r'```infographic\s*\n(.*?)```',
        text,
        re.DOTALL,
    )
    if not match:
        return None

    json_str = match.group(1).strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"[Infographic] JSON parse error: {e}")
        # Try to fix common issues (trailing commas, etc.)
        cleaned = re.sub(r',\s*([}\]])', r'\1', json_str)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def _auto_extract(text: str) -> Optional[Dict[str, Any]]:
    """
    Auto-extract infographic data from response text.

    GUARANTEED to return an infographic for any non-trivial response.
    Uses a tiered extraction strategy:
      0. Detect value proposition structure → VP template
      1. Look for structured pharma/chemistry metrics
      2. Look for bold-text highlights and key sentences
      3. Look for numbered steps / headings
      4. Fallback: extract a summary from the first meaningful paragraphs

    Scans for:
      - Challenge/Solution/Outcome sections → value_proposition
      - Numbers/stats → key metrics
      - Bold items → highlights
      - Headings → process steps
    """
    # ── Priority 0: Value Proposition template detection ──
    vp_data = _extract_value_proposition(text)
    if vp_data:
        logger.info("[Infographic] Detected value proposition structure — using VP template")
        return vp_data

    infographic: Dict[str, Any] = {
        "title": "Council Response Summary",
        "type": "auto",
    }

    # Extract key metrics: pharma, chemistry, and general patterns
    metrics = _extract_metrics(text)
    if metrics:
        infographic["key_metrics"] = metrics[:6]

    # Extract highlights from bold text and key sentences
    highlights = _extract_highlights(text)
    if highlights:
        infographic["highlights"] = highlights[:4]

    # Extract process steps from numbered lists or headings
    steps = _extract_steps(text)
    if steps:
        infographic["process_steps"] = steps[:6]

    # ── GUARANTEE: always return an infographic ──
    # Tier 1: we have metrics or highlights → return as-is
    if metrics or highlights:
        return infographic

    # Tier 2: we have steps → return with steps
    if steps:
        return infographic

    # Tier 3: generate a fallback infographic from the response
    return _fallback_infographic(text)


def _extract_value_proposition(text: str) -> Optional[Dict[str, Any]]:
    """
    Detect and extract a Challenge → Solution → Outcome value proposition
    template from the chairman's response.

    Triggers when at least 2 of the 3 VP sections are found with meaningful
    content. Returns a VP-typed infographic dict or None.
    """
    text_lower = text.lower()

    # ── Section detection patterns ──
    section_patterns = {
        "challenge": [
            r'#+\s*(?:the\s+)?challenge[s]?\s*[:\n]',
            r'\*\*(?:the\s+)?challenge[s]?\*\*\s*[:\n]',
            r'(?:^|\n)\s*challenge[s]?\s*:\s*',
            r'(?:^|\n)\s*(?:the\s+)?unmet\s+need\s*[:\n]',
            r'(?:^|\n)\s*(?:current\s+)?limitation[s]?\s*[:\n]',
        ],
        "solution": [
            r'#+\s*(?:the\s+)?solution[s]?\s*[:\n]',
            r'\*\*(?:the\s+)?solution[s]?\*\*\s*[:\n]',
            r'(?:^|\n)\s*solution[s]?\s*:\s*',
            r'#+\s*(?:the\s+)?approach\s*[:\n]',
            r'#+\s*how\s+it\s+works\s*[:\n]',
            r'#+\s*(?:the\s+)?value\s+proposition\s*[:\n]',
        ],
        "outcome": [
            r'#+\s*(?:the\s+)?outcome[s]?\s*[:\n]',
            r'\*\*(?:the\s+)?outcome[s]?\*\*\s*[:\n]',
            r'(?:^|\n)\s*outcome[s]?\s*:\s*',
            r'#+\s*(?:the\s+)?(?:clinical\s+)?(?:impact|result|benefit)[s]?\s*[:\n]',
            r'#+\s*(?:the\s+)?transform(?:ative|ing)\s+impact\s*[:\n]',
        ],
    }

    # Find section positions
    section_positions = {}  # section_type → start_index
    for section_type, patterns in section_patterns.items():
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if match:
                section_positions[section_type] = match.end()
                break

    # Need at least 2 of 3 sections
    if len(section_positions) < 2:
        return None

    # ── Extract content for each section ──
    # Sort by position to determine boundaries
    sorted_sections = sorted(section_positions.items(), key=lambda x: x[1])

    sections = []
    for i, (section_type, start_pos) in enumerate(sorted_sections):
        # End = start of next section or end of text (capped at 2000 chars)
        if i + 1 < len(sorted_sections):
            end_pos = sorted_sections[i + 1][1] - 60  # back up before heading
        else:
            end_pos = min(start_pos + 2000, len(text))

        content_block = text[start_pos:end_pos].strip()

        # Extract bullets (- item or * item or numbered)
        bullets = re.findall(
            r'(?:^|\n)\s*(?:[-*•]|\d+[.)]) \s*(.{10,150})',
            content_block,
        )
        bullets = [b.strip().rstrip('.') for b in bullets[:5]]

        # If no bullets, split into sentences and take first 3
        if not bullets:
            sentences = re.split(r'(?<=[.!?])\s+', re.sub(r'[#*_]', '', content_block))
            bullets = [
                s.strip()[:140]
                for s in sentences
                if 15 < len(s.strip()) < 200
            ][:3]

        # Summary = first 2 meaningful sentences
        clean_block = re.sub(r'[#*_\[\]]', '', content_block)
        sentences = re.split(r'(?<=[.!?])\s+', clean_block)
        summary_parts = [
            s.strip()
            for s in sentences[:3]
            if len(s.strip()) > 20
        ]
        summary = ' '.join(summary_parts)[:300]

        title_map = {
            "challenge": "The Challenge",
            "solution": "The Solution",
            "outcome": "The Outcome",
        }

        sections.append({
            "section_type": section_type,
            "title": title_map.get(section_type, section_type.title()),
            "content": summary,
            "bullets": bullets,
        })

    # ── Build VP infographic ──
    # Try to extract a title from the document
    title_match = re.search(r'#+\s*(.{5,80}?)(?:\n|$)', text[:500])
    title = title_match.group(1).strip() if title_match else "Value Proposition"

    infographic: Dict[str, Any] = {
        "title": title[:100],
        "type": "value_proposition",
        "sections": sections,
    }

    # Also extract metrics and highlights for the VP template
    metrics = _extract_metrics(text)
    if metrics:
        infographic["key_metrics"] = metrics[:6]

    highlights = _extract_highlights(text)
    if highlights:
        infographic["highlights"] = highlights[:4]

    return infographic


def _extract_metrics(text: str) -> List[Dict[str, str]]:
    """Extract quantitative metrics from text — pharma, chemistry, and general."""
    metrics = []
    seen = set()

    # Pattern: "IC50: 5.2 nM", "EC50 = 10 μM", "Ki: 3.1 nM"
    pharma_patterns = [
        (r'(?:IC|EC|ED|LD|TD|CC)[\s_]*50\s*[:=≈]\s*([0-9.,]+\s*\S+)', '💊'),
        (r'K[id]\s*[:=≈]\s*([0-9.,]+\s*\S+)', '🎯'),
        (r'AUC\s*[:=≈]\s*([0-9.,]+[^.\n]{0,20})', '📊'),
        (r't½\s*[:=≈]\s*([0-9.,]+\s*\S+)', '⏱️'),
        (r'half[- ]life\s*[:=of]*\s*([0-9.,]+\s*\S+)', '⏱️'),
        (r'(?:Phase|phase)\s+(I{1,3}[Vv]?|[1-4])\b', '🔬'),
        (r'(\d{4})\s*(?:FDA|EMA)\s*approv', '✅'),
        (r'bioavailability\s*[:=of]*\s*([0-9.,]+\s*%?)', '💉'),
        (r'clearance\s*[:=of]*\s*([0-9.,]+[^.\n]{0,15})', '🔄'),
    ]

    # Chemistry / structural patterns
    chemistry_patterns = [
        (r'molecular\s+weight\s*[:=of]*\s*([0-9.,]+\s*(?:g/mol|Da|kDa)?)', 'Molecular Weight', '⚗️'),
        (r'MW\s*[:=≈]\s*([0-9.,]+\s*(?:g/mol|Da|kDa)?)', 'Molecular Weight', '⚗️'),
        (r'molecular\s+formula\s*[:=of]*\s*([A-Z][A-Za-z0-9₀-₉]+)', 'Molecular Formula', '🧪'),
        (r'(?:Log\s*P|logP|cLogP)\s*[:=≈]\s*([+-]?[0-9.,]+)', 'LogP', '📐'),
        (r'pKa\s*[:=≈]\s*([0-9.,]+)', 'pKa', '📐'),
        (r'(?:melting\s+point|m\.?p\.?)\s*[:=of]*\s*([0-9.,]+\s*°?\s*C?)', 'Melting Point', '🌡️'),
        (r'(?:boiling\s+point|b\.?p\.?)\s*[:=of]*\s*([0-9.,]+\s*°?\s*C?)', 'Boiling Point', '🌡️'),
        (r'solubility\s*[:=of]*\s*([0-9.,]+[^.\n]{0,20})', 'Solubility', '💧'),
        (r'(?:TPSA|polar\s+surface\s+area)\s*[:=of]*\s*([0-9.,]+\s*(?:Å²?)?)', 'TPSA', '📐'),
        (r'(?:protein\s+binding|PPB)\s*[:=of]*\s*([0-9.,]+\s*%?)', 'Protein Binding', '🔗'),
        (r'(?:Vd|volume\s+of\s+distribution)\s*[:=of]*\s*([0-9.,]+[^.\n]{0,15})', 'Vd', '📦'),
        (r'(?:Cmax|C_max)\s*[:=of]*\s*([0-9.,]+[^.\n]{0,15})', 'Cmax', '📈'),
        (r'(?:Tmax|T_max)\s*[:=of]*\s*([0-9.,]+[^.\n]{0,15})', 'Tmax', '⏱️'),
        (r'(?:H-bond\s+donors?|HBD)\s*[:=of]*\s*(\d+)', 'H-Bond Donors', '🔗'),
        (r'(?:H-bond\s+acceptors?|HBA)\s*[:=of]*\s*(\d+)', 'H-Bond Acceptors', '🔗'),
        (r'(?:rotatable\s+bonds?)\s*[:=of]*\s*(\d+)', 'Rotatable Bonds', '🔄'),
        (r'CAS\s*(?:number|#|no\.?)?\s*[:=]?\s*([0-9]+-[0-9]+-[0-9]+)', 'CAS Number', '🏷️'),
    ]

    for pattern, icon in pharma_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()[:30]
            # Determine label from pattern
            label_match = re.search(r'(IC50|EC50|Ki|Kd|AUC|half.life|t½|Phase|approv|bioavail|clearance)',
                                    match.group(0), re.IGNORECASE)
            label = label_match.group(1).strip() if label_match else "Metric"
            label = label.replace('half-life', 'Half-life').replace('half life', 'Half-life')

            key = label.lower()
            if key not in seen:
                seen.add(key)
                metrics.append({"label": label, "value": value, "icon": icon})

    # Chemistry patterns (with pre-defined labels)
    for pattern, label, icon in chemistry_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and label.lower() not in seen:
            seen.add(label.lower())
            metrics.append({"label": label, "value": match.group(1).strip()[:30], "icon": icon})

    # Generic number extraction: "X patients", "X% response rate"
    generic_patterns = [
        (r'(\d[\d,]+)\s+patients?\b', 'Patients', '👥'),
        (r'(\d+(?:\.\d+)?)\s*%\s*(?:response|survival|remission|efficacy)',
         'Response Rate', '📈'),
        (r'p\s*[<=]\s*(0\.\d+)', 'p-value', '📐'),
        (r'hazard ratio\s*[:=of]*\s*([0-9.,]+)', 'Hazard Ratio', '⚖️'),
        (r'(\d+)\s*(?:clinical )?trials?\b', 'Clinical Trials', '🏥'),
    ]

    for pattern, label, icon in generic_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and label.lower() not in seen:
            seen.add(label.lower())
            metrics.append({"label": label, "value": match.group(1).strip()[:30], "icon": icon})

    return metrics


def _extract_highlights(text: str) -> List[Dict[str, str]]:
    """Extract key takeaways from bold text and important sentences."""
    highlights = []

    # Extract bold text: **important statement**
    bolds = re.findall(r'\*\*([^*]{10,120})\*\*', text)
    for bold in bolds[:6]:
        # Skip headings and labels
        if bold.endswith(':') or bold.startswith('#'):
            continue
        # Classify type
        bold_lower = bold.lower()
        if any(w in bold_lower for w in ['warning', 'caution', 'risk', 'adverse', 'contraind', 'black box']):
            htype = 'warning'
        elif any(w in bold_lower for w in ['approved', 'benefit', 'effective', 'success', 'positive']):
            htype = 'success'
        elif any(w in bold_lower for w in ['note', 'important', 'key', 'critical']):
            htype = 'info'
        else:
            htype = 'info'

        highlights.append({"text": bold.strip()[:120], "type": htype})

    # If no bold text found, extract first sentences with key indicators
    if not highlights:
        sentences = re.split(r'(?<=[.!?])\s+', text[:2000])
        for sent in sentences:
            sent_clean = re.sub(r'[#*_\[\]]', '', sent).strip()
            if len(sent_clean) < 20 or len(sent_clean) > 150:
                continue
            if any(kw in sent_clean.lower() for kw in
                   ['important', 'key', 'significant', 'notably', 'critical',
                    'recommend', 'conclude', 'finding', 'result']):
                highlights.append({"text": sent_clean[:120], "type": "info"})
                if len(highlights) >= 4:
                    break

    return highlights


def _fallback_infographic(text: str) -> Dict[str, Any]:
    """
    Generate a guaranteed fallback infographic from any response.

    Called when _extract_metrics, _extract_highlights, and _extract_steps
    all return empty.  Extracts the first meaningful sentences as highlights
    and counts structural signals (word count, sections, etc.) as metrics.
    """
    infographic: Dict[str, Any] = {
        "title": "Council Response Summary",
        "type": "fallback",
    }

    # Count structural features as metrics
    metrics = []
    word_count = len(text.split())
    if word_count > 0:
        metrics.append({"label": "Word Count", "value": str(word_count), "icon": "📝"})

    section_count = len(re.findall(r'#{2,4}\s+', text))
    if section_count > 0:
        metrics.append({"label": "Sections", "value": str(section_count), "icon": "📑"})

    bold_count = len(re.findall(r'\*\*[^*]+\*\*', text))
    if bold_count > 0:
        metrics.append({"label": "Key Terms", "value": str(bold_count), "icon": "🔑"})

    code_count = len(re.findall(r'```', text)) // 2
    if code_count > 0:
        metrics.append({"label": "Code Blocks", "value": str(code_count), "icon": "💻"})

    list_items = len(re.findall(r'(?:^|\n)\s*[-*•]\s+', text))
    if list_items > 0:
        metrics.append({"label": "List Items", "value": str(list_items), "icon": "📋"})

    # SMILES or molecular formulas
    smiles_count = len(re.findall(r'`[A-Z][A-Za-z0-9@+\-\[\]()=#/\\]{5,}`', text))
    if smiles_count > 0:
        metrics.append({"label": "Molecules", "value": str(smiles_count), "icon": "🧬"})

    if metrics:
        infographic["key_metrics"] = metrics[:6]

    # Extract first 2-4 meaningful sentences as highlights
    highlights = []
    sentences = re.split(r'(?<=[.!?])\s+', re.sub(r'[#*_]', '', text[:3000]))
    for sent in sentences:
        sent = sent.strip()
        if 25 < len(sent) < 150:
            highlights.append({"text": sent[:140], "type": "info"})
            if len(highlights) >= 3:
                break

    if highlights:
        infographic["highlights"] = highlights

    return infographic


def _extract_steps(text: str) -> List[Dict[str, Any]]:
    """Extract process/mechanism steps from numbered lists or headings."""
    steps = []

    # Look for numbered items: "1. Step title" or "1) Step title"
    numbered = re.findall(
        r'(?:^|\n)\s*(\d+)[.)]\s+\*{0,2}([^\n*]{5,80})\*{0,2}',
        text
    )
    for num, title in numbered[:6]:
        steps.append({
            "step": int(num),
            "title": title.strip().rstrip(':'),
            "description": "",
        })

    # If no numbered steps, try headings: "### Step Title"
    if not steps:
        headings = re.findall(r'#{2,4}\s+(.{5,60})', text)
        for i, heading in enumerate(headings[:6], 1):
            # Skip generic headings
            if heading.lower() in ('references', 'summary', 'conclusion',
                                   'introduction', 'overview'):
                continue
            steps.append({
                "step": i,
                "title": heading.strip(),
                "description": "",
            })

    return steps


def _validate_and_clean(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and clean infographic data structure."""
    clean: Dict[str, Any] = {
        "title": str(data.get("title", "Summary"))[:200],
        "type": str(data.get("type", "summary")),
    }

    # key_metrics — generous limits for research data visibility
    if "key_metrics" in data and isinstance(data["key_metrics"], list):
        clean["key_metrics"] = [
            {
                "label": str(m.get("label", ""))[:100],
                "value": str(m.get("value", ""))[:80],
                "icon": str(m.get("icon", "📊"))[:4],
            }
            for m in data["key_metrics"][:8]
            if isinstance(m, dict) and m.get("label")
        ]

    # comparison
    if "comparison" in data and isinstance(data["comparison"], dict):
        comp = data["comparison"]
        if "headers" in comp and "rows" in comp:
            clean["comparison"] = {
                "headers": [str(h)[:80] for h in comp["headers"][:8]],
                "rows": [
                    [str(c)[:100] for c in row[:8]]
                    for row in comp["rows"][:12]
                ],
            }

    # process_steps
    if "process_steps" in data and isinstance(data["process_steps"], list):
        clean["process_steps"] = [
            {
                "step": int(s.get("step", i + 1)),
                "title": str(s.get("title", ""))[:120],
                "description": str(s.get("description", ""))[:300],
            }
            for i, s in enumerate(data["process_steps"][:8])
            if isinstance(s, dict) and s.get("title")
        ]

    # highlights
    if "highlights" in data and isinstance(data["highlights"], list):
        valid_types = {"success", "warning", "info", "danger"}
        clean["highlights"] = [
            {
                "text": str(h.get("text", ""))[:400],
                "type": str(h.get("type", "info")) if h.get("type") in valid_types else "info",
            }
            for h in data["highlights"][:6]
            if isinstance(h, dict) and h.get("text")
        ]

    # sections (value_proposition type)
    if "sections" in data and isinstance(data["sections"], list):
        valid_section_types = {"challenge", "solution", "outcome"}
        clean["sections"] = [
            {
                "section_type": str(s.get("section_type", "")).lower()
                    if str(s.get("section_type", "")).lower() in valid_section_types
                    else "info",
                "title": str(s.get("title", ""))[:150],
                "content": str(s.get("content", ""))[:1000],
                "bullets": [
                    str(b)[:400] for b in (s.get("bullets") or [])[:8]
                ],
            }
            for s in data["sections"][:4]
            if isinstance(s, dict) and s.get("title")
        ]

    return clean
