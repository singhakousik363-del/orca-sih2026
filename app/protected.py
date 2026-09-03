"""
Marine protected areas and seasonal closures.

The problem statement asks for geofence alerts near maritime boundaries *and*
ecologically sensitive zones. The boundaries were the obvious half; this is the
other one, and for many fishermen it is the half that actually catches them.

Crossing into a sanctuary is not a navigational error, it is an offence, and
the penalty falls on the crew rather than on whoever drew the line. Two of
these matter more than the rest:

  Gahirmatha, off Odisha, closes to fishing every year from 1 November to
  31 May while olive ridley turtles nest. It is the world's largest nesting
  beach for them. A boat out of Dhamra or Paradip is working right beside it,
  and the closure is seasonal, so the water that was legal in June is not in
  December — which is exactly the kind of thing an app should be for.

  The Sundarbans sit immediately east of Namkhana and Kakdwip, the two
  harbours this project has been built and tested around.

GEOMETRY IS APPROXIMATE, AND MORE SO THAN THE BOUNDARIES

A gazette notification defines a sanctuary by a list of survey coordinates.
What is here is a centre and a radius, or a corridor along a coast, sized from
the published area. That is enough to say "you are close to Gahirmatha" and
nowhere near enough to say which side of the line a boat is on.

So the warning is deliberately soft: it says a protected area is near and names
it, and it never says a boat is inside one. Telling someone they have committed
an offence on the strength of a circle drawn from an area figure would be worse
than saying nothing.

Before the finale, replace these with the notified boundaries from the state
forest departments or the WDPA, and say in the deck which source was used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import geofence

# Warn from this far out. Wider than the maritime-boundary warning because the
# geometry is rougher, and being told early costs nothing.
NEAR_KM = 15.0


@dataclass(frozen=True)
class Closure:
    """A season when fishing is prohibited, as month and day."""

    start: tuple[int, int]      # (month, day)
    end: tuple[int, int]
    reason: str                 # key into the language pack

    def days_until(self, when: date) -> int | None:
        """Days until this closure begins, if it has not already.

        A closure that starts in three weeks is something to plan around, not
        something to be told about on the morning it takes effect.
        """
        if self.active_on(when):
            return None
        start = date(when.year, *self.start)
        if start < when:
            start = date(when.year + 1, *self.start)
        return (start - when).days

    def active_on(self, when: date) -> bool:
        s = date(when.year, *self.start)
        e = date(when.year, *self.end)
        if s <= e:
            return s <= when <= e
        # a closure that runs across the new year
        return when >= s or when <= e


@dataclass(frozen=True)
class Protected:
    id: str
    names: dict                 # lang -> name
    state: str
    # Either a circle (centre + radius) or a corridor (line + half-width).
    lat: float = 0.0
    lon: float = 0.0
    radius_km: float = 0.0
    line: list = field(default_factory=list)
    corridor_km: float = 0.0
    closure: Closure | None = None

    def name(self, lang: str) -> str:
        return self.names.get(lang) or self.names["en"]

    def distance_km(self, lat: float, lon: float) -> float:
        if self.line:
            best = float("inf")
            for a, b in zip(self.line, self.line[1:]):
                d, _ = geofence._point_to_segment_km((lat, lon), a, b)
                best = min(best, d)
            return max(0.0, best - self.corridor_km)
        return max(0.0, geofence.distance_km((lat, lon), (self.lat, self.lon))
                   - self.radius_km)


AREAS: list[Protected] = [
    Protected(
        id="gahirmatha",
        names={"en": "Gahirmatha Marine Sanctuary", "or": "ଗହୀରମାଥା ସାମୁଦ୍ରିକ ଅଭୟାରଣ୍ୟ",
               "bn": "গহীরমাথা সামুদ্রিক অভয়ারণ্য", "hi": "गहीरमाथा समुद्री अभयारण्य"},
        state="Odisha", lat=20.57, lon=86.84, radius_km=21.0,
        # 1 November to 31 May, for olive ridley nesting
        closure=Closure((11, 1), (5, 31), "turtle_nesting"),
    ),
    Protected(
        id="gulf_of_mannar",
        names={"en": "Gulf of Mannar Marine National Park",
               "ta": "மன்னார் வளைகுடா கடல் தேசிய பூங்கா",
               "bn": "মান্নার উপসাগর সামুদ্রিক জাতীয় উদ্যান",
               "hi": "मन्नार की खाड़ी समुद्री राष्ट्रीय उद्यान"},
        state="Tamil Nadu",
        # a 160 km chain of 21 islands between Thoothukudi and Dhanushkodi
        line=[(8.78, 78.20), (9.05, 78.75), (9.25, 79.15), (9.28, 79.45)],
        corridor_km=12.0,
    ),
    Protected(
        id="sundarbans",
        names={"en": "Sundarbans National Park", "bn": "সুন্দরবন জাতীয় উদ্যান",
               "hi": "सुंदरबन राष्ट्रीय उद्यान"},
        state="West Bengal", lat=21.85, lon=88.85, radius_km=35.0,
    ),
    Protected(
        id="bhitarkanika",
        names={"en": "Bhitarkanika", "or": "ଭିତରକନିକା", "bn": "ভিতরকণিকা",
               "hi": "भितरकनिका"},
        state="Odisha", lat=20.72, lon=86.90, radius_km=18.0,
    ),
    Protected(
        id="gulf_of_kachchh",
        names={"en": "Gulf of Kachchh Marine National Park",
               "gu": "કચ્છના અખાતનું દરિયાઈ રાષ્ટ્રીય ઉદ્યાન",
               "bn": "কচ্ছ উপসাগর সামুদ্রিক জাতীয় উদ্যান",
               "hi": "कच्छ की खाड़ी समुद्री राष्ट्रीय उद्यान"},
        state="Gujarat", lat=22.48, lon=69.75, radius_km=30.0,
    ),
    Protected(
        id="malvan",
        names={"en": "Malvan Marine Sanctuary", "mr": "मालवण सागरी अभयारण्य",
               "bn": "মালভান সামুদ্রিক অভয়ারণ্য", "hi": "मालवण समुद्री अभयारण्य"},
        state="Maharashtra", lat=16.05, lon=73.45, radius_km=6.0,
    ),
    Protected(
        id="coringa",
        names={"en": "Coringa Wildlife Sanctuary", "te": "కోరింగ వన్యప్రాణి అభయారణ్యం",
               "bn": "করিঙ্গা অভয়ারণ্য", "hi": "कोरिंगा वन्यजीव अभयारण्य"},
        state="Andhra Pradesh", lat=16.78, lon=82.32, radius_km=15.0,
    ),
    Protected(
        id="chilika",
        names={"en": "Chilika (Nalabana) Sanctuary", "or": "ଚିଲିକା (ନଳବଣ)",
               "bn": "চিলিকা (নলবন)", "hi": "चिलिका (नलबन)"},
        state="Odisha", lat=19.72, lon=85.35, radius_km=12.0,
    ),
    Protected(
        id="balukhand_konark",
        names={"en": "Balukhand-Konark Wildlife Sanctuary",
               "or": "ବାଲୁଖଣ୍ଡ-କୋଣାର୍କ ଅଭୟାରଣ୍ୟ",
               "bn": "বালুখণ্ড-কোণার্ক অভয়ারণ্য",
               "hi": "बालूखंड-कोणार्क वन्यजीव अभयारण्य"},
        state="Odisha",
        # the coastal strip between Puri and Konark
        line=[(19.81, 85.85), (19.87, 86.00), (19.89, 86.09)],
        corridor_km=5.0,
    ),
    Protected(
        id="point_calimere",
        names={"en": "Point Calimere Wildlife Sanctuary",
               "ta": "கோடியக்கரை வனவிலங்கு சரணாலயம்",
               "bn": "পয়েন্ট ক্যালিমিয়ার অভয়ারণ্য",
               "hi": "पॉइंट कैलिमेरे वन्यजीव अभयारण्य"},
        state="Tamil Nadu", lat=10.29, lon=79.85, radius_km=14.0,
    ),
    Protected(
        id="pulicat",
        names={"en": "Pulicat Lake Bird Sanctuary",
               "ta": "பழவேற்காடு பறவைகள் சரணாலயம்",
               "te": "పులికాట్ సరస్సు పక్షుల అభయారణ్యం",
               "bn": "পুলিকট হ্রদ পক্ষী অভয়ারণ্য",
               "hi": "पुलिकट झील पक्षी अभयारण्य"},
        state="Tamil Nadu", lat=13.55, lon=80.20, radius_km=20.0,
    ),
    Protected(
        id="krishna",
        names={"en": "Krishna Wildlife Sanctuary",
               "te": "కృష్ణా వన్యప్రాణి అభయారణ్యం",
               "bn": "কৃষ্ণা অভয়ারণ্য", "hi": "कृष्णा वन्यजीव अभयारण्य"},
        state="Andhra Pradesh", lat=15.90, lon=80.90, radius_km=22.0,
    ),
    Protected(
        id="rani_jhansi",
        names={"en": "Rani Jhansi Marine National Park",
               "bn": "রানি ঝাঁসি সামুদ্রিক জাতীয় উদ্যান",
               "hi": "रानी झांसी समुद्री राष्ट्रीय उद्यान"},
        state="Andaman & Nicobar", lat=12.15, lon=93.05, radius_km=25.0,
    ),
]


# Far enough ahead to be worth planning around, close enough to be news.
CLOSURE_NOTICE_DAYS = 45


@dataclass(frozen=True)
class Nearby:
    area: Protected
    distance_km: float
    closed: bool                # a seasonal closure is in force today
    opens_in_days: int | None = None    # a closure starting soon

    @property
    def touching(self) -> bool:
        """Close enough that the rough geometry cannot separate in from out.

        Reported as "you are at the edge", never as "you are inside": a circle
        sized from an area figure cannot tell a court which side of a gazetted
        line a boat was on, and neither can we.
        """
        return self.distance_km <= 0.5


def check(lat: float, lon: float, when: date | None = None) -> Nearby | None:
    """The nearest protected area, if one is close enough to matter."""
    when = when or date.today()
    best: Nearby | None = None

    for area in AREAS:
        d = area.distance_km(lat, lon)
        if d > NEAR_KM:
            continue
        closed = bool(area.closure and area.closure.active_on(when))
        soon = None
        if area.closure and not closed:
            ahead = area.closure.days_until(when)
            if ahead is not None and ahead <= CLOSURE_NOTICE_DAYS:
                soon = ahead
        candidate = Nearby(area, round(d, 1), closed, soon)

        if best is None:
            best = candidate
            continue

        # A closure in force outranks a nearer area that is open. Bhitarkanika
        # sits closer to Dhamra than Gahirmatha does, and reporting only the
        # nearer one would bury the fact that the other is shut for seven
        # months of the year — which is the thing the crew can be prosecuted
        # for.
        if closed and not best.closed:
            best = candidate
        elif closed == best.closed:
            # a closure about to start outranks a nearer area with none
            if soon is not None and best.opens_in_days is None:
                best = candidate
            elif (soon is None) == (best.opens_in_days is None) \
                    and d < best.distance_km:
                best = candidate

    return best
