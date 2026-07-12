"""
council.py — Council XXII–XXIV: 5-Member Council Assessments

Each of the 5 council members reviews the scored result from their assigned lens
(parallel Claude Haiku calls). A synthesis call then produces upgraded statements
and a plain-English brief for non-MEL reporting teams.

Projected scores are calculated deterministically from fixes[].score_impact_value
— the AI does not invent score numbers, preserving the methodology guarantee.

check_fabrication() is a deterministic, machine-checked backstop on the synthesis
call's upgraded statements: any numeral/year/percentage not present in the user's
own submission causes that statement to be withheld rather than shown.
"""

from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# ---------------------------------------------------------------------------
# Council member definitions
# ---------------------------------------------------------------------------

COUNCIL_MEMBERS = [
    {
        "id":        "evidence_auditor",
        "name":      "Evidence Auditor",
        "archetype": "MEL Lead × First Principle",
        "icon":      "\U0001f52c",
        "color":     "#1B5E20",
        "instruction": (
            "You are the Evidence Auditor — a senior MEL officer applying first-principles "
            "scrutiny to evidence quality.\n"
            "Your job: review the 3 Confidence sub-scores (Directness, Verification, Recency). "
            "For each sub-score, explain what the current level means and what single action "
            "would unlock the next level. Focus on the bottleneck first. "
            "Be specific, cite the sub-score numbers, and keep your total response to 4-5 sentences."
        ),
    },
    {
        "id":        "strategist",
        "name":      "Programme Strategist",
        "archetype": "Programme Director × Expansionist",
        "icon":      "\U0001f3af",
        "color":     "#1565C0",
        "instruction": (
            "You are the Programme Strategist — a programme director who thinks about "
            "how results fit the wider programme narrative and donor story.\n"
            "Your job: review the result statement and Clarity score. "
            "Identify one specific weakness in how the result is framed, then propose "
            "an improved result statement (one sentence, in quotes) that fixes it without "
            "overstating the achievement. "
            "Keep your total response to 4-5 sentences."
        ),
    },
    {
        "id":        "contrarian",
        "name":      "Critical Reviewer",
        "archetype": "MEL Consultant × Contrarian",
        "icon":      "⚡",
        "color":     "#6A1B9A",
        "instruction": (
            "You are the Critical Reviewer — a MEL consultant hired to stress-test claims "
            "before donor submission.\n"
            "Your job: name exactly 2 weaknesses that a skeptical donor reviewer would flag. "
            "Number them 1 and 2. Be direct and specific — no softening language. "
            "Do not propose solutions; just name the problems. "
            "Keep your total response to 4-5 sentences."
        ),
    },
    {
        "id":        "executor",
        "name":      "Implementation Guide",
        "archetype": "Tech Architect × Executor",
        "icon":      "\U0001f527",
        "color":     "#E65100",
        "instruction": (
            "You are the Implementation Guide — a technical advisor who turns gaps into "
            "a numbered action plan.\n"
            "Your job: provide exactly 3 concrete fixes, each with a realistic time estimate "
            "in brackets (e.g., [30 min], [1 hour]). "
            "Each fix must be specific enough that a junior MEL officer could execute it "
            "without asking a follow-up question. "
            "Format: '1. [time] — action. 2. [time] — action. 3. [time] — action.' "
            "Keep your total response to 5-6 sentences."
        ),
    },
    {
        "id":        "donor_rep",
        "name":      "Donor Lens",
        "archetype": "Donor Rep × Outsider",
        "icon":      "\U0001f441",
        "color":     "#B71C1C",
        "instruction": (
            "You are the Donor Lens — a donor representative reviewing this result for "
            "the first time, with no MEL background.\n"
            "Your job: write 3-4 sentences in plain English that a programme manager "
            "(not a MEL specialist) can read and immediately understand. "
            "No jargon: avoid words like 'Confidence axis', 'Directness', 'Recency score', "
            "'triangulate', 'USAID ADS 201'. "
            "Instead use: 'the paperwork', 'the evidence', 'the supporting documents', "
            "'the count', 'the date'. "
            "Explain what the score means for whether this result will be accepted by the donor."
        ),
    },
]

_MEMBER_BY_ID = {m["id"]: m for m in COUNCIL_MEMBERS}

# ---------------------------------------------------------------------------
# Shared context builder
# ---------------------------------------------------------------------------

def _build_shared_context(submission: dict, ev: dict) -> str:
    """Structured context block injected into every council member's system prompt."""
    conf   = ev.get("confidence_score", 0)
    clar   = ev.get("clarity_score", 0)
    vc     = ev.get("confidence_components", {})
    cc     = ev.get("clarity_components", {})
    fixes  = ev.get("fixes", [])
    rs     = (submission.get("result_statement") or "")[:500]
    evs    = (submission.get("evidence") or [{}])[0]
    ev_type = evs.get("type", "not specified")
    ev_desc = (evs.get("description") or "")[:300]
    ev_date = evs.get("recency", "not specified")
    review  = submission.get("internal_review", "not specified")
    verdict = ev.get("verdict", "")

    fixes_block = ""
    for i, f in enumerate(fixes[:3], 1):
        fixes_block += f"  Fix {i}: {f.get('message', '')} ({f.get('score_impact', '')})\n"

    return f"""
RESULT UNDER REVIEW
Result statement: {rs}
Verdict: {verdict}

SCORES
Confidence: {conf}/5.0
  Directness:   {vc.get('direct_score', 0)}/2.0  (level {vc.get('direct_level', 0)}/5)
  Verification: {vc.get('verify_score', 0)}/2.0  (level {vc.get('verify_level', 0)}/5)
  Recency:      {vc.get('recency_score', 0)}/1.0  (level {vc.get('recency_level', 0)}/5)
Clarity: {clar}/5.0
  Definition:   {cc.get('definition_score', 0)}/1.25
  Measurement:  {cc.get('measurement_score', 0)}/1.25
  Integrity:    {cc.get('integrity_score', 0)}/1.0
  Scope:        {cc.get('scope_score', 0)}/0.75
  Governance:   {cc.get('governance_score', 0)}/0.75

EVIDENCE DETAILS
Type: {ev_type}
Date: {ev_date}
Internal review: {review}
Description (excerpt): {ev_desc}

EXISTING PRIORITY FIXES
{fixes_block.strip() or "None generated."}
""".strip()


# ---------------------------------------------------------------------------
# Verdict-aware instruction modifiers
# ---------------------------------------------------------------------------

def _verdict_modifier(member_id: str, ev: dict) -> str:
    """Return an additional instruction line that steers each council member
    based on which axis is weak. Avoids generic 'find weaknesses' framing when
    one axis is already strong."""
    conf = ev.get("confidence_score", 0)
    clar = ev.get("clarity_score", 0)
    threshold = 4.0  # matches SUBMISSION_THRESHOLD in evaluator.py

    # Both strong — refinement mode
    if conf >= threshold and clar >= threshold:
        return (
            "NOTE: This result scores well on both axes. "
            "Frame your assessment as refinement, not remediation. "
            "Identify what would push this from 'acceptable' to 'excellent'."
        )

    # Confidence weak only (UNDEREVIDENCED / well-defined but weak evidence)
    if clar >= threshold and conf < threshold:
        if member_id == "strategist":
            return (
                "NOTE: Clarity is already above threshold (the result statement is well-constructed). "
                "Do NOT look for framing weaknesses — there are none significant. "
                "Instead, comment on how the strong Clarity framing can be maintained while "
                "the Confidence gap is addressed. Your proposed statement should preserve the "
                "current framing and only add contribution language if genuinely missing."
            )
        return (
            "NOTE: Clarity is already above threshold — focus ONLY on the Confidence axis gaps. "
            "Do not comment on result statement weaknesses."
        )

    # Clarity weak only (MISLEADING / sharpen the definition)
    if conf >= threshold and clar < threshold:
        if member_id == "evidence_auditor":
            return (
                "NOTE: Confidence is already above threshold — the evidence is strong. "
                "Briefly acknowledge this, then focus your assessment on what Clarity gaps remain."
            )
        return (
            "NOTE: Confidence is already above threshold — focus ONLY on the Clarity axis gaps "
            "(Definition, Measurement, Integrity, Scope, Governance)."
        )

    # Both weak — default, no modifier needed
    return ""


# ---------------------------------------------------------------------------
# Per-member system prompt builder
# ---------------------------------------------------------------------------

def build_member_system_prompt(member_id: str, submission: dict, ev: dict) -> str:
    member   = _MEMBER_BY_ID[member_id]
    context  = _build_shared_context(submission, ev)
    modifier = _verdict_modifier(member_id, ev)
    extra    = f"\n{modifier}" if modifier else ""
    return (
        f"{member['instruction']}{extra}\n\n"
        f"RULES:\n"
        f"1. Base your assessment ONLY on the data provided below.\n"
        f"2. Never suggest exaggerating, falsifying, or inflating reported numbers.\n"
        f"3. Keep your response under 120 words.\n\n"
        f"{context}"
    )


# ---------------------------------------------------------------------------
# Synthesis call — upgraded statements + reporting team brief
# ---------------------------------------------------------------------------

def _build_synthesis_prompt(submission: dict, ev: dict, verdicts: dict[str, str]) -> str:
    context   = _build_shared_context(submission, ev)
    conf      = ev.get("confidence_score", 0)
    clar      = ev.get("clarity_score", 0)
    threshold = 4.0

    # Axis-specific instruction for the synthesis
    if clar >= threshold and conf < threshold:
        rs_instruction = (
            "Clarity is already above threshold — the result statement is well-constructed. "
            "For 'upgraded_result_statement': preserve the existing framing; only add a brief "
            "contribution clause if it is genuinely absent. Do not rewrite what is already clear."
        )
    elif conf >= threshold and clar < threshold:
        rs_instruction = (
            "Confidence is already above threshold — the evidence chain is strong. "
            "For 'upgraded_result_statement': focus on sharpening the definition elements "
            "(who/what/where/when/how measured) that are still missing."
        )
    elif conf >= threshold and clar >= threshold:
        rs_instruction = (
            "Both axes are above threshold. "
            "For 'upgraded_result_statement': make only minor refinements — do not overhaul "
            "a statement that is already submission-ready."
        )
    else:
        rs_instruction = (
            "Both axes need work. "
            "For 'upgraded_result_statement': address the most impactful framing gap first "
            "(contribution, specificity, or scope — whichever the council flagged)."
        )

    verdicts_block = "\n".join(
        f"{_MEMBER_BY_ID[mid]['name']} ({_MEMBER_BY_ID[mid]['archetype']}):\n{txt}"
        for mid, txt in verdicts.items()
    )
    return f"""You are the ImpactProof Council Synthesis Engine.
You have received assessments from 5 council members reviewing a scored impact result.
Your job: produce 3 outputs as valid JSON (no markdown, no code fences):

1. "upgraded_result_statement": One improved result statement (1-2 sentences).
   Preserve the factual claims exactly — do not invent numbers or achievements.
   Improve only: clarity, specificity, contribution framing. Stay honest.
   {rs_instruction}

2. "upgraded_evidence_statement": One improved evidence statement (2-3 sentences).
   Must address the top 1-2 gaps identified by the council. Stay factual — use
   placeholder tokens like [source] or [MEL officer name] where specifics are unknown.

3. "reporting_team_brief": A plain-English brief for a non-MEL programme manager.
   Structure as an object with these exact keys:
   - "what_score_means": 2 sentences — what the current score means for submission (no jargon)
   - "what_to_change": list of 2-3 short strings — each a plain-English action item
   - "how_long": 1 sentence — realistic time estimate for all fixes combined
   - "projected_status": 1 sentence — what the result status becomes after fixes

RULES:
- Output ONLY valid JSON. No prose before or after.
- Never invent numbers, names, or data not present in the context.
- Use plain English in reporting_team_brief — no MEL jargon.

{context}

COUNCIL MEMBER ASSESSMENTS:
{verdicts_block}"""


# ---------------------------------------------------------------------------
# Deterministic projected score calculator
# ---------------------------------------------------------------------------

def _calculate_projected_scores(ev: dict) -> tuple[float, float]:
    """
    Sum fix.score_impact_value for each axis and add to current scores.
    Caps at 5.0. Deterministic — no AI involvement.
    """
    conf  = ev.get("confidence_score", 0.0)
    clar  = ev.get("clarity_score", 0.0)
    fixes = ev.get("fixes", [])

    conf_gain = sum(
        f.get("score_impact_value", 0.0)
        for f in fixes
        if "confidence" in f.get("score_impact", "").lower()
    )
    clar_gain = sum(
        f.get("score_impact_value", 0.0)
        for f in fixes
        if "clarity" in f.get("score_impact", "").lower()
    )

    proj_conf = round(min(5.0, conf + conf_gain), 2)
    proj_clar = round(min(5.0, clar + clar_gain), 2)
    return proj_conf, proj_clar


# ---------------------------------------------------------------------------
# Fabrication guard — deterministic, no AI involvement
#
# The synthesis prompt instructs the model not to invent numbers, but that is
# a soft instruction only. This is the machine-checked backstop: every
# numeral/year/percentage in an AI-drafted statement must appear somewhere in
# the user's own submission, or the statement is withheld rather than shown.
# ---------------------------------------------------------------------------

_NUMERIC_TOKEN_RE = re.compile(r"\d[\d,]*\.?\d*%?")


def _extract_numeric_tokens(text: str) -> set[str]:
    """Extract normalized numeric tokens (ints, decimals, percentages) from text.

    Strips thousands-separator commas, a trailing '%', and a trailing '.' —
    the last of which handles a sentence-ending period glued onto a match
    (e.g. "...in 2025." must normalize to match a bare "2025" elsewhere)
    without touching a genuine decimal like "3.5".
    """
    if not text:
        return set()
    tokens = set()
    for raw in _NUMERIC_TOKEN_RE.findall(text):
        norm = raw.replace(",", "").rstrip("%").rstrip(".")
        if norm:
            tokens.add(norm)
    return tokens


def _submission_fact_text(submission: dict) -> str:
    """Concatenate the raw, untruncated user-supplied fields that count as
    'the source input' for fabrication checking. Deliberately does NOT reuse
    _build_shared_context's output, which is truncated and also contains
    score-display numbers (e.g. "Confidence: 4.2/5.0") that are not project
    facts — checking against it risks both false negatives (truncated-away
    real facts) and false positives (a hallucinated number matching a score
    readout instead of an actual fact).
    """
    parts = []
    for key in (
        "result_statement", "target_group", "timeframe", "geographic_scope",
        "additional_context", "logframe_indicator", "logframe_target",
        "logframe_achievement", "beneficiary_voice", "bv_method_detail",
        "internal_review", "external_review",
    ):
        val = submission.get(key)
        if val:
            parts.append(str(val))

    for item in submission.get("evidence", []) or []:
        for key in ("type", "description", "recency", "verified_by"):
            val = item.get(key)
            if val:
                parts.append(str(val))

    for val in (submission.get("provenance_checklist") or {}).values():
        if isinstance(val, str) and val:
            parts.append(val)

    return "\n".join(parts)


def check_fabrication(draft: str, submission: dict) -> tuple[bool, list[str]]:
    """Check that every numeral/year/percentage in `draft` appears somewhere
    in the submission's own fields. Returns (is_clean, offending_tokens)."""
    if not draft:
        return True, []
    draft_tokens  = _extract_numeric_tokens(draft)
    allowed_tokens = _extract_numeric_tokens(_submission_fact_text(submission))
    offending = sorted(draft_tokens - allowed_tokens)
    return (len(offending) == 0), offending


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def _call_haiku(system_prompt: str, user_msg: str, api_key: str, max_tokens: int = 200,
                model: str = "claude-haiku-4-5-20251001") -> str:
    """Single Claude API call. Returns response text or an error string."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp   = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text if resp.content else ""
    except Exception as exc:
        return f"[Council member unavailable: {type(exc).__name__}]"


def run_council_assessment(submission: dict, ev: dict, api_key: str) -> dict:
    """
    Run all 5 council members in parallel, then one synthesis call.

    Returns:
    {
        "verdicts": {
            member_id: {
                "name": str, "icon": str, "archetype": str, "color": str,
                "verdict_text": str
            }
        },
        "upgraded_result_statement": str,   # "" if withheld by the fabrication guard
        "upgraded_evidence_statement": str, # "" if withheld by the fabrication guard
        "reporting_team_brief": {
            "what_score_means": str,
            "what_to_change": [str, ...],
            "how_long": str,
            "projected_status": str,
        },
        "projected_conf": float,
        "projected_clar": float,
        "error": str | None,
        "withheld": {
            "upgraded_result_statement": bool,
            "upgraded_evidence_statement": bool,
        },
    }
    """
    verdicts: dict[str, str] = {}
    errors: list[str]        = []

    # --- Step 1: 5 parallel council member calls ---
    user_msg = "Please provide your assessment."

    def _run_member(member: dict) -> tuple[str, str]:
        sys_prompt = build_member_system_prompt(member["id"], submission, ev)
        text       = _call_haiku(sys_prompt, user_msg, api_key, max_tokens=220)
        return member["id"], text

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_run_member, m): m for m in COUNCIL_MEMBERS}
        for future in as_completed(futures):
            mid, text = future.result()
            verdicts[mid] = text
            if text.startswith("[Council member unavailable"):
                errors.append(mid)

    # Preserve display order
    ordered_verdicts = {
        m["id"]: {
            "name":        m["name"],
            "icon":        m["icon"],
            "archetype":   m["archetype"],
            "color":       m["color"],
            "verdict_text": verdicts.get(m["id"], "[No response]"),
        }
        for m in COUNCIL_MEMBERS
    }

    # --- Step 2: Synthesis call ---
    synthesis_prompt = _build_synthesis_prompt(submission, ev, verdicts)
    raw_synthesis    = _call_haiku(synthesis_prompt, "Produce the JSON output now.", api_key, max_tokens=700)

    upgraded_result    = ""
    upgraded_evidence  = ""
    reporting_brief: dict[str, Any] = {}

    # Strip any accidental markdown fences before parsing
    clean = re.sub(r"```(?:json)?|```", "", raw_synthesis).strip()
    try:
        parsed             = json.loads(clean)
        upgraded_result    = parsed.get("upgraded_result_statement", "")
        upgraded_evidence  = parsed.get("upgraded_evidence_statement", "")
        reporting_brief    = parsed.get("reporting_team_brief", {})
    except (json.JSONDecodeError, ValueError):
        # Graceful fallback — show raw text in the brief
        reporting_brief = {
            "what_score_means": raw_synthesis[:300] if raw_synthesis else "Synthesis unavailable.",
            "what_to_change":   [],
            "how_long":         "",
            "projected_status": "",
        }

    # --- Step 3: Deterministic projected scores ---
    proj_conf, proj_clar = _calculate_projected_scores(ev)

    # --- Step 4: Fabrication guard — withhold any drafted statement that
    # introduces a numeral/year/percentage not present in the user's own
    # submission. No-fabrication is a non-negotiable product rule; this is
    # the machine-checked backstop behind the synthesis prompt's instruction.
    result_clean, _ = check_fabrication(upgraded_result, submission)
    evidence_clean, _ = check_fabrication(upgraded_evidence, submission)
    if not result_clean:
        upgraded_result = ""
    if not evidence_clean:
        upgraded_evidence = ""

    return {
        "verdicts":                   ordered_verdicts,
        "upgraded_result_statement":  upgraded_result,
        "upgraded_evidence_statement": upgraded_evidence,
        "reporting_team_brief":       reporting_brief,
        "projected_conf":             proj_conf,
        "projected_clar":             proj_clar,
        "error":                      ", ".join(errors) if errors else None,
        "withheld": {
            "upgraded_result_statement":   not result_clean,
            "upgraded_evidence_statement": not evidence_clean,
        },
    }


# ---------------------------------------------------------------------------
# Council XXIII — Evidence Type Debate
# ---------------------------------------------------------------------------
# 5 council members each vote on the closest-fit evidence type from the
# product's fixed EVIDENCE_TYPES list, bringing domain knowledge of donor
# evidence hierarchies (USAID ADS 201, FCDO, Bond) and field practice.
# A synthesis call resolves the votes into one consensus recommendation.

_EVIDENCE_DEBATE_MEMBERS = [
    {
        "id":   "mel_methodologist",
        "name": "MEL Methodologist",
        "instruction": (
            "You are a MEL Methodologist applying evidence-quality standards "
            "(USAID ADS 201 validity typology, Bond Evidence Principles). "
            "Vote for the evidence type that best matches the METHODOLOGY described — "
            "not the subject matter."
        ),
    },
    {
        "id":   "donor_compliance",
        "name": "Donor Compliance Officer",
        "instruction": (
            "You are a Donor Compliance Officer who reviews evidence against donor DQA "
            "checklists daily. Vote for the evidence type a donor reviewer (USAID, FCDO, "
            "EU, or a fund like OCIF) would name for this evidence, and note which type "
            "donors generally trust most for this kind of claim."
        ),
    },
    {
        "id":   "field_practitioner",
        "name": "Field Practitioner",
        "instruction": (
            "You are a field MEL officer who actually collects this kind of evidence. "
            "Vote based on the OPERATIONAL REALITY described — how was this data "
            "physically gathered, stored, and by whom — not how it is phrased."
        ),
    },
    {
        "id":   "scoring_analyst",
        "name": "Scoring Analyst",
        "instruction": (
            "You are a Scoring Analyst who understands how each evidence type affects "
            "the Directness score. Vote for the type that is most ACCURATE without "
            "overstating the evidence — do not pick a 'stronger' type than the "
            "description actually supports."
        ),
    },
    {
        "id":   "devils_advocate",
        "name": "Devil's Advocate",
        "instruction": (
            "You are skeptical of the obvious answer. Before voting, ask: is there a "
            "closer-fitting type being overlooked? Would a donor reviewer push back on "
            "the leading classification? Vote for what you believe is the most "
            "DEFENSIBLE type, and flag if the description is too vague to classify "
            "confidently."
        ),
    },
]


def _build_evidence_debate_prompt(member: dict, description: str, result_statement: str,
                                   evidence_types: list[str]) -> str:
    types_list = "\n".join(f'- "{t}"' for t in evidence_types)
    return f"""{member['instruction']}

TASK: Vote for exactly ONE evidence type from this list that best matches the evidence
description below. Output ONLY valid JSON (no markdown, no prose):
{{"vote": "<exact type string from the list>", "reasoning": "<1-2 sentences>"}}

VALID TYPES (vote must be one of these, verbatim):
{types_list}

RESULT STATEMENT: {(result_statement or "")[:400]}

EVIDENCE DESCRIPTION: {(description or "")[:600]}"""


def _build_evidence_synthesis_prompt(description: str, result_statement: str,
                                      evidence_types: list[str],
                                      votes: dict[str, dict]) -> str:
    types_list = "\n".join(f'- "{t}"' for t in evidence_types)
    votes_block = "\n".join(
        f"{_EVIDENCE_DEBATE_MEMBERS_BY_ID[mid]['name']}: voted \"{v.get('vote','')}\" — {v.get('reasoning','')}"
        for mid, v in votes.items()
    )
    return f"""You are the ImpactProof Evidence Type Synthesis Engine.
5 council members voted on the best-fit evidence type for this evidence. Resolve their
votes into one consensus recommendation.

Output ONLY valid JSON (no markdown, no prose):
{{
  "recommended_type": "<exact type string from VALID TYPES, verbatim>",
  "confidence": "high" | "medium" | "low",
  "reasoning": "<1-2 sentences synthesizing why this is the best fit>",
  "donor_alignment": "<1 sentence on which donor framework(s) prioritise this type>"
}}

RULES:
- If 3+ members agree, confidence is "high".
- If votes split roughly evenly, confidence is "medium" or "low" and reasoning should
  acknowledge the disagreement.
- The Scoring Analyst's vote breaks ties — weight it slightly higher when votes are split.
- recommended_type MUST be an exact string from VALID TYPES below.

VALID TYPES:
{types_list}

RESULT STATEMENT: {(result_statement or "")[:400]}
EVIDENCE DESCRIPTION: {(description or "")[:600]}

COUNCIL VOTES:
{votes_block}"""


_EVIDENCE_DEBATE_MEMBERS_BY_ID = {m["id"]: m for m in _EVIDENCE_DEBATE_MEMBERS}


def debate_evidence_type(description: str, result_statement: str,
                          evidence_types: list[str], api_key: str) -> dict:
    """
    Run a 5-member council debate to classify evidence into the closest-fit type.

    Args:
        description: the user's evidence description text
        result_statement: the result statement for context
        evidence_types: the valid EVIDENCE_TYPES list (excluding placeholder)
        api_key: Anthropic API key

    Returns:
    {
        "recommended_type": str,   # exact string from evidence_types
        "confidence": "high"|"medium"|"low",
        "reasoning": str,
        "donor_alignment": str,
        "member_votes": {member_id: {"vote": str, "reasoning": str}},
    }
    """
    if not description or not description.strip():
        return {
            "recommended_type": "",
            "confidence": "low",
            "reasoning": "No evidence description provided.",
            "donor_alignment": "",
            "member_votes": {},
        }

    def _run_vote(member: dict) -> tuple[str, dict]:
        prompt = _build_evidence_debate_prompt(member, description, result_statement, evidence_types)
        raw    = _call_haiku(prompt, "Vote now.", api_key, max_tokens=150)
        clean  = re.sub(r"```(?:json)?|```", "", raw).strip()
        try:
            parsed = json.loads(clean)
            vote   = parsed.get("vote", "")
            # Validate vote is one of the allowed types; else treat as unmatched
            if vote not in evidence_types:
                vote = ""
            return member["id"], {"vote": vote, "reasoning": parsed.get("reasoning", "")}
        except (json.JSONDecodeError, ValueError):
            return member["id"], {"vote": "", "reasoning": "[Vote unavailable]"}

    votes: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_run_vote, m): m for m in _EVIDENCE_DEBATE_MEMBERS}
        for future in as_completed(futures):
            mid, vote_data = future.result()
            votes[mid] = vote_data

    # Synthesis call
    synthesis_prompt = _build_evidence_synthesis_prompt(description, result_statement, evidence_types, votes)
    raw_synthesis     = _call_haiku(synthesis_prompt, "Produce the JSON output now.", api_key, max_tokens=300)
    clean_synthesis   = re.sub(r"```(?:json)?|```", "", raw_synthesis).strip()

    try:
        parsed = json.loads(clean_synthesis)
        recommended = parsed.get("recommended_type", "")
        if recommended not in evidence_types:
            recommended = ""
        result = {
            "recommended_type": recommended,
            "confidence":       parsed.get("confidence", "low"),
            "reasoning":        parsed.get("reasoning", ""),
            "donor_alignment":  parsed.get("donor_alignment", ""),
            "member_votes":     votes,
        }
    except (json.JSONDecodeError, ValueError):
        result = {"recommended_type": "", "confidence": "low", "reasoning": "", "donor_alignment": "", "member_votes": votes}

    # Fallback: if synthesis failed to produce a valid type, use plurality vote
    if not result["recommended_type"]:
        vote_counts: dict[str, int] = {}
        for v in votes.values():
            vt = v.get("vote", "")
            if vt:
                vote_counts[vt] = vote_counts.get(vt, 0) + 1
        if vote_counts:
            result["recommended_type"] = max(vote_counts, key=vote_counts.get)
            result["confidence"] = "medium" if max(vote_counts.values()) >= 3 else "low"
            if not result["reasoning"]:
                result["reasoning"] = "Selected by plurality vote among council members."

    return result


# ---------------------------------------------------------------------------
# Council XXIV — Competitive Position Debate (council XXIV)
# ---------------------------------------------------------------------------
# 5 council members debate a product/competitive positioning question.
# Designed as an admin/product tool — not user-facing. Enables future
# councils to be run programmatically for any strategic product question.

_COMPETITIVE_DEBATE_MEMBERS = [
    {
        "id":   "contrarian",
        "name": "Contrarian",
        "archetype": "MEL Consultant × Contrarian",
        "instruction": (
            "You are the Contrarian — a senior MEL consultant hired to stress-test "
            "the product's competitive position. Challenge every assumption. Surface "
            "what the competition can replicate. Name the specific conditions under which "
            "users would abandon the product for a free alternative. Be direct."
        ),
    },
    {
        "id":   "expansionist",
        "name": "Expansionist",
        "archetype": "Programme Director × Expansionist",
        "instruction": (
            "You are the Expansionist — a programme director who thinks about scale, "
            "portfolio management, and institutional adoption. Where does this product "
            "create disproportionate value at scale? What use cases does it unlock that "
            "individual tools cannot? What would make organisations mandate it?"
        ),
    },
    {
        "id":   "executor",
        "name": "Executor",
        "archetype": "Tech Architect × Executor",
        "instruction": (
            "You are the Executor — a technical architect focused on implementation reality. "
            "What specific technical capabilities make this product's output non-reproducible "
            "by a generic AI tool with a prompt? Focus on: reproducibility, artifact quality, "
            "integration points, and audit trail. Name concrete features, not abstractions."
        ),
    },
    {
        "id":   "first_principle",
        "name": "First Principle",
        "archetype": "MEL Lead × First Principle",
        "instruction": (
            "You are First Principle — a MEL lead applying first-principles thinking. "
            "Strip away the product features. What is the fundamental job this product "
            "does that users cannot do themselves? What is the irreducible core of its "
            "value? What would have to be true for users to choose this over free alternatives?"
        ),
    },
    {
        "id":   "outsider",
        "name": "Outsider",
        "archetype": "Donor Rep × Outsider",
        "instruction": (
            "You are the Outsider — a donor representative who reviews implementing partner "
            "submissions. You have no loyalty to any tool. What would make you trust a "
            "submission MORE because the team used this product? What would you expect "
            "the product's output to look like for it to be cited in a submission? "
            "What would make you recommend or require it of partners?"
        ),
    },
]

_COMPETITIVE_DEBATE_MEMBERS_BY_ID = {m["id"]: m for m in _COMPETITIVE_DEBATE_MEMBERS}


def debate_competitive_position(question: str, product_context: str, api_key: str,
                                chairman_model: str = "claude-haiku-4-5-20251001") -> dict:
    """
    Run the 5 council members (Contrarian, Expansionist, Executor, First Principle,
    Outsider) to debate a product/competitive positioning question.

    Args:
        question: The strategic question to debate (e.g. "Why would X choose us over ChatGPT?")
        product_context: Brief description of the product's current state and capabilities
        api_key: Anthropic API key

    Returns:
    {
        "member_verdicts": {member_id: {"name", "archetype", "verdict"}},
        "chairmans_verdict": str,      # synthesis of key insights
        "actionable_changes": [str],   # 3-5 concrete product change recommendations
        "drca_gaps": {                 # which DRCA pillars are weakly surfaced
            "deterministic": bool, "reproducible": bool,
            "comparable": bool, "auditable": bool
        },
    }
    """
    def _run_member(member: dict) -> tuple[str, str]:
        system = (
            f"{member['instruction']}\n\n"
            f"PRODUCT CONTEXT:\n{product_context}\n\n"
            f"RULES: Keep your response under 150 words. Be specific. "
            f"Name concrete features, not abstractions."
        )
        text = _call_haiku(system, question, api_key, max_tokens=250)
        return member["id"], text

    verdicts: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_run_member, m): m for m in _COMPETITIVE_DEBATE_MEMBERS}
        for future in as_completed(futures):
            mid, text = future.result()
            verdicts[mid] = text

    ordered_verdicts = {
        m["id"]: {
            "name":      m["name"],
            "archetype": m["archetype"],
            "verdict":   verdicts.get(m["id"], "[No response]"),
        }
        for m in _COMPETITIVE_DEBATE_MEMBERS
    }

    # Chairman's synthesis call
    verdicts_block = "\n\n".join(
        f"{_COMPETITIVE_DEBATE_MEMBERS_BY_ID[mid]['name']} ({_COMPETITIVE_DEBATE_MEMBERS_BY_ID[mid]['archetype']}):\n{v}"
        for mid, v in verdicts.items()
    )
    chair_prompt = f"""You are the Chairman of the ImpactProof product council.
5 council members have debated: "{question}"

Synthesise their verdicts into:
1. A "Chairman's Verdict" — 2-3 sentences identifying the most defensible competitive position
2. A list of 3-5 "Actionable Changes" — specific product/copy changes to implement
3. A "DRCA Assessment" — which of Deterministic/Reproducible/Comparable/Auditable is most weakly surfaced

Output valid JSON:
{{
  "chairmans_verdict": "<2-3 sentences>",
  "actionable_changes": ["<change 1>", "<change 2>", "<change 3>"],
  "drca_gaps": {{"deterministic": true|false, "reproducible": true|false, "comparable": true|false, "auditable": true|false}}
}}
(true = gap exists/pillar is weakly surfaced)

COUNCIL VERDICTS:
{verdicts_block}"""

    raw = _call_haiku(chair_prompt, "Produce the chairman's synthesis now.", api_key, max_tokens=500,
                      model=chairman_model)
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        parsed = json.loads(clean)
        return {
            "member_verdicts":   ordered_verdicts,
            "chairmans_verdict": parsed.get("chairmans_verdict", ""),
            "actionable_changes": parsed.get("actionable_changes", []),
            "drca_gaps":         parsed.get("drca_gaps", {}),
        }
    except (json.JSONDecodeError, ValueError):
        return {
            "member_verdicts":   ordered_verdicts,
            "chairmans_verdict": raw[:400],
            "actionable_changes": [],
            "drca_gaps":         {},
        }
