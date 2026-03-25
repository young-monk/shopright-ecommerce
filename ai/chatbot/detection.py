"""
Safety, intent-signal, and query-analysis detectors for the ShopRight chatbot.

All functions are pure (no I/O, no side effects beyond _session_prev_message).
"""
from __future__ import annotations

import re

# ── Session ending ────────────────────────────────────────────────────────────
SESSION_END_PHRASES = [
    "thanks", "thank you", "that's all", "that's it", "i'm done", "im done",
    "goodbye", "bye", "see you", "see ya", "all set", "got it", "perfect",
    "great thanks", "no more questions", "nothing else", "that's everything",
    "i'm good", "im good", "i'm all good", "that'll do", "no thanks",
]
_AMBIGUOUS_ENDINGS = {"ok", "okay", "k", "sure", "yep", "nope", "nah", "alright", "cool", "noted"}
_BOT_WRAP_UP_SIGNALS = [
    "anything else", "let me know", "here if you need", "feel free to ask",
    "happy to help", "have a great day", "come back", "is there anything",
    "can i help", "hope that helps", "if you need anything",
]

SESSION_END_RESPONSE = (
    "You're welcome! Before you go — how would you rate your experience today? "
    "Your feedback helps us improve. ⭐"
)


def is_session_ending(message: str, history: list) -> bool:
    msg = message.lower().strip()
    if len(msg.split()) > 6:
        return False
    if any(phrase in msg for phrase in SESSION_END_PHRASES):
        return True
    if msg in _AMBIGUOUS_ENDINGS and history:
        last_bot = next((m.content.lower() for m in reversed(history) if m.role == "assistant"), "")
        if any(signal in last_bot for signal in _BOT_WRAP_UP_SIGNALS):
            return True
    return False


# ── Wellbeing ─────────────────────────────────────────────────────────────────
WELLBEING_PATTERNS = [
    "feeling low", "feeling sad", "feeling depressed", "feeling lonely",
    "i'm sad", "im sad", "i'm depressed", "im depressed",
    "i'm lonely", "im lonely", "i'm not okay", "im not okay",
    "not doing well", "talk to me", "need someone to talk",
    "having a hard time", "going through a tough time",
    "stressed", "anxious", "overwhelmed", "hopeless",
    "want to hurt", "hurting myself", "end my life", "suicide",
    "nobody cares", "no one cares", "feel worthless",
]

WELLBEING_RESPONSE = (
    "I'm really sorry to hear you're feeling this way. "
    "I'm a shopping assistant and not equipped to provide the support you deserve right now, "
    "but please know that help is available.\n\n"
    "If you're in crisis or need someone to talk to, please reach out to a crisis helpline — "
    "in the US you can call or text **988** (Suicide & Crisis Lifeline), available 24/7.\n\n"
    "Take care of yourself. When you're ready, I'm here to help with any home improvement needs. 💙"
)


def is_wellbeing_message(message: str) -> bool:
    msg = message.lower().strip()
    return any(pattern in msg for pattern in WELLBEING_PATTERNS)


# ── Unanswered / scope ────────────────────────────────────────────────────────
UNCERTAINTY_PHRASES = [
    "i don't have", "i don't know", "i'm not sure", "i cannot find",
    "not available in", "no information", "outside my knowledge",
    "can't help with that", "unable to find", "not in our catalog",
]

_INJECTION_RESPONSE    = "I'm ShopRight's home improvement assistant and I'm not able to help with that request. Is there something around the house I can help you with?"
_VULGAR_RESPONSE       = "That's not something I'm able to help with. I'm ShopRight's home improvement assistant — is there a project or product I can help you find?"
_SCOPE_REJECTION_MARKER = "i'm here to help with home improvement"


def detect_unanswered(response: str, sources_count: int, history: list) -> bool:
    response_lower = response.lower()
    has_uncertainty = any(phrase in response_lower for phrase in UNCERTAINTY_PHRASES)
    return sources_count == 0 and has_uncertainty


def detect_scope_rejected(response: str) -> bool:
    return _SCOPE_REJECTION_MARKER in response.lower()


# ── Vulgar / sexual content ───────────────────────────────────────────────────
_VULGAR_PATTERNS: list[tuple[str, str]] = [
    (r"\b(porn|pornography|xxx|onlyfans)\b",                        "pornography"),
    (r"\b(naked|nude|nudity|nudes)\b",                              "nudity"),
    (r"\b(sex|sexual|sexually|intercourse|foreplay)\b",             "sexual"),
    (r"\b(masturbat\w+|orgasm|ejaculat\w+)\b",                      "explicit_sexual"),
    (r"\b(erotic|erotica|fetish|bdsm|kink\w*)\b",                   "explicit_sexual"),
    (r"\b(fuck|fucking|fucked|fucker|fucks)\b",                     "profanity"),
    (r"\bc[u\*]nt\b",                                               "profanity"),
    (r"\bcock\b(?!\s*(pit|roach|tail|erel|atoo))",                  "sexual"),
    (r"\bdick\b(?!\s*(ens|inson|son))",                             "sexual"),
    (r"\bpussy\b(?!\s*(cat|willow|foot))",                          "sexual"),
    (r"\bash+ole\b",                                                 "profanity"),
    (r"\bwhor[e\b]",                                                 "profanity"),
    (r"\bslut\b",                                                    "profanity"),
    (r"\b(have sex|sleep with|hook up) with you\b",                 "sexual_solicitation"),
    (r"\bshow me your (body|breasts?|genitals?)\b",                 "sexual_solicitation"),
    (r"\bsend (me )?(nudes?|naked|sexy) (pics?|photos?|pictures?)", "sexual_solicitation"),
]


def detect_vulgar(message: str) -> tuple[bool, str | None]:
    msg_lower = message.lower()
    for pattern, label in _VULGAR_PATTERNS:
        if re.search(pattern, msg_lower):
            return True, label
    return False, None


# ── Prompt injection ──────────────────────────────────────────────────────────
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+)?previous\s+instructions?",                 "ignore_instructions"),
    (r"(disregard|forget)\s+(your\s+)?(previous\s+)?instructions?", "disregard_instructions"),
    (r"you\s+are\s+now\s+(a|an|the)\s+",                           "persona_override"),
    (r"act\s+as\s+(a|an|the)\s+(?!store|sales|product|shop)",      "act_as"),
    (r"pretend\s+(you\s+are|to\s+be)\s+",                          "pretend_as"),
    (r"\b(jailbreak|dan\s+mode|do\s+anything\s+now)\b",            "jailbreak"),
    (r"reveal\s+(your\s+)?(system\s+)?(prompt|instructions?)",      "extract_prompt"),
    (r"what\s+(are|were)\s+your\s+(system\s+)?instructions?",       "extract_prompt"),
    (r"override\s+(your\s+)?(safety|guidelines?|instructions?)",    "safety_override"),
]
_INJECTION_MSG_MAX_LEN = 4000


def detect_prompt_injection(message: str) -> tuple[bool, str | None]:
    if len(message) > _INJECTION_MSG_MAX_LEN:
        return True, "message_too_long"
    msg_lower = message.lower()
    for pattern, label in _INJECTION_PATTERNS:
        if re.search(pattern, msg_lower):
            return True, label
    return False, None


# ── Frustration ───────────────────────────────────────────────────────────────
_FRUSTRATION_PATTERNS: list[tuple[str, str]] = [
    (r"\b(never mind|nevermind|forget it|forget that)\b",                    "giving_up"),
    (r"\bnot (what i|what I) (needed|wanted|asked|meant|was looking for)\b", "mismatch"),
    (r"\bthat'?s? (not (right|helpful|correct|what i|it)|wrong)\b",         "rejection"),
    (r"\b(useless|not helpful|unhelpful|doesn'?t help)\b",                  "unhelpful"),
    (r"\bjust (search|look|find) (it |myself|on my own)",                   "abandoning"),
    (r"\bno[,.]?\s+(not that|that'?s? not)\b",                              "rejection"),
    (r"\b(wrong product|wrong item|not the right)\b",                       "mismatch"),
]

# Last user message per session — for repeated-rephrase detection
_session_prev_message: dict[str, str] = {}


def detect_frustration(message: str, session_id: str, prev_was_unanswered: bool) -> tuple[bool, str | None]:
    msg_lower = message.lower()
    for pattern, label in _FRUSTRATION_PATTERNS:
        if re.search(pattern, msg_lower):
            return True, label
    # Repeated rephrase: Jaccard word overlap > 60% with previous turn
    prev = _session_prev_message.get(session_id, "")
    if prev:
        prev_words = set(prev.lower().split())
        curr_words = set(msg_lower.split())
        if len(prev_words) > 2 and len(curr_words) > 2:
            overlap = len(prev_words & curr_words) / len(prev_words | curr_words)
            if overlap > 0.6:
                return True, "repeated_rephrase"
    if prev_was_unanswered:
        return True, "after_unanswered"
    return False, None


# ── Category detection ────────────────────────────────────────────────────────
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Power Tools":            ["drill", "saw", "grinder", "sander", "router", "jigsaw", "circular saw", "impact driver", "nail gun", "heat gun", "power tool"],
    "Hand Tools":             ["hammer", "screwdriver", "wrench", "pliers", "chisel", "hand tool", "tape measure", "level", "utility knife"],
    "Outdoor & Garden":       ["lawn", "mower", "garden", "grass", "trimmer", "edger", "fertilizer", "soil", "mulch", "seed", "weed", "sprinkler", "hose", "rake", "shovel", "chainsaw", "leaf blower", "pressure washer", "snow blower", "generator", "outdoor power"],
    "Plumbing":               ["pipe", "faucet", "toilet", "sink", "drain", "valve", "fitting", "plumbing", "water heater", "garbage disposal"],
    "Electrical":             ["wire", "cable", "outlet", "switch", "breaker", "circuit", "electrical", "conduit", "panel", "speaker wire", "in-wall wire", "audio cable"],
    "Flooring":               ["floor", "tile", "hardwood", "laminate", "vinyl", "carpet", "grout", "underlayment"],
    "Paint & Supplies":       ["paint", "primer", "stain", "brush", "roller", "spray", "coating", "varnish", "caulk", "sealant"],
    "Safety & Security":      ["safety", "glove", "helmet", "goggle", "respirator", "harness", "protective", "lock", "deadbolt", "camera", "alarm"],
    "Storage & Organization": ["shelf", "cabinet", "rack", "storage", "organizer", "bin", "drawer", "pegboard"],
    "Heating & Cooling":      ["hvac", "air conditioner", "heater", "furnace", "duct", "vent", "thermostat", "filter", "fan", "dehumidifier"],
    "Building Materials":     ["insulation", "soundproof", "sound dampening", "acoustic", "drywall", "home theatre", "home theater", "theatre room", "theater room", "sound barrier", "noise reduction", "framing", "lumber", "plywood", "concrete", "cement", "batt", "r-value"],
}


def detect_category(query: str) -> str | None:
    query_lower = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return category
    return None


# ── Price extraction ──────────────────────────────────────────────────────────
_PRICE_PATTERNS = [
    r'under\s*\$?(\d+(?:\.\d+)?)',
    r'below\s*\$?(\d+(?:\.\d+)?)',
    r'less\s+than\s*\$?(\d+(?:\.\d+)?)',
    r'cheaper\s+than\s*\$?(\d+(?:\.\d+)?)',
    r'up\s+to\s*\$?(\d+(?:\.\d+)?)',
    r'within\s*\$?(\d+(?:\.\d+)?)',
    r'max(?:imum)?\s*\$?(\d+(?:\.\d+)?)',
    r'budget\s*(?:of\s*|around\s*|~\s*)?\$?(\d+(?:\.\d+)?)',
    r'\$?(\d+(?:\.\d+)?)\s*budget',
    r'around\s*\$(\d+(?:\.\d+)?)',
]


def extract_price_limit(query: str) -> float | None:
    for pattern in _PRICE_PATTERNS:
        m = re.search(pattern, query.lower())
        if m:
            return float(m.group(1))
    return None
