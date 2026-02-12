"""
Infographic extraction from Chairman Stage 3 responses.

Parses structured JSON infographic data from the chairman's output
and provides a fallback auto-extraction when the chairman doesn't
include the infographic block.
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

    Scans for:
      - Headings → process steps
      - Numbers/stats → key metrics
      - Bold items → highlights
    """
    infographic: Dict[str, Any] = {
        "title": "Council Response Summary",
        "type": "auto",
    }

    # Extract key metrics: look for patterns like "IC50: 5.2 nM" or "Phase III"
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

    # Only return if we found something meaningful
    if metrics or highlights:
        return infographic
    return None


def _extract_metrics(text: str) -> List[Dict[str, str]]:
    """Extract quantitative metrics from text."""
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
        "title": str(data.get("title", "Summary"))[:100],
        "type": str(data.get("type", "summary")),
    }

    # key_metrics
    if "key_metrics" in data and isinstance(data["key_metrics"], list):
        clean["key_metrics"] = [
            {
                "label": str(m.get("label", ""))[:40],
                "value": str(m.get("value", ""))[:30],
                "icon": str(m.get("icon", "📊"))[:4],
            }
            for m in data["key_metrics"][:6]
            if isinstance(m, dict) and m.get("label")
        ]

    # comparison
    if "comparison" in data and isinstance(data["comparison"], dict):
        comp = data["comparison"]
        if "headers" in comp and "rows" in comp:
            clean["comparison"] = {
                "headers": [str(h)[:40] for h in comp["headers"][:6]],
                "rows": [
                    [str(c)[:40] for c in row[:6]]
                    for row in comp["rows"][:8]
                ],
            }

    # process_steps
    if "process_steps" in data and isinstance(data["process_steps"], list):
        clean["process_steps"] = [
            {
                "step": int(s.get("step", i + 1)),
                "title": str(s.get("title", ""))[:60],
                "description": str(s.get("description", ""))[:120],
            }
            for i, s in enumerate(data["process_steps"][:6])
            if isinstance(s, dict) and s.get("title")
        ]

    # highlights
    if "highlights" in data and isinstance(data["highlights"], list):
        valid_types = {"success", "warning", "info", "danger"}
        clean["highlights"] = [
            {
                "text": str(h.get("text", ""))[:150],
                "type": str(h.get("type", "info")) if h.get("type") in valid_types else "info",
            }
            for h in data["highlights"][:4]
            if isinstance(h, dict) and h.get("text")
        ]

    return clean
