# Duet Phase 2 — the SDR persona (pure logic, no model dependencies).
#
# The persona lives OUTSIDE the voice model on purpose: Moshi owns how things
# get said (timing, tone, interruptions); this module owns what is true (the
# product fact sheet) and what matters (qualification rubric). The reasoning
# layer (reasoning.py) is the bridge: it reads the conversation and returns
# short "talking points" grounded in these facts.

from dataclasses import dataclass, field

# The fictional product every demo and benchmark uses. Fictional so the demo
# never drifts into claims about a real company, but detailed enough that the
# reasoning layer has real facts to ground answers in (and hallucination
# beyond this sheet is detectable — the eval checks for it).
PRODUCT_FACTS = """\
Product: Brewline — inventory management SaaS for specialty coffee shops.
Pricing: Starter $99/mo (1 location); Growth $249/mo (up to 5 locations); 14-day free trial; no setup fee.
Core features: automatic reorder points from sales velocity; waste tracking; supplier price comparison;
POS integrations (Square, Toast, Clover); weekly COGS report.
Typical outcome: customers cut 8-12% off COGS within two months (based on fictional case studies).
Not offered: hardware, payroll, multi-warehouse logistics, custom API work on Starter tier."""

DISCOVERY_QUESTIONS = [
    "What's your role at the shop, and how many locations do you run?",
    "How do you handle inventory and ordering today?",
    "What's the most annoying part of that process?",
    "Roughly how much time does ordering eat per week?",
    "If this worked, when would you want to be up and running?",
]

# The 3 objections the brief requires the persona to handle, plus canonical ids
# so evals can assert classification instead of string-matching prose.
OBJECTION_PLAYBOOK = {
    "status_quo": "Spreadsheets feel free until you count hours and over-ordering; Brewline pays for itself cutting 8-12% of COGS.",
    "price": "It's $99 a month — most shops save multiples of that in reduced waste alone, and the 14-day trial is free.",
    "no_time": "Setup is an afternoon: connect your POS and Brewline builds reorder points from your own sales history.",
}

INTENTS = ("greeting", "discovery_answer", "question", "objection", "closing", "smalltalk", "other")
SIGNAL_STRENGTHS = ("strong", "weak", "none")
BANT = ("budget", "authority", "need", "timeline")

SYSTEM_PROMPT = f"""\
You are the reasoning brain behind a real-time VOICE sales agent for Brewline. The voice model
handles conversational flow on its own; your job is ONLY to supply substance. Ground every answer
strictly in the fact sheet — if the sheet doesn't cover it, say so in the talking point rather
than inventing details.

FACT SHEET
{PRODUCT_FACTS}

GOALS, in order: understand the lead (role, locations, current process, pain, timeline),
handle objections honestly, and move toward booking a demo.

Respond ONLY with JSON:
{{
  "intent": one of {list(INTENTS)},
  "objection_type": one of {list(OBJECTION_PLAYBOOK)} or null,
  "talking_point": "ONE conversational sentence, max 22 words, first person, no emojis",
  "lead_signals": {{"budget": strength, "authority": strength, "need": strength, "timeline": strength}}
}}
where strength is one of {list(SIGNAL_STRENGTHS)} — your cumulative read of the WHOLE call so far.
"""


def build_prompt(history: list[tuple[str, str]], user_utterance: str) -> str:
    """history is [(speaker, text), ...] with speaker in {'agent', 'lead'}."""
    lines = [f"{speaker}: {text}" for speaker, text in history[-12:]]  # bound context, bound cost
    lines.append(f"lead: {user_utterance}")
    return "Conversation so far:\n" + "\n".join(lines) + "\n\nRespond with the JSON now."


@dataclass
class LeadScore:
    total: int
    breakdown: dict = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        if self.total >= 70:
            return "qualified"
        if self.total >= 40:
            return "nurture"
        return "not a fit"


_POINTS = {"strong": 25, "weak": 12, "none": 0}


def score_lead(signals: dict) -> LeadScore:
    """Deterministic BANT rubric: the LLM reports evidence strength, but the
    scoring math lives here where it's testable and can't drift call-to-call."""
    breakdown = {}
    for dim in BANT:
        strength = signals.get(dim, "none")
        breakdown[dim] = _POINTS.get(strength, 0)  # unknown labels score 0, never crash
    return LeadScore(total=sum(breakdown.values()), breakdown=breakdown)
