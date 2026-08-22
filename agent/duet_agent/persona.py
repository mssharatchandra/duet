"""ASBL Broadway outbound-concierge policy, facts, and qualification logic.

The realtime model may choose natural wording, but not truth, consent, or sales
pressure. Those live here as versioned, testable policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .actions import ACTION_NAMES

AGENT_NAME = "Aira"
PROJECT_NAME = "ASBL Broadway"
FACTS_VERIFIED_ON = "2026-08-23"

# Claims supported by ASBL's public pages or the supplied CEO keynote.
PRODUCT_FACTS = f"""\
Project: ASBL Broadway, a premium residential project in Hyderabad's Financial District.
Official positioning: privacy, space and luxury.
Configuration: three towers, G+50 floors, four basements, and 885 apartments.
Homes: 3 and 3.5 BHK apartments; published super built-up areas range from 2,035 to 2,650 sq ft.
Site: 5.03 acres with 75% open space and more than 107,000 sq ft of indoor amenities.
Published possession date: December 2029.
Current public starting price: around INR 3 crore, verified {FACTS_VERIFIED_ON}; price, inventory,
floor premiums, payment plans and offers change and must be confirmed by an authorised ASBL advisor.
Location: Financial District, beside ASBL Loft, with access toward Gachibowli and the ORR corridor.
Privacy design: private foyers for many homes and tower planning intended to avoid opposite main doors.
Design: curtain-wall elements bring more natural light; the keynote specifies 3,300 mm
slab-to-slab height and approximately 3,050 mm clear height before floor or ceiling finishes.
Lifestyle: clubhouse and indoor amenities include fitness, social, children's and practical-luxury
spaces; the keynote describes co-working, creche-adjacent convenience, clinic or physiotherapy
provision, walking and recreation areas, and metered utilities.
Sustainability: the keynote describes sewage treatment with treated water reused for landscaping
and flushing.
Not guaranteed by this agent: unit availability, final price, discounts, legal or RERA interpretation,
loan eligibility, tax treatment, rental yield, capital appreciation, commute time or investment return.
"""

FACT_SOURCES = {
    "official_project": "https://asbl.in/broadway/",
    "official_landing": "https://asbl.in/broadway/landing/apartments-for-sale-in-hyderabad/",
    "ceo_keynote": "ASBL Keynote Ajitesh Korupolu decodes Hyderabad real estate at the Broadway ROTC",
}

# Public, inspectable retrieval registry.  The model returns these IDs and the
# UI resolves them to claims and sources; this is intentionally evidence, not
# hidden chain-of-thought.
FACT_REGISTRY = {
    "homes": {
        "claim": "3 and 3.5 BHK homes; published sizes are 2,035–2,650 sq ft.",
        "source_label": "ASBL Broadway official landing page",
        "source_url": FACT_SOURCES["official_landing"],
        "freshness": "recheck before publishing",
    },
    "scale": {
        "claim": "5.03 acres, 75% open space, three G+50 towers and 885 homes.",
        "source_label": "ASBL Broadway official landing page",
        "source_url": FACT_SOURCES["official_landing"],
        "freshness": "stable project specification",
    },
    "amenities": {
        "claim": "More than 107,000 sq ft of indoor amenities, including practical work-life spaces.",
        "source_label": "ASBL Broadway official project page",
        "source_url": FACT_SOURCES["official_project"],
        "freshness": "stable project specification",
    },
    "possession": {
        "claim": "The published possession date is December 2029.",
        "source_label": "ASBL Broadway official project page",
        "source_url": FACT_SOURCES["official_project"],
        "freshness": "recheck before each demo",
    },
    "price": {
        "claim": f"The current public starting price is around INR 3 crore (checked {FACTS_VERIFIED_ON}).",
        "source_label": "ASBL Broadway official landing page",
        "source_url": FACT_SOURCES["official_landing"],
        "freshness": "volatile — advisor must confirm",
    },
    "location": {
        "claim": "Broadway is in Hyderabad's Financial District, beside ASBL Loft and near the ORR corridor.",
        "source_label": "ASBL Broadway official project page",
        "source_url": FACT_SOURCES["official_project"],
        "freshness": "stable; exact travel times not guaranteed",
    },
    "privacy": {
        "claim": "Private foyers and planning that avoids opposite main doors are intended to improve privacy.",
        "source_label": "ASBL CEO Broadway keynote supplied for this demo",
        "source_url": FACT_SOURCES["official_project"],
        "freshness": "verify against the selected unit plan",
    },
    "light_and_height": {
        "claim": "Curtain-wall elements improve light; the keynote states 3,300 mm slab-to-slab height.",
        "source_label": "ASBL CEO Broadway keynote supplied for this demo",
        "source_url": FACT_SOURCES["official_project"],
        "freshness": "verify against specifications and selected unit",
    },
}

DISCOVERY_QUESTIONS = [
    "Would this be primarily a home for your family or an investment?",
    "Which matters most: workplace access, privacy, space, amenities, or long-term value?",
    "Are you considering a 3 BHK or would you like to compare the larger layouts?",
    "What broad budget range would feel comfortable, including registration and interiors?",
    "When would you ideally want to make a decision or move?",
    "Who else should be part of a site visit or final decision?",
]

OBJECTION_PLAYBOOK = {
    "price": "Acknowledge budget; state only the current public starting point and offer an authorised price comparison.",
    "timing": "Acknowledge the possession horizon and ask whether December 2029 fits without creating urgency.",
    "location": "Ask which commute matters; never invent drive times or infrastructure completion dates.",
    "trust": "Offer official material, live progress and an authorised advisor; never dismiss delivery or compliance concerns.",
    "comparison": "Ask which project and criteria matter, then compare only verified like-for-like facts.",
    "family_approval": "Respect shared decisions and offer a joint site visit; never pressure someone to decide alone.",
    "investment_returns": "Never promise appreciation, rent or yield; separate project facts from investment assumptions.",
}

INTENTS = (
    "permission",
    "greeting",
    "discovery_answer",
    "question",
    "objection",
    "site_visit",
    "callback",
    "opt_out",
    "closing",
    "smalltalk",
    "other",
)
SIGNAL_STRENGTHS = ("strong", "weak", "none")
QUALIFICATION_DIMENSIONS = ("budget_fit", "decision_role", "use_case", "timeline")
BANT = QUALIFICATION_DIMENSIONS  # compatibility for the existing transport
CONVERSATION_STAGES = ("permission", "discovery", "education", "objection", "next_step", "closing")
RESPONSE_STRATEGIES = (
    "acknowledge_and_answer",
    "clarify_need",
    "explain_value",
    "handle_objection",
    "factual_boundary",
    "offer_next_step",
    "wait",
)
NEXT_ACTIONS = ("continue", "ask", "wait", "handoff", "tool", "stop")

OPENING = (
    f"Hi, I'm {AGENT_NAME}, ASBL's AI assistant, calling about your Broadway enquiry. "
    "Is now a good time for a brief conversation?"
)
OPT_OUT_ACK = "Of course. I'll stop here, and this demo will not continue or place another call. Take care."
NOT_NOW_ACK = "No problem. I'll stop here; an ASBL advisor can follow up only at a time you prefer."
INTERRUPTION_CLARIFICATION = (
    "I heard that you changed your mind. Should I stop the conversation, "
    "or did you want to change one preference?"
)
SENSITIVE_PROFILE_ACK = (
    "I won't use religion or other sensitive traits to judge whether you may buy. "
    "I can only use needs you explicitly choose to share."
)

_OPT_OUT = re.compile(
    r"\b(stop calling|stop talking|stop now|do not call|don't call|remove me|opt[ -]?out|not interested|"
    r"leave me alone|wrong number|end (?:the )?(?:call|conversation)|stop (?:the )?conversation|hang up|no more|"
    r"(?:do not|don't|dont|no longer) want to (?:listen|hear|talk|continue))\b",
    re.IGNORECASE,
)
_PERMISSION_YES = re.compile(
    r"\b(yes|yeah|yep|sure|okay|ok|go ahead|fine|this is a good time|i can talk)\b",
    re.IGNORECASE,
)
_PERMISSION_NO = re.compile(
    r"\b(no|not now|bad time|busy|call later|another time|can't talk|cannot talk)\b",
    re.IGNORECASE,
)


def is_opt_out(text: str) -> bool:
    return bool(_OPT_OUT.search(text))


_AMBIGUOUS_CHANGE = re.compile(
    r"\b(?:i\s+)?(?:just\s+)?change(?:d)? my mind\b|\b(?:actually|no),?\s*(?:yeah|yes|maybe|never mind)\b",
    re.IGNORECASE,
)
_CLARIFICATION_CONTINUE = re.compile(
    r"\b(?:continue|keep going|go on|carry on|change (?:a |my )?(?:preference|requirement|answer)|"
    r"different (?:preference|requirement)|i still want to (?:hear|talk|continue))\b",
    re.IGNORECASE,
)


def is_ambiguous_change(text: str) -> bool:
    """Changes of mind need a referent before sales reasoning may resume."""
    return bool(_AMBIGUOUS_CHANGE.search(text)) and not is_opt_out(text)


def clarification_response(text: str) -> str | None:
    """Resolve a pending interruption clarification without guessing intent."""
    if is_opt_out(text):
        return "stop"
    if _CLARIFICATION_CONTINUE.search(text):
        return "continue"
    return None


def permission_response(text: str) -> str | None:
    """Return granted, denied, or None when the answer is genuinely unclear."""
    if is_opt_out(text) or _PERMISSION_NO.search(text):
        return "denied"
    if _PERMISSION_YES.search(text):
        return "granted"
    return None


_BACKCHANNELS = {
    "hm", "hmm", "mm", "mhm", "uh huh", "aha", "okay", "ok", "right", "got it", "i see",
}
_EXPLICIT_INTERRUPTS = re.compile(r"\b(wait|stop|hold on|actually|no|sorry|one second)\b", re.IGNORECASE)
_UNAVAILABLE_ACTION = re.compile(
    r"\b(i(?:'ll| will) (?:send|share|arrange|schedule|book|have|update|mark)|i have (?:sent|shared|arranged|scheduled|booked|updated|marked)|(?:an? )?(?:advisor|team) will (?:call|contact|send|share|reach out))\b",
    re.IGNORECASE,
)
_SENSITIVE_PROFILE = re.compile(
    r"\b(religion|religious|muslim|hindu|christian|caste|ethnicity|health|disability)\b.*\b"
    r"(likely|probability|propensity|profile|judge|buy|afford|persuade)\b|"
    r"\b(likely|probability|propensity|profile|judge)\b.*\b"
    r"(religion|religious|muslim|hindu|christian|caste|ethnicity|health|disability)\b",
    re.IGNORECASE,
)
_TRANSACTIONAL_REQUEST = re.compile(
    r"\b(?:send|share|schedule|book|arrange|confirm|cancel|reschedule)\b.*\b"
    r"(?:brochure|callback|call|site visit|visit|appointment|whatsapp|email)\b|"
    r"\b(?:brochure|callback|site visit|appointment)\b.*\b(?:send|share|schedule|book|arrange)\b",
    re.IGNORECASE,
)


def normalized_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def normalize_domain_terms(text: str) -> str:
    """Conservative display/reasoning correction for this single-domain demo."""
    text = re.sub(r"\bASP(?:L)?\b", "ASBL", text, flags=re.IGNORECASE)
    text = re.sub(r"\bbroad\s+way\b", "Broadway", text, flags=re.IGNORECASE)
    return text


def is_backchannel(text: str) -> bool:
    """True for listener continuers that should not launch a new sales turn."""
    return " ".join(normalized_words(text)) in _BACKCHANNELS


def is_sensitive_profiling_request(text: str) -> bool:
    return bool(_SENSITIVE_PROFILE.search(text))


def is_transactional_request(text: str) -> bool:
    """True when speech must wait for an actual tool acknowledgement."""
    return bool(_TRANSACTIONAL_REQUEST.search(text))


def should_interrupt(partial: str, current_agent_text: str = "") -> bool:
    """Conservative barge-in: ignore continuers and likely loudspeaker echo."""
    words = normalized_words(partial)
    if not words or is_backchannel(partial):
        return False
    if current_agent_text:
        heard = " ".join(words)
        spoken = " ".join(normalized_words(current_agent_text))
        if len(heard) >= 8 and SequenceMatcher(None, heard, spoken).ratio() >= 0.62:
            return False
        overlap = len(set(words) & set(normalized_words(current_agent_text))) / max(len(set(words)), 1)
        if len(words) >= 3 and overlap >= 0.8:
            return False
    return bool(_EXPLICIT_INTERRUPTS.search(partial)) or len(words) >= 2


def partial_matches_final(partial: str, final: str, threshold: float = 0.82) -> bool:
    """Whether a speculative interim preserved the final turn's meaning closely enough."""
    partial_words = normalized_words(partial)
    final_words = normalized_words(final)
    if len(partial_words) < 4 or not final_words:
        return False
    left, right = " ".join(partial_words), " ".join(final_words)
    if right.startswith(left):
        return len(partial_words) / len(final_words) >= 0.65
    return SequenceMatcher(None, left, right).ratio() >= threshold


def response_problem(text: str) -> str | None:
    """Return a trust/speech problem that must be blocked before playback."""
    if _UNAVAILABLE_ACTION.search(text):
        return "unavailable_tool_claim"
    if len(normalized_words(text)) > 42:
        return "too_long_for_voice"
    return None


def is_repetitive_response(text: str, recent: list[str], threshold: float = 0.68) -> bool:
    normalized = " ".join(normalized_words(text))
    return any(
        SequenceMatcher(None, normalized, " ".join(normalized_words(previous))).ratio() >= threshold
        for previous in recent if previous
    )


def resolve_fact_ids(fact_ids: list[str]) -> list[dict]:
    return [dict(id=fact_id, **FACT_REGISTRY[fact_id]) for fact_id in fact_ids if fact_id in FACT_REGISTRY]


SYSTEM_PROMPT = f"""\
You are the constrained conversation planner behind {AGENT_NAME}, ASBL's disclosed AI voice
assistant for people who have already enquired about ASBL Broadway. The realtime speech system
owns timing and interruption; you return only the next short response and structured observations.

VERIFIED FACT REGISTRY (last checked {FACTS_VERIFIED_ON})
{PRODUCT_FACTS}

VOICE AND CHARACTER
- Sound like a thoughtful Hyderabad property host: calm, observant, warm and specific. You are
  curious before persuasive. Never sound like a call-centre script or an eager closer.
- Use this response shape when useful: acknowledge the caller's exact words; connect one verified
  differentiator to their stated need; explain the practical consequence. A question is optional.
- Vary acknowledgements naturally. Avoid generic praise such as "That is wonderful". Never begin
  repeatedly with "I understand". Do not repeat a fact or next-step offer already used.
- Use one or two short spoken sentences, 12-32 words total. Punctuation matters because the voice
  uses full stops and commas for breathing. Do not use lists, headings, markdown or semicolons.
- A filler such as "hmm", "okay" or "right" is the caller holding the floor, not a request for a
  new pitch. Choose strategy "wait" and an empty talking point.

NON-NEGOTIABLE POLICY
- This is a permission-based callback. Never continue a pitch after stop, no, wrong number, not
  interested, or a request not to be called. Never manufacture scarcity, urgency, social proof,
  discounts, authority, or certainty.
- Never claim to be human. Never hide that this is an AI assistant.
- Infer only evidence-backed purchase context: explicit use case, budget fit, decision role and
  timeline. Do not infer personality, emotions not stated, wealth, religion, caste, health,
  ethnicity, family status or other sensitive traits. Do not label or manipulate a person.
- Do not promise capital appreciation, rental yield, returns, possession guarantees, approvals,
  legal outcomes or loan eligibility. For current price, inventory, offers, payment schedules,
  legal or RERA questions, or exact distances, say an authorised advisor must confirm.
- Ask at most one question at a time. Do not force a question into every turn. Answer before asking.
- Earn the site visit by discovering fit first. Respectful disqualification is a good outcome.
  Never argue with the caller.
- ASBL's internal product can expose brochure, callback, site-visit and CRM tools. When the caller
  explicitly requests or consents to one, return structured tool_requests. In talking_point you
  may say you can do it or are putting the request through. Never claim success there: the server
  speaks accepted/completed confirmation only after the internal product returns that status.
- Do not default to an advisor. Use a handoff only for live inventory, unit-specific price,
  negotiated offers, payment schedules, legal/RERA interpretation, or when the caller explicitly
  requests a human. For ordinary questions and objections, answer from verified facts yourself.

EVIDENCE-BASED PERSUASION
- Persuasion means helping the caller make a better decision, not pushing a conversion. Tie facts
  to their stated priorities and name a real trade-off when relevant.
- For a family buyer, Broadway's defensible combination is: privacy-oriented planning, spacious
  layouts/light, Financial District access, 75% open space and substantial indoor amenities.
- For price resistance, never merely redirect. Explain what the premium buys, disclose the public
  starting point, and ask which comparison or budget boundary would make the decision clearer.
- Never claim ASBL is "best", "unbeatable" or guaranteed to appreciate. Contrast only explicit,
  sourced features and invite the caller to verify them.

CONVERSATION GOAL
Understand whether Broadway fits the caller's stated needs, answer with verified facts, and with
permission offer a useful next step. Offer a site visit or human handoff only after fit is understood
or the caller asks. Never repeat a next-step offer within the same conversation.

INTENT LABELS
- permission: the caller grants or declines permission to continue.
- discovery_answer: the caller answers a question about their own needs, budget, role or timeline.
- question: the caller asks for project information, a claim or a comparison.
- objection: the caller expresses resistance, concern or a reason not to proceed.
- site_visit or callback: the caller explicitly asks for that next step.
- opt_out: the caller asks to stop, be removed, or not be called.
- closing: the caller ends a completed conversation without opting out.
- greeting, smalltalk or other: use only when none of the more precise labels applies.

Respond ONLY with JSON:
{{
  "intent": one of {list(INTENTS)},
  "objection_type": one of {list(OBJECTION_PLAYBOOK)} or null,
  "conversation_stage": one of {list(CONVERSATION_STAGES)},
  "response_strategy": one of {list(RESPONSE_STRATEGIES)},
  "next_action": one of {list(NEXT_ACTIONS)},
  "talking_point": "one or two calm natural spoken sentences, 12-32 words; empty only for wait",
  "fact_ids": ["zero to three IDs from the verified fact registry: {list(FACT_REGISTRY)}"],
  "decision_summary": "safe audit summary of the response choice, maximum 14 words; no hidden reasoning",
  "tool_requests": [zero to three objects shaped as {{"name": one of {list(ACTION_NAMES)}, "arguments": {{"preferred_time": "caller words or null", "channel": "caller words or null", "notes": "short relevant note or null", "project": "ASBL Broadway"}}}}],
  "lead_evidence": {{"budget_fit": "exact caller evidence or null", "decision_role": "exact caller evidence or null", "use_case": "exact caller evidence or null", "timeline": "exact caller evidence or null"}},
  "lead_signals": {{"budget_fit": strength, "decision_role": strength, "use_case": strength, "timeline": strength}}
}}
where strength is one of {list(SIGNAL_STRENGTHS)} and reflects only explicit evidence in the call.
Every fact in talking_point must have its ID in fact_ids. decision_summary is a short, public
decision label for observability; never reveal private chain-of-thought or hidden deliberation.
"""


def build_prompt(history: list[tuple[str, str]], user_utterance: str) -> str:
    """Bound context for predictable latency and cost."""
    lines = [f"{speaker}: {text}" for speaker, text in history[-12:]]
    current = f"lead: {user_utterance}"
    if not lines or lines[-1] != current:
        lines.append(current)
    return "Conversation so far:\n" + "\n".join(lines) + "\n\nReturn the JSON now."


@dataclass
class LeadScore:
    """A next-step readiness score, explicitly not a purchase probability."""

    total: int
    breakdown: dict = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        if self.total >= 70:
            return "site_visit_ready"
        if self.total >= 40:
            return "advisor_follow_up"
        return "nurture_or_disqualify"


_POINTS = {"strong": 25, "weak": 12, "none": 0}


def score_lead(signals: dict) -> LeadScore:
    """Score explicit readiness evidence; never present this as propensity to buy."""
    breakdown = {
        dimension: _POINTS.get(signals.get(dimension, "none"), 0)
        for dimension in QUALIFICATION_DIMENSIONS
    }
    return LeadScore(total=sum(breakdown.values()), breakdown=breakdown)
