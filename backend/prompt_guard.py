"""
Prompt Suitability Guard — Pre-Stage Gate for LLM Council.

Evaluates whether a user prompt is appropriate for the pharmaceutical
/ life-sciences LLM Council before any stage is triggered.  If the
prompt is deemed unsuitable the conversation is marked as blocked and
a polite, policy-aligned rejection is returned.

Rejection categories
────────────────────
  1. OFF-TOPIC          — Not related to pharma, healthcare, life sciences,
                          chemistry, biology, medicine, or clinical research
  2. HARMFUL_CONTENT    — Violent, hateful, discriminatory, sexually explicit,
                          or otherwise harmful content
  3. ILLEGAL_ACTIVITY   — Requests for illicit drug synthesis, controlled
                          substance acquisition, or unlicensed dispensing
  4. PERSONAL_DATA      — Requests involving real patient PII / PHI
  5. PROMPT_INJECTION   — Attempts to override system instructions,
                          jailbreak, or exfiltrate internal prompts
  6. TRIVIAL            — Prompts with no meaningful content (empty, single
                          character, gibberish, etc.)

The guard is intentionally conservative: it should only block clearly
unsuitable prompts and let borderline queries through so the council
models can handle them.
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("llm_council.prompt_guard")

# ── Constants ────────────────────────────────────────────────────────

MIN_PROMPT_LENGTH = 5          # Minimum meaningful prompt length
MAX_GIBBERISH_RATIO = 0.65     # If >65 % non-alpha chars → likely gibberish
LLM_GUARD_TIMEOUT = 12.0       # Timeout for LLM relevance check (seconds)


# ── Result dataclass ─────────────────────────────────────────────────

@dataclass
class GuardVerdict:
    """Result of the prompt suitability check."""
    allowed: bool
    category: Optional[str] = None        # e.g. "OFF_TOPIC", "HARMFUL_CONTENT"
    message: Optional[str] = None         # polite user-facing message
    internal_reason: Optional[str] = None # debug-only detail (never shown)


# ── Rejection messages (aligned with AI guidelines & policies) ───────

_REJECTION_MESSAGES = {
    "TRIVIAL": (
        "Thank you for reaching out. It seems your message doesn't contain "
        "a substantive query for the Council to deliberate on. Please start "
        "a **new conversation** with a clear question related to "
        "pharmaceutical sciences, drug safety, clinical research, or "
        "life-science topics, and the Council will be happy to assist."
    ),
    "HARMFUL_CONTENT": (
        "We appreciate your engagement, however the LLM Council is unable to "
        "process requests that contain harmful, hateful, violent, or "
        "inappropriate content. This platform is governed by Bayer's "
        "Responsible AI Policy and is dedicated solely to supporting "
        "evidence-based pharmaceutical and life-science inquiries.\n\n"
        "Please start a **new conversation** with a professionally "
        "appropriate question, and the Council will be glad to help."
    ),
    "ILLEGAL_ACTIVITY": (
        "The LLM Council is designed to support legitimate pharmaceutical "
        "research, drug safety, and clinical science inquiries. We are "
        "unable to provide guidance on the synthesis, acquisition, or "
        "distribution of controlled substances outside of licensed and "
        "regulated frameworks.\n\n"
        "If you have a lawful scientific question, please start a "
        "**new conversation** and the Council will be happy to assist."
    ),
    "PERSONAL_DATA": (
        "To protect patient privacy and comply with data-protection "
        "regulations (GDPR, HIPAA), the LLM Council cannot process "
        "requests that contain or seek personally identifiable information "
        "(PII) or protected health information (PHI) of real individuals.\n\n"
        "Please start a **new conversation** with de-identified or "
        "hypothetical scenarios, and the Council will be glad to help."
    ),
    "PROMPT_INJECTION": (
        "The LLM Council has detected content that appears to attempt to "
        "modify the system's operating instructions. For the safety and "
        "integrity of all users, such requests cannot be processed.\n\n"
        "Please start a **new conversation** with a genuine "
        "pharmaceutical or life-science question, and the Council will "
        "be happy to assist."
    ),
    "OFF_TOPIC": (
        "Thank you for your query. The LLM Council is a specialised "
        "platform powered by multiple AI models, purpose-built for "
        "**pharmaceutical sciences, drug safety, clinical research, "
        "molecular biology, chemistry, and healthcare** topics.\n\n"
        "Your question does not appear to fall within these domains. "
        "To ensure you receive the most accurate and evidence-grounded "
        "response, please start a **new conversation** with a question "
        "related to the life sciences, and the Council will be delighted "
        "to assist."
    ),
}


# ── Pattern banks ────────────────────────────────────────────────────

# Harmful / hateful / violent / sexual content patterns
_HARMFUL_PATTERNS = re.compile(
    r'\b(?:'
    r'kill\s+(?:all|every|those)|exterminate|genocide|ethnic\s+cleansing|'
    r'white\s+(?:supremacy|power|nationalist)|nazi|'
    r'racial\s+(?:purity|superiority|inferiority)|'
    r'(?:hate|harass|stalk|threaten)\s+(?:gays?|jews?|muslims?|blacks?|women|immigrants?)|'
    r'child\s+(?:porn|exploitation|abuse)|'
    r'how\s+to\s+(?:make\s+a\s+bomb|build\s+(?:a\s+)?weapon|poison\s+(?:someone|people))|'
    r'sex\s+with\s+(?:minor|child|underage)|'
    r'rape\s+(?:fantasy|guide|how\s+to)'
    r')\b',
    re.IGNORECASE,
)

# Illegal drug synthesis / controlled substance patterns
_ILLEGAL_PATTERNS = re.compile(
    r'\b(?:'
    r'how\s+to\s+(?:synthesize?|cook|make|produce|manufacture)\s+'
    r'(?:meth|methamphetamine|fentanyl|heroin|cocaine|crack|lsd|mdma|ecstasy|ghb|pcp)|'
    r'buy\s+(?:drugs?\s+)?(?:without\s+(?:a\s+)?prescription|illegally|on\s+(?:the\s+)?(?:dark|black)\s*(?:web|market|net))|'
    r'how\s+to\s+(?:get|obtain)\s+(?:opioids?|benzodiazepines?|stimulants?)\s+without\s+'
    r'(?:doctor|prescription|rx)|'
    r'(?:dark\s*web|silk\s*road)\s+(?:drug|pharma)|'
    r'counterfeit\s+(?:medication|pills?|drugs?|prescription)'
    r')\b',
    re.IGNORECASE,
)

# Prompt injection / jailbreak patterns
_INJECTION_PATTERNS = re.compile(
    r'(?:'
    r'ignore\s+(?:all\s+)?(?:previous|above|prior|system)\s+(?:instructions?|prompts?|rules?)|'
    r'you\s+are\s+(?:now\s+)?(?:DAN|an?\s+unrestricted|jailbroken)|'
    r'system\s*:\s*you\s+(?:are|will|must|can)|'
    r'pretend\s+(?:you\s+(?:are|have)\s+)?(?:no\s+(?:restrictions?|guidelines?|rules?))|'
    r'bypass\s+(?:your\s+)?(?:safety|content|ethical)\s+(?:filters?|guidelines?|restrictions?)|'
    r'repeat\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)\s+(?:verbatim|exactly|word\s+for\s+word)|'
    r'what\s+(?:are|is)\s+your\s+(?:system\s+)?(?:prompt|instructions?|rules?)\b|'
    r'reveal\s+(?:your\s+)?(?:hidden|secret|system)\s+(?:prompt|instructions?)|'
    r'(?:developer|admin|sudo|root)\s+mode\s+(?:on|enabled|activate)|'
    r'override\s+(?:content|safety|ethical)\s+(?:policy|filter|restriction)'
    r')',
    re.IGNORECASE,
)

# PII / PHI patterns (SSN, real patient names with medical context, etc.)
# NOTE: SSN regex requires dash or space separators (NOT dots) to avoid
#       false positives on DOIs, lab values, and scientific identifiers.
#       e.g. DOI "10.2174/138161282" or concentration "138.16.1282 pg/mL"
#       would previously false-match the SSN pattern.
_PII_PATTERNS = re.compile(
    r'(?:'
    r'\b\d{3}[-\s]\d{2}[-\s]\d{4}\b|'                # SSN (123-45-6789 or 123 45 6789)
    r'\b(?:patient|subject)\s+(?:name|id)\s*(?:is|:)\s*[A-Z][a-z]+\s+[A-Z][a-z]+|'  # "patient name is John Doe"
    r'\bMRN\s*(?::|is|=)\s*\d{5,}|'                      # Medical Record Number
    r'\b(?:date\s+of\s+birth|DOB)\s*(?::|is|=)\s*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}'  # DOB
    r')',
    re.IGNORECASE,
)

# Scientific number patterns stripped before PII check to prevent
# DOIs, PMIDs, and other identifiers from triggering false positives.
_SCIENTIFIC_NUMBERS = re.compile(
    r'(?:'
    r'10\.\d{4,}/[^\s]+|'        # DOIs (10.xxxx/...)
    r'\bPMID\s*:?\s*\d{5,}|'     # PMID references
    r'\bPMC\d{5,}|'              # PMC IDs
    r'\bISSN\s*:?\s*\d{4}-\d{4}' # ISSNs
    r')',
    re.IGNORECASE,
)


# ── On-topic keyword bank ───────────────────────────────────────────
# If the prompt contains ANY of these, it's likely pharma/science-related.

_ONTOPIC_KEYWORDS = re.compile(
    r'\b(?:'
    # Pharmacology & Drug Science
    r'drug|pharma|pharmaceutical|medication|medicine|prescription|dosage|'
    r'dose|dosing|formulation|excipient|bioavailability|pharmacokinetic|'
    r'pharmacodynamic|half[\-\s]?life|clearance|absorption|metabolism|'
    r'distribution|elimination|API|active\s+pharmaceutical|generic|'
    r'biosimilar|biologic|monoclonal|antibody|vaccine|immunotherapy|'
    # Clinical & Medical
    r'clinical\s+trial|FDA|EMA|regulatory|approval|indication|'
    r'contraindication|adverse\s+event|side\s+effect|efficacy|safety|'
    r'toxicity|teratogenic|carcinogenic|mutagenic|LD50|IC50|EC50|'
    r'therapeutic|treatment|therapy|diagnosis|prognosis|symptom|'
    r'disease|disorder|syndrome|pathology|oncology|cardiology|'
    r'neurology|immunology|endocrinology|hematology|dermatology|'
    r'gastroenterology|pulmonology|nephrology|urology|psychiatry|'
    r'forensic\s+medicine|forensic\s+pathology|forensic\s+toxicology|'
    r'forensic\s+science|autopsy|post[\-\s]?mortem|cause\s+of\s+death|'
    r'medico[\-\s]?legal|death\s+investigation|forensic\s+examination|'
    r'radiology|anesthesiology|ophthalmology|otolaryngology|'
    r'rheumatology|geriatrics|pediatrics|neonatology|'
    r'emergency\s+medicine|sports\s+medicine|nuclear\s+medicine|'
    r'palliative\s+care|rehabilitation|orthopedics|'
    r'patient|physician|nurse|healthcare|hospital|clinic|'
    # Chemistry
    r'molecule|compound|chemical|reaction|synthesis|mechanism|'
    r'structure|SMILES|InChI|molecular\s+weight|solubility|pKa|logP|'
    r'stereochemistry|enantiomer|isomer|chirality|functional\s+group|'
    r'organic|inorganic|polymer|protein|peptide|amino\s+acid|'
    r'nucleotide|DNA|RNA|gene|genome|enzyme|receptor|ligand|'
    r'agonist|antagonist|inhibitor|substrate|catalyst|'
    # Biology & Life Sciences
    r'cell|tissue|organ|pathway|signaling|expression|mutation|'
    r'variant|genotype|phenotype|biomarker|assay|in[\-\s]?vitro|'
    r'in[\-\s]?vivo|ex[\-\s]?vivo|preclinical|clinical|phase\s+[1234I]+|'
    r'cohort|randomized|placebo|blind|endpoint|outcome|survival|'
    r'response\s+rate|hazard\s+ratio|confidence\s+interval|'
    r'p[\-\s]?value|statistical|meta[\-\s]?analysis|systematic\s+review|'
    # Well-known drug names (partial — catches most queries)
    r'aspirin|ibuprofen|metformin|atorvastatin|omeprazole|lisinopril|'
    r'amlodipine|losartan|gabapentin|sertraline|levothyroxine|'
    r'pembrolizumab|nivolumab|trastuzumab|bevacizumab|rituximab|'
    r'adalimumab|semaglutide|tirzepatide|ozempic|wegovy|mounjaro|'
    r'insulin|warfarin|heparin|acetaminophen|paracetamol|amoxicillin|'
    # General scientific
    r'research|study|literature|evidence|hypothesis|experiment|'
    r'data\s+analysis|mechanism\s+of\s+action|ADME|'
    r'toxicology|pharmacovigilance|'
    r'PubMed|ClinicalTrials|DailyMed|DrugBank|RCSB|PDB|UniProt'
    r')\b',
    re.IGNORECASE,
)

# Short acronyms that cause false positives with IGNORECASE
# (e.g. "who" matching WHO, "api" matching API).
# Checked case-sensitively.
_CASE_SENSITIVE_ACRONYMS = re.compile(
    r'\b(?:WHO|NIH|CDC|ICH|GMP|GCP|GLP|MOA|PK|PD|API)\b'
)

# Common off-topic categories (entertainment, sports, cooking non-pharma, etc.)
_OFFTOPIC_STRONG = re.compile(
    r'\b(?:'
    r'football|soccer|basketball|baseball|cricket|tennis|super\s*bowl|'
    r'world\s+cup|olympics?|championship|tournament|league|'
    r'movie|film|tv\s+show|netflix|anime|manga|disney|marvel|'
    r'recipe|cooking|bake|ingredients\s+for\s+(?:cake|pie|bread|soup|pasta)|'
    # Food / meals / casual daily-life (not pharma-relevant)
    r'pizza|burger|sushi|tacos?|sandwich|breakfast|lunch|dinner|dessert|'
    r'restaurant|fast\s+food|takeout|delivery|groceries|'
    r'stock\s+(?:price|market|portfolio|trading)|'
    r'cryptocurrency|bitcoin|ethereum|NFT|'
    r'write\s+(?:a\s+)?(?:poem|song|story|novel|essay\s+about\s+(?!drug|pharma|medicine|health))|'
    r'play\s+(?:a\s+)?game|video\s+game|minecraft|fortnite|'
    r'tell\s+(?:me\s+)?a\s+joke|funny\s+(?:story|joke)|'
    r'celebrity|gossip|horoscope|astrology|zodiac|'
    r'capital\s+of\s+(?!pharma)|president\s+of|prime\s+minister|'
    r'weather\s+(?:in|at|forecast)|'
    r'travel\s+(?:to|in|guide)|vacation|hotel|flight\s+(?:to|from)|'
    r'real\s+estate|mortgage|home\s+(?:loan|buying)|'
    r'dating|relationship\s+advice|'
    r'who\s+won\s+(?:the\s+)?(?:game|match|election|race|award|oscar)|'
    # Pets / hobbies / shopping (non-pharma)
    r'(?:adopt|buy)\s+(?:a\s+)?(?:puppy|kitten|dog|cat)|'
    r'fashion|outfit|clothing|shoes|sneakers|'
    r'furniture|interior\s+design|home\s+decor|'
    # Greetings / small talk with no question
    r'good\s+(?:morning|afternoon|evening|night)|'
    r"how\s+are\s+you|what\s*(?:is|'\s*s)\s+your\s+name|"
    r'(?:car|auto)\s+(?:insurance|repair|lease|loan)'
    r')\b',
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════
# LLM relevance check prompt (for ambiguous queries)
# ═══════════════════════════════════════════════════════════════════

_RELEVANCE_SYSTEM = """You are a gate-keeper for a pharmaceutical and life-sciences LLM council.
Your ONLY job is to decide whether a user's query is related to ANY of these domains:
  - Pharmaceutical sciences, drugs, medications, drug safety
  - Clinical research, clinical trials, regulatory affairs
  - Medicine, healthcare, disease, diagnosis, treatment
  - Chemistry, biochemistry, molecular biology
  - Genomics, proteomics, bioinformatics
  - Toxicology, pharmacovigilance, pharmacology
  - Biotechnology, bioprocessing, biologics
  - Public health, epidemiology
  - Medical devices (if related to therapy/diagnosis)
  - Forensic medicine, forensic pathology, forensic toxicology, medico-legal science
  - Any medical speciality (radiology, anaesthesiology, ophthalmology, orthopaedics, etc.)

Rules:
- If the query is clearly about one of these domains → respond EXACTLY: YES
- If the query mentions ANY medical speciality, field of medicine, or healthcare discipline → respond EXACTLY: YES
- If the query mentions a term you do not recognise and it is NOT clearly a scientific/medical term → respond EXACTLY: NO
- If the query is about general knowledge, entertainment, technology, coding, business, sports, cooking, travel, or any non-life-science topic → respond EXACTLY: NO
- When file attachments are mentioned (e.g. [Attachments: filename.png]), consider the filename as additional context — a file named 'forensic medicine.png' implies a medical topic
- If the prompt includes extracted text from attached documents (after '---\nAttached Files:'), evaluate the EXTRACTED CONTENT for domain relevance, not just the user's short query
- If the user is asking about "this document" / "the file" / "attached data" and the extracted content appears scientific or medical, respond: YES
- Do NOT guess. If you cannot confidently place the query in a life-science domain, respond: NO
- Respond with ONLY one word: YES or NO"""


# ═══════════════════════════════════════════════════════════════════
# Main guard function (async — supports LLM relevance check)
# ═══════════════════════════════════════════════════════════════════

# ── Document-referencing patterns ────────────────────────────────
# Queries that clearly reference an attached document/file should be
# allowed through when attachments are present — the guard cannot
# evaluate document *content* from the query text alone.
_DOCUMENT_REF_PATTERNS = re.compile(
    r'(?:'
    r'(?:this|the|that|my|attached|uploaded)\s+'
    r'(?:document|file|paper|report|pdf|image|slide|spreadsheet|data|attachment|presentation|table|figure|chart|letter)|'
    r'(?:summarize?|summarise?|analyze|analyse|extract|infer|review|examine|interpret|read|parse|describe)\s+'
    r'(?:this|the|that|it|these|those|what)|'
    r'(?:drawn|extracted|inferred|concluded|derived|identified|found)\s+'
    r'(?:from|in)\s+(?:this|the|that|it)|'
    r'(?:what|which|how|who|where)\s+.*?\b(?:document|file|attachment|paper|report|pdf|slide|table)\b|'
    r'\b(?:main|key|important|critical|relevant)\s+'
    r'(?:findings?|points?|takeaways?|conclusions?|inferences?|insights?|items?)\s+'
    r'(?:from|in|of)\s+(?:this|the|that)'
    r')',
    re.IGNORECASE,
)


# ── Targeted follow-up patterns ─────────────────────────────────
# Messages that reference a specific Stage or model response are
# post-processing requests on already-validated council output
# (translate, summarise, simplify, etc.).  Safety checks still run
# but the on-topic / off-topic gate is bypassed.
_FOLLOWUP_PREFIX_KW = (
    r'(?:Regarding|About|Re:?|On|For|Expand\s+on|Elaborate\s+on|'
    r'Tell\s+me\s+more\s+about|More\s+on|Concerning)'
)
_FOLLOWUP_REF_PATTERNS = re.compile(
    rf"^{_FOLLOWUP_PREFIX_KW}\s+"
    r"(?:Stage\s*\d"
    "|.+?(?:'s|\u2018s|\u2019s)\\s+response"
    ")",
    re.IGNORECASE,
)


async def evaluate_prompt(prompt: str, *, has_attachments: bool = False) -> GuardVerdict:
    """
    Evaluate whether a user prompt is suitable for the LLM Council.

    Uses fast regex checks first, then falls back to a quick LLM
    relevance check (gemini-2.5-flash) for ambiguous queries that
    don't match any on-topic or off-topic keyword bank.

    Args:
        prompt: The raw user prompt text (may include extracted
                attachment content when files are attached).
        has_attachments: True when the request includes file uploads.
                         Enables document-reference bypass so queries
                         like "summarize this document" pass through.

    Returns:
        GuardVerdict with allowed=True if the prompt may proceed,
        or allowed=False with category and polite rejection message.
    """
    # ── 1. Trivial / empty ─────────────────────────────────────────
    if not prompt or not prompt.strip():
        return GuardVerdict(
            allowed=False,
            category="TRIVIAL",
            message=_REJECTION_MESSAGES["TRIVIAL"],
            internal_reason="Empty prompt",
        )

    cleaned = prompt.strip()

    if len(cleaned) < MIN_PROMPT_LENGTH:
        return GuardVerdict(
            allowed=False,
            category="TRIVIAL",
            message=_REJECTION_MESSAGES["TRIVIAL"],
            internal_reason=f"Prompt too short ({len(cleaned)} chars)",
        )

    # Check gibberish ratio (non-alpha / total)
    alpha_count = sum(1 for c in cleaned if c.isalpha() or c.isspace())
    if len(cleaned) > 10 and alpha_count / len(cleaned) < (1 - MAX_GIBBERISH_RATIO):
        return GuardVerdict(
            allowed=False,
            category="TRIVIAL",
            message=_REJECTION_MESSAGES["TRIVIAL"],
            internal_reason=f"Gibberish ratio too high ({alpha_count}/{len(cleaned)})",
        )

    # ── 2. Harmful / hateful / violent ─────────────────────────────
    if _HARMFUL_PATTERNS.search(cleaned):
        logger.warning(f"[PromptGuard] BLOCKED — harmful content detected")
        return GuardVerdict(
            allowed=False,
            category="HARMFUL_CONTENT",
            message=_REJECTION_MESSAGES["HARMFUL_CONTENT"],
            internal_reason="Harmful content pattern matched",
        )

    # ── 3. Illegal activity ────────────────────────────────────────
    if _ILLEGAL_PATTERNS.search(cleaned):
        logger.warning(f"[PromptGuard] BLOCKED — illegal activity detected")
        return GuardVerdict(
            allowed=False,
            category="ILLEGAL_ACTIVITY",
            message=_REJECTION_MESSAGES["ILLEGAL_ACTIVITY"],
            internal_reason="Illegal activity pattern matched",
        )

    # ── 4. Prompt injection / jailbreak ────────────────────────────
    if _INJECTION_PATTERNS.search(cleaned):
        logger.warning(f"[PromptGuard] BLOCKED — prompt injection attempt")
        return GuardVerdict(
            allowed=False,
            category="PROMPT_INJECTION",
            message=_REJECTION_MESSAGES["PROMPT_INJECTION"],
            internal_reason="Prompt injection pattern matched",
        )

    # ── 5. PII / PHI ──────────────────────────────────────────────
    # Strip known scientific number formats (DOIs, PMIDs, ISSNs) before
    # checking PII patterns — prevents false positives on academic content.
    cleaned_for_pii = _SCIENTIFIC_NUMBERS.sub(' ', cleaned)
    if _PII_PATTERNS.search(cleaned_for_pii):
        logger.warning(f"[PromptGuard] BLOCKED — PII/PHI detected")
        return GuardVerdict(
            allowed=False,
            category="PERSONAL_DATA",
            message=_REJECTION_MESSAGES["PERSONAL_DATA"],
            internal_reason="PII/PHI pattern matched",
        )

    # ── 5b. Document-reference bypass ──────────────────────────────
    # When the user has uploaded files and their query clearly
    # references "this document" / "the attached file" / etc., the
    # guard cannot judge relevance from the query text alone — the
    # actual content is embedded in augmented_content and will be
    # evaluated by the council models.  Allow through.
    if has_attachments and _DOCUMENT_REF_PATTERNS.search(cleaned):
        logger.info("[PromptGuard] ALLOWED — document-reference query with attachments")
        return GuardVerdict(allowed=True)

    # ── 5c. Targeted follow-up bypass ──────────────────────────────
    # When the user sends a follow-up referencing a specific Stage or
    # model response (e.g. "Regarding Stage 3: translate to German"),
    # this is a post-processing request on already-validated council
    # output.  The original content passed the guard in the first
    # turn, so we allow translation / summarisation / reformatting
    # requests through without re-checking on-topic relevance.
    # Safety checks (harmful, illegal, injection, PII) above still
    # apply to follow-ups.
    if _FOLLOWUP_REF_PATTERNS.search(cleaned):
        logger.info("[PromptGuard] ALLOWED — targeted follow-up reference (Stage/model)")
        return GuardVerdict(allowed=True)

    # ── 6. On-topic / off-topic check ─────────────────────────────
    has_ontopic = bool(_ONTOPIC_KEYWORDS.search(cleaned)) or bool(_CASE_SENSITIVE_ACRONYMS.search(cleaned))
    has_offtopic = bool(_OFFTOPIC_STRONG.search(cleaned))

    # 6a. Clearly off-topic (matches off-topic bank, no on-topic keywords)
    if has_offtopic and not has_ontopic:
        logger.info(f"[PromptGuard] BLOCKED — off-topic query (regex)")
        return GuardVerdict(
            allowed=False,
            category="OFF_TOPIC",
            message=_REJECTION_MESSAGES["OFF_TOPIC"],
            internal_reason="Off-topic pattern matched, no on-topic keywords found",
        )

    # 6b. Clearly on-topic — pass immediately
    if has_ontopic:
        logger.info(f"[PromptGuard] ALLOWED — on-topic keywords found (fast path)")
        return GuardVerdict(allowed=True)

    # ── 7. Ambiguous — No keyword match either way ─────────────────
    # Use a quick LLM check (gemini-2.5-flash) to determine relevance.
    # This catches queries like "What is Clawdbot?" that have no
    # keywords from either bank.
    logger.info(f"[PromptGuard] Ambiguous prompt — running LLM relevance check")
    try:
        from .openrouter import query_model
        messages = [
            {"role": "system", "content": _RELEVANCE_SYSTEM},
            {"role": "user", "content": cleaned},
        ]
        result = await query_model(
            "gemini-2.5-flash", messages, timeout=LLM_GUARD_TIMEOUT
        )
        answer = (result.get("content", "") or "").strip().upper() if result else ""
        logger.info(f"[PromptGuard] LLM relevance verdict: {answer}")

        if answer.startswith("YES"):
            return GuardVerdict(allowed=True)
        else:
            # LLM says NO or ambiguous → block as off-topic
            logger.info(f"[PromptGuard] BLOCKED — LLM determined off-topic")
            return GuardVerdict(
                allowed=False,
                category="OFF_TOPIC",
                message=_REJECTION_MESSAGES["OFF_TOPIC"],
                internal_reason=f"LLM relevance check returned: {answer}",
            )
    except Exception as e:
        # If LLM check fails, err on the side of caution — allow through
        # so the council models can handle it (better than false blocking)
        logger.warning(f"[PromptGuard] LLM relevance check failed: {e} — allowing through")
        return GuardVerdict(allowed=True)
