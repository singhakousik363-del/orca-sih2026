"""
Conversation state.

The problem statement asks for multi-turn conversations where the user can
refine a query. In practice that means: "is tomorrow safe?" then "and the day
after?" then "what if my boat were 12 m?" — each one a fragment that only means
something against the turn before it.

Storage is in-process, which is fine for a demo and for Cloud Run with one
instance. Swap the dict for Firestore before any real deployment; the interface
is the same.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

TTL_SECONDS = 30 * 60


@dataclass
class Turn:
    question: str
    when_key: str          # today | tomorrow | dayafter | now
    intent: str            # safety | fishing | boundary | conditions
    verdict: str = ""


@dataclass
class Session:
    lat: float = 21.55
    lon: float = 88.15
    boat_length_m: float = 9.0
    lang: str = "bn"
    turns: list[Turn] = field(default_factory=list)
    touched: float = field(default_factory=time.time)

    @property
    def last(self) -> Turn | None:
        return self.turns[-1] if self.turns else None


_SESSIONS: dict[str, Session] = {}


def get(session_id: str) -> Session:
    now = time.time()
    for sid, s in list(_SESSIONS.items()):
        if now - s.touched > TTL_SECONDS:
            del _SESSIONS[sid]

    s = _SESSIONS.setdefault(session_id, Session())
    s.touched = now
    return s


# ------------------------------------------------------------ follow-up parsing

# "and the day after?", "what about tomorrow?" — a fragment with no verb of its
# own. Short, and opens with a connective.
FOLLOWUP_OPENERS = (
    "আর", "আচ্ছা", "তাহলে", "এবং",           # bn
    "और", "तो", "फिर",                        # hi / mr
    "અને", "તો",                              # gu
    "ଆଉ", "ତେବେ",                             # or
    "மேலும்", "அப்படியென்றால்",                # ta
    "మరి", "అయితే",                            # te
    "പിന്നെ", "എന്നാൽ",                        # ml
    "and", "what about", "then",              # en
)

# Metres, and feet. A fisherman in Bengal says "thirty foot boat", not
# "nine point one metres" — the register a licence is written in is not the one
# people speak. Both go in, and feet convert.
BOAT_M_PATTERN = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*(?:m\b|মিটার|मीटर|મીટર|ମିଟର|மீட்டர்|మీటర్|മീറ്റർ)",
    re.IGNORECASE,
)
BOAT_FT_PATTERN = re.compile(
    r"(\d{1,3}(?:\.\d)?)\s*"
    r"(?:ft\b|feet\b|foot\b|'|ফুট|फुट|फूट|ફૂટ|ଫୁଟ|அடி|అడుగు|അടി)",
    re.IGNORECASE,
)

FEET_PER_METRE = 3.28084

DAYAFTER_WORDS = ("পরশু", "परसों", "परवा", "પરમ દિવસે", "ପରଦିନ",
                  "நாளை மறுநாள்", "ఎల్లుండి", "മറ്റന്നാൾ", "day after")
TOMORROW_WORDS = ("কাল", "आगामी कल", "कल", "उद्या", "કાલે", "କାଲି",
                  "நாளை", "రేపు", "നാളെ", "tomorrow")


def is_followup(question: str) -> bool:
    q = question.strip().lower()
    if len(q.split()) > 6:
        return False
    return any(q.startswith(w.lower()) for w in FOLLOWUP_OPENERS) or bool(
        BOAT_M_PATTERN.search(question)
        or BOAT_FT_PATTERN.search(question)
    )


def extract_boat(question: str) -> float | None:
    """A boat length from a question, in metres, however it was said.

    Feet are checked first: "30 ft" contains no metre word, but a careless
    metre pattern could still match a stray digit nearby. Whichever unit was
    used, what comes back is metres, because that is what the wave limits are
    written in.
    """
    m = BOAT_FT_PATTERN.search(question)
    if m:
        metres = round(float(m.group(1)) / FEET_PER_METRE, 1)
        return metres if 3 <= metres <= 40 else None

    m = BOAT_M_PATTERN.search(question)
    if not m:
        return None
    v = float(m.group(1))
    return v if 3 <= v <= 40 else None


def extract_when(question: str) -> str | None:
    if any(w in question for w in DAYAFTER_WORDS):
        return "dayafter"
    if any(w in question for w in TOMORROW_WORDS):
        return "tomorrow"
    return None


@dataclass
class Resolved:
    question: str          # what we will actually answer
    when_key: str
    intent: str
    boat_length_m: float
    inherited: bool        # true when context carried the meaning
    carried: list[str] = field(default_factory=list)


def resolve(session: Session, question: str, boat_override: float | None = None) -> Resolved:
    """Work out what a fragment means, given what came before."""
    last = session.last

    # An override is the length showing in the boat field, which is what this
    # person actually said their boat is. Remember it, the way a length typed
    # into the question is remembered.
    #
    # Not doing so had a visible consequence: the answer used the length the
    # user set, but the field then snapped back to the session's stale value,
    # because the page fills it from what the server reports afterwards. The
    # screen ended up showing 18 m beside a limit calculated for 9 m.
    if boat_override:
        session.boat_length_m = boat_override
    boat = boat_override or session.boat_length_m
    carried: list[str] = []

    new_boat = extract_boat(question)
    if new_boat:
        boat = new_boat
        session.boat_length_m = new_boat

    new_when = extract_when(question)

    if last and is_followup(question):
        when = new_when or last.when_key
        intent = last.intent

        # Boat length is a safety parameter and nothing else. Asked after a
        # boundary question, "what if my boat is 18 m" used to inherit the
        # boundary intent and return a word-for-word identical answer, because
        # the distance to a line does not depend on hull length. The user gets
        # no answer to the question they asked. Changing the boat means they
        # want to know what it changes, which is whether it is safe to go.
        # Boat length and time are both safety parameters. Neither moves an
        # international boundary, so inheriting the boundary intent returned a
        # word-for-word identical answer and the user got nothing back for the
        # question they asked. Changing either means asking what it changes.
        if intent == "boundary" and (new_boat or new_when):
            intent = "safety"
            carried.append("boat_switched_to_safety" if new_boat
                           else "time_switched_to_safety")

        if not new_when:
            carried.append("time")
        if not new_boat:
            carried.append("boat")
        carried.append("intent")
        return Resolved(question, when, intent, boat, True, carried)

    when = new_when or "today"
    return Resolved(question, when, "", boat, False, [])
