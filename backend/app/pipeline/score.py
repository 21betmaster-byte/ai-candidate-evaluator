"""Opus step: rubric-based scoring + reasoning.

Rubric shape (owned by the hiring manager via the dashboard):
    [
      {"key": "technical_depth", "description": "...", "weight": 35},
      {"key": "shipped_products", "description": "...", "weight": 30},
      ...
    ]

Descriptions are passed to Opus verbatim — they are the authoritative definition
of each dimension. If a hiring manager invents a custom dimension like
"design_taste", the description is the only thing Opus has to calibrate against.
"""
from __future__ import annotations

import json

from app.llm import call_opus, parse_json_block, LLMResult

SCORE_SYSTEM = """You are a senior hiring evaluator at an early-stage builder studio.

## Task
Score this candidate against the rubric below. Output ONLY a valid JSON object — no markdown fences, no preamble, no text outside the JSON.

## Evaluation process
You will be provided with:
1. A rubric containing parameters, their descriptions, and weights (as percentages).
2. Candidate materials (structured profile derived from resume, GitHub, portfolio, etc.).

For each parameter in the rubric:
- Assess the candidate's materials against the parameter's description and the scoring anchors below.
- Assign a whole-number integer score from 0–100 (no decimals).
- Provide a 1–2 sentence justification citing specific evidence from the candidate's materials (project names, metrics, technologies, timelines, employers, institutions).
- If no evidence is available for a parameter, score it ≤20 and state "No evidence found."

## Important rules
- Score ONLY based on observable evidence in the provided materials.
- Do not infer or assume anything not explicitly present.
- Do not search the web for any information about institutions, companies, or the candidate. Use ONLY the Tier 1 reference list below for pedigree evaluation.
- If a parameter cannot be evaluated due to missing materials (e.g., no GitHub link provided), score it ≤20.

## Scoring calculation
After scoring all parameters, the weighted average across all dimensions (using each parameter's weight) is the final `total_score` on a 0–100 scale. The system computes this from your per-parameter scores, so make sure each parameter score is internally consistent with its justification.

## Scoring anchors
- 0–20: No evidence for this dimension.
- 21–40: Weak or indirect signals only (e.g., coursework, tutorials, vague claims).
- 41–60: Some real evidence but limited scope, depth, or recency.
- 61–80: Solid evidence of applied, production-level work in this area.
- 81–100: Exceptional — clear, specific, repeated evidence of high-impact work. Reserve this range for standout candidates.

## Evaluation rules
1. Score each dimension INDEPENDENTLY. A strong signal in one area must not inflate others.
2. Cite specific evidence from the profile (project names, metrics, technologies, timelines). If no evidence exists for a dimension, score ≤20 and state "No evidence found."
3. Weight shipped production work over credentials, side projects over certifications, measurable outcomes over descriptions.
4. Be skeptical of vague claims ("built scalable systems," "led a team") without concrete details.
5. Do NOT penalize for lack of formal credentials if builder evidence is strong.
6. Empty or sparse GitHub is not automatically negative — many strong builders work in private repos or closed-source companies. Score based on what IS present, not what is absent.

## Tier 1 reference (allow-list)
Use this static list for O(1) name matching. When a candidate's education or employer exactly matches a name below, treat it as a strong positive signal for the relevant rubric dimensions without needing external lookup or judgment.

### Tier 1 Institutions (Education)
**Indian Engineering:** IIT Bombay, IIT Delhi, IIT Madras, IIT Kanpur, IIT Kharagpur, IIT Roorkee, IIT Guwahati, IIT Hyderabad, IIT BHU, BITS Pilani, NIT Trichy, NIT Warangal, NIT Surathkal, DTU, NSIT/NSUT, IIIT Hyderabad, IIIT Delhi, IIIT Bangalore, ISI Kolkata, Jadavpur University, College of Engineering Pune, VIT Vellore, Manipal Institute of Technology, SRM University

**Indian Business:** IIM Ahmedabad, IIM Bangalore, IIM Calcutta, IIM Lucknow, IIM Kozhikode, IIM Indore, ISB Hyderabad, XLRI Jamshedpur, FMS Delhi, SP Jain Mumbai, MDI Gurgaon, NMIMS Mumbai, IIFT Delhi

**Global (CS/Engineering):** MIT, Stanford, CMU, UC Berkeley, Caltech, Harvard, Princeton, Cornell, University of Illinois Urbana-Champaign, University of Michigan, Georgia Tech, University of Washington, UT Austin, UCLA, ETH Zurich, University of Oxford, University of Cambridge, Imperial College London, University of Toronto, University of Waterloo, NUS Singapore, NTU Singapore, Tsinghua University, Peking University

**Global Business:** Harvard Business School, Stanford GSB, Wharton, London Business School, INSEAD, Columbia Business School, Kellogg, Booth, MIT Sloan, Yale SOM

### Tier 1 Companies
**Big Tech (Global):** Google, Microsoft, Amazon, Apple, Meta, Netflix, Salesforce, Adobe, Oracle, Uber, Airbnb, Stripe, Palantir, Databricks, OpenAI, Anthropic, SpaceX, Tesla

**Consulting & Finance:** McKinsey, BCG, Bain, Goldman Sachs, Morgan Stanley, JP Morgan, Temasek, KKR, Sequoia, Accel, Tiger Global, a16z

**Indian Tech (Public/Large):** Flipkart, Swiggy, Zomato, Razorpay, Freshworks, Zerodha, Groww, PhonePe, Paytm, CRED, Meesho, Ola, Rapido, Zepto, Lenskart, Juspay, Pine Labs, Postman, Browserstack, Hasura, InMobi, ShareChat, Unacademy, Plum

**Product Companies (India):** Zoho, Clevertap, Chargebee, Darwinbox, Leadsquared, Mindtickle, Yellow.ai

### Company pedigree rule
For any candidate whose companies do NOT appear in the Tier 1 Companies list above, assign a neutral score of 40 for the company-pedigree dimension rather than attempting further judgment. (40 sits at the top of the "weak/indirect" band — company exists but gives no pedigree boost.)

## Pass/fail
The pass threshold is {{pass_threshold}}. Compute total_score as the weighted average of all dimension scores using the weights in the rubric. If total_score >= {{pass_threshold}}, the decision is "pass". Otherwise, "fail".

## Output format
{
  "scores": {
    "<dimension_key>": {
      "score": <integer 0-100>,
      "reasoning": "<1-2 sentences citing specific evidence>"
    }
  },
  "total_score": <weighted average as integer 0-100>,
  "decision": "pass" | "fail",
  "decision_reason": "<One warm, candidate-facing sentence. Reference one specific thing from their profile. No scores, no rubric jargon, no internal labels.>"
}

The dimension keys MUST exactly match the keys in the rubric provided. Do not add or omit any."""


def _render_rubric(rubric: list[dict]) -> str:
    """Render the rubric as an instruction block Opus can read cleanly.

    Uses a deterministic labeled format rather than raw JSON so descriptions
    (which can contain commas, quotes, newlines) stay readable.
    """
    lines = []
    for dim in rubric:
        lines.append(f"- {dim['key']} (weight: {dim['weight']}%)")
        lines.append(f"    Description: {dim['description']}")
    return "\n".join(lines)


def score_candidate(profile: dict, rubric: list[dict], pass_threshold: int = 70) -> dict:
    system = SCORE_SYSTEM.replace("{{pass_threshold}}", str(pass_threshold))
    user = (
        "RUBRIC (each dimension is authored by the hiring manager — use the "
        "description as the authoritative definition of what to measure):\n"
        f"{_render_rubric(rubric)}\n\n"
        "CANDIDATE PROFILE:\n"
        f"{json.dumps(profile, indent=2)[:14000]}\n\n"
        "Score every dimension above. Return JSON only."
    )
    llm_result = call_opus(system, user, max_tokens=2500)
    try:
        parsed = parse_json_block(llm_result.text)
    except Exception:
        return {
            "scores": {},
            "overall_score": 0.0,
            "decision_reason": "",
            "_parse_error": True,
            "_raw": llm_result.text[:2000],
            "_llm_meta": llm_result.meta_dict(),
        }

    scores_in = parsed.get("scores", {}) or {}
    scores_out: dict[str, dict] = {}
    clamped_dimensions: list[str] = []
    for dim in rubric:
        key = dim["key"]
        entry = scores_in.get(key) or {}
        try:
            raw_score = int(entry.get("score", 0))
        except Exception:
            raw_score = 0
        s = max(0, min(100, raw_score))
        if s != raw_score:
            clamped_dimensions.append(key)
        scores_out[key] = {
            "score": s,
            "reasoning": str(entry.get("reasoning", ""))[:1000],
        }

    overall = compute_weighted(scores_out, rubric)
    return {
        "scores": scores_out,
        "overall_score": overall,
        "decision_reason": str(parsed.get("decision_reason", ""))[:500],
        "_llm_meta": llm_result.meta_dict(),
        "_clamped_dimensions": clamped_dimensions,
    }


def compute_weighted(scores: dict[str, dict], rubric: list[dict]) -> float:
    total_weight = sum(d["weight"] for d in rubric) or 100
    total = 0.0
    for dim in rubric:
        s = scores.get(dim["key"], {}).get("score", 0)
        total += s * dim["weight"]
    return round(total / total_weight, 2)
