"""
Fishing harbours around the Indian coast.

The place picker used to hold four hardcoded Bengali names, which broke the
moment someone switched the interface to Hindi — and made the app useless to a
fisherman anywhere outside South 24 Parganas.

COORDINATES ARE APPROXIMATE. They are good enough to pull a forecast for the
right stretch of water, but each one should be checked against the harbour's
published position before the finale. A wrong coordinate here means a correct
answer about the wrong place, which is worse than no answer.

Local names are given in the language of that coast. Where we do not carry the
language yet (Kannada for Karnataka, Konkani for Goa), the English name shows.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Port:
    id: str
    lat: float
    lon: float
    state: str              # display name of the state or UT
    coast: str              # east | west | islands
    names: dict = field(default_factory=dict)   # lang code -> local name

    def name(self, lang: str) -> str:
        return self.names.get(lang) or self.names["en"]


PORTS: list[Port] = [
    # ---------------- West Bengal ----------------
    Port("namkhana", 21.76, 88.23, "West Bengal", "east",
         {"en": "Namkhana", "bn": "নামখানা", "hi": "नामखाना"}),
    Port("kakdwip", 21.88, 88.19, "West Bengal", "east",
         {"en": "Kakdwip", "bn": "কাকদ্বীপ", "hi": "काकद्वीप"}),
    Port("frasergunj", 21.57, 88.26, "West Bengal", "east",
         {"en": "Frasergunj", "bn": "ফ্রেজারগঞ্জ", "hi": "फ्रेजरगंज"}),
    Port("sagar", 21.65, 88.05, "West Bengal", "east",
         {"en": "Sagar Island", "bn": "সাগরদ্বীপ", "hi": "सागर द्वीप"}),
    Port("digha", 21.63, 87.51, "West Bengal", "east",
         {"en": "Digha", "bn": "দিঘা", "hi": "दीघा"}),
    Port("shankarpur", 21.60, 87.58, "West Bengal", "east",
         {"en": "Shankarpur", "bn": "শঙ্করপুর", "hi": "शंकरपुर"}),

    # ---------------- Odisha ----------------
    Port("paradip", 20.31, 86.61, "Odisha", "east",
         {"en": "Paradip", "or": "ପାରାଦୀପ", "hi": "पारादीप", "bn": "পারাদ্বীপ"}),
    Port("dhamra", 20.79, 86.98, "Odisha", "east",
         {"en": "Dhamra", "bn": "ধামরা", "or": "ଧାମରା", "hi": "धामरा"}),
    Port("astaranga", 20.11, 86.34, "Odisha", "east",
         {"en": "Astaranga", "bn": "অস্তরঙ্গ", "or": "ଅସ୍ତରଙ୍ଗ", "hi": "अस्तरंग"}),
    Port("puri", 19.80, 85.82, "Odisha", "east",
         {"en": "Puri", "or": "ପୁରୀ", "hi": "पुरी", "bn": "পুরী"}),
    Port("gopalpur", 19.26, 84.91, "Odisha", "east",
         {"en": "Gopalpur", "bn": "গোপালপুর", "or": "ଗୋପାଳପୁର", "hi": "गोपालपुर"}),

    # ---------------- Andhra Pradesh ----------------
    Port("bhavanapadu", 18.53, 84.30, "Andhra Pradesh", "east",
         {"en": "Bhavanapadu", "bn": "ভবনপাডু", "hi": "भावनापाडु", "te": "భావనపాడు"}),
    Port("visakhapatnam", 17.69, 83.29, "Andhra Pradesh", "east",
         {"en": "Visakhapatnam", "bn": "বিশাখাপত্তনম", "te": "విశాఖపట్నం", "hi": "विशाखापत्तनम"}),
    Port("kakinada", 16.94, 82.24, "Andhra Pradesh", "east",
         {"en": "Kakinada", "bn": "কাকিনাড়া", "te": "కాకినాడ", "hi": "काकीनाडा"}),
    Port("machilipatnam", 16.17, 81.13, "Andhra Pradesh", "east",
         {"en": "Machilipatnam", "bn": "মছলিপত্তনম", "hi": "मछलीपट्टनम", "te": "మచిలీపట్నం"}),
    Port("nizampatnam", 15.90, 80.66, "Andhra Pradesh", "east",
         {"en": "Nizampatnam", "bn": "নিজামপত্তনম", "hi": "निज़ामपट्टनम", "te": "నిజాంపట్నం"}),

    # ---------------- Tamil Nadu ----------------
    Port("chennai", 13.10, 80.30, "Tamil Nadu", "east",
         {"en": "Chennai", "bn": "চেন্নাই", "ta": "சென்னை", "hi": "चेन्नई"}),
    Port("cuddalore", 11.71, 79.78, "Tamil Nadu", "east",
         {"en": "Cuddalore", "bn": "কুড্ডালোর", "hi": "कुड्डालोर", "ta": "கடலூர்"}),
    Port("nagapattinam", 10.77, 79.85, "Tamil Nadu", "east",
         {"en": "Nagapattinam", "bn": "নাগাপট্টিনম", "hi": "नागपट्टिनम", "ta": "நாகப்பட்டினம்"}),
    Port("rameswaram", 9.28, 79.31, "Tamil Nadu", "east",
         {"en": "Rameswaram", "bn": "রামেশ্বরম", "ta": "ராமேஸ்வரம்", "hi": "रामेश्वरम"}),
    Port("thoothukudi", 8.75, 78.20, "Tamil Nadu", "east",
         {"en": "Thoothukudi", "bn": "তুতিকোরিন", "hi": "तूतुकुड़ी", "ta": "தூத்துக்குடி"}),
    Port("kanyakumari", 8.08, 77.55, "Tamil Nadu", "west",
         {"en": "Kanyakumari", "bn": "কন্যাকুমারী", "ta": "கன்னியாகுமரி", "hi": "कन्याकुमारी"}),

    # ---------------- Puducherry ----------------
    Port("puducherry", 11.93, 79.83, "Puducherry", "east",
         {"en": "Puducherry", "bn": "পুদুচেরি", "ta": "புதுச்சேரி", "hi": "पुदुच्चेरी"}),

    # ---------------- Kerala ----------------
    Port("vizhinjam", 8.38, 76.99, "Kerala", "west",
         {"en": "Vizhinjam", "bn": "ভিঝিঞ্জম", "hi": "विझिंजम", "ml": "വിഴിഞ്ഞം"}),
    Port("kollam", 8.88, 76.58, "Kerala", "west",
         {"en": "Kollam", "bn": "কোল্লম", "hi": "कोल्लम", "ml": "കൊല്ലം"}),
    Port("kochi", 9.96, 76.24, "Kerala", "west",
         {"en": "Kochi", "bn": "কোচি", "ml": "കൊച്ചി", "hi": "कोच्चि"}),
    Port("munambam", 10.18, 76.17, "Kerala", "west",
         {"en": "Munambam", "bn": "মুনম্বম", "hi": "मुनंबम", "ml": "മുനമ്പം"}),
    Port("beypore", 11.17, 75.80, "Kerala", "west",
         {"en": "Beypore", "bn": "বেপোর", "hi": "बेपोर", "ml": "ബേപ്പൂർ"}),
    Port("kozhikode", 11.25, 75.77, "Kerala", "west",
         {"en": "Kozhikode", "bn": "কোঝিকোড়", "ml": "കോഴിക്കോട്", "hi": "कोझिकोड"}),

    # ---------------- Karnataka (Kannada not carried yet) ----------------
    Port("mangaluru", 12.85, 74.83, "Karnataka", "west",
         {"en": "Mangaluru", "bn": "ম্যাঙ্গালুরু", "hi": "मंगलुरु"}),
    Port("malpe", 13.35, 74.70, "Karnataka", "west", {"en": "Malpe", "bn": "মালপে", "hi": "मलपे"}),
    Port("honnavar", 14.28, 74.44, "Karnataka", "west", {"en": "Honnavar", "bn": "হোন্নাবর", "hi": "होन्नावर"}),
    Port("karwar", 14.81, 74.12, "Karnataka", "west", {"en": "Karwar", "bn": "কারওয়ার", "hi": "कारवार"}),

    # ---------------- Goa ----------------
    Port("panaji", 15.50, 73.80, "Goa", "west",
         {"en": "Panaji", "bn": "পানাজি", "mr": "पणजी", "hi": "पणजी"}),
    Port("vasco", 15.40, 73.80, "Goa", "west",
         {"en": "Vasco da Gama", "bn": "ভাস্কো দা গামা", "hi": "वास्को द गामा", "mr": "वास्को द गामा"}),


    # ---------------- Maharashtra ----------------
    Port("malvan", 16.06, 73.46, "Maharashtra", "west",
         {"en": "Malvan", "bn": "মালভান", "hi": "मालवण", "mr": "मालवण"}),
    Port("ratnagiri", 16.99, 73.30, "Maharashtra", "west",
         {"en": "Ratnagiri", "bn": "রত্নাগিরি", "mr": "रत्नागिरी", "hi": "रत्नागिरी"}),
    Port("alibag", 18.64, 72.87, "Maharashtra", "west",
         {"en": "Alibag", "bn": "আলিবাগ", "hi": "अलीबाग", "mr": "अलिबाग"}),
    Port("mumbai", 18.91, 72.82, "Maharashtra", "west",
         {"en": "Mumbai (Sassoon Dock)", "bn": "মুম্বই", "mr": "मुंबई", "hi": "मुंबई"}),
    Port("satpati", 19.71, 72.70, "Maharashtra", "west",
         {"en": "Satpati", "bn": "সাতপাটি", "hi": "सातपाटी", "mr": "सातपाटी"}),

    # ---------------- Gujarat ----------------
    Port("veraval", 20.90, 70.37, "Gujarat", "west",
         {"en": "Veraval", "bn": "ভেরাভল", "gu": "વેરાવળ", "hi": "वेरावल"}),
    Port("mangrol", 21.12, 70.12, "Gujarat", "west",
         {"en": "Mangrol", "bn": "মাংরোল", "hi": "मांगरोल", "gu": "માંગરોળ"}),
    Port("porbandar", 21.63, 69.61, "Gujarat", "west",
         {"en": "Porbandar", "bn": "পোরবন্দর", "gu": "પોરબંદર", "hi": "पोरबंदर"}),
    Port("okha", 22.47, 69.07, "Gujarat", "west",
         {"en": "Okha", "bn": "ওখা", "hi": "ओखा", "gu": "ઓખા"}),
    Port("mandvi", 22.83, 69.35, "Gujarat", "west",
         {"en": "Mandvi", "bn": "মান্ডভি", "hi": "मांडवी", "gu": "માંડવી"}),
    Port("jakhau", 23.22, 68.72, "Gujarat", "west",
         {"en": "Jakhau", "bn": "জখৌ", "hi": "जखौ", "gu": "જખૌ"}),

    # ---------------- Islands ----------------
    Port("port_blair", 11.62, 92.73, "Andaman & Nicobar", "islands",
         {"en": "Port Blair", "hi": "पोर्ट ब्लेयर", "bn": "পোর্ট ব্লেয়ার"}),
    Port("kavaratti", 10.57, 72.64, "Lakshadweep", "islands",
         {"en": "Kavaratti", "bn": "কাভারত্তি", "hi": "कवरत्ती", "ml": "കവരത്തി"}),
]

BY_ID = {p.id: p for p in PORTS}


# State names for the picker's group headings. English left them as the one
# untranslated thing in an otherwise translated dropdown.
STATE_NAMES: dict[str, dict[str, str]] = {
    "West Bengal":       {"bn": "পশ্চিমবঙ্গ", "hi": "पश्चिम बंगाल"},
    "Odisha":            {"bn": "ওড়িশা", "hi": "ओडिशा", "or": "ଓଡ଼ିଶା"},
    "Andhra Pradesh":    {"bn": "অন্ধ্রপ্রদেশ", "hi": "आंध्र प्रदेश",
                          "te": "ఆంధ్రప్రదేశ్"},
    "Tamil Nadu":        {"bn": "তামিলনাড়ু", "hi": "तमिलनाडु", "ta": "தமிழ்நாடு"},
    "Puducherry":        {"bn": "পুদুচেরি", "hi": "पुदुच्चेरी", "ta": "புதுச்சேரி"},
    "Kerala":            {"bn": "কেরালা", "hi": "केरल", "ml": "കേരളം"},
    "Karnataka":         {"bn": "কর্ণাটক", "hi": "कर्नाटक"},
    "Goa":               {"bn": "গোয়া", "hi": "गोवा", "mr": "गोवा"},
    "Maharashtra":       {"bn": "মহারাষ্ট্র", "hi": "महाराष्ट्र",
                          "mr": "महाराष्ट्र"},
    "Gujarat":           {"bn": "গুজরাট", "hi": "गुजरात", "gu": "ગુજરાત"},
    "Andaman & Nicobar": {"bn": "আন্দামান ও নিকোবর", "hi": "अंडमान और निकोबार"},
    "Lakshadweep":       {"bn": "লাক্ষাদ্বীপ", "hi": "लक्षद्वीप",
                          "ml": "ലക്ഷദ്വീപ്"},
}


def state_name(state: str, lang: str) -> str:
    return STATE_NAMES.get(state, {}).get(lang) or state


def listing(lang: str) -> list[dict]:
    """Ports grouped by state, named in the interface language where we have it."""
    out: list[dict] = []
    for p in PORTS:
        out.append({
            "id": p.id, "lat": p.lat, "lon": p.lon,
            "state": state_name(p.state, lang), "coast": p.coast,
            "name": p.name(lang),
        })
    return out


# Roughly how far offshore a day boat actually works. Ocean colour asked for
# at the harbour itself is half land, and land has no colour at all.
SEAWARD_DEG = 0.35        # about 38 km


def seaward(p: Port) -> tuple[float, float]:
    """A point out to sea from a harbour, where the fishing actually happens.

    The direction comes from which coast the harbour is on. This is a
    simplification — the coastline turns, and around Kanyakumari and the Gulf
    of Mannar "east" and "west" stop meaning much — but it is far better than
    sampling the harbour basin, and any error puts us further out to sea rather
    than further inland, which is the safe direction to be wrong in.
    """
    if p.coast == "east":
        return round(p.lat - 0.1, 3), round(p.lon + SEAWARD_DEG, 3)
    if p.coast == "west":
        return round(p.lat - 0.1, 3), round(p.lon - SEAWARD_DEG, 3)
    return round(p.lat - SEAWARD_DEG, 3), round(p.lon, 3)   # islands: go south


def nearest(lat: float, lon: float) -> Port:
    """Closest harbour to a GPS fix. Flat distance is fine for ranking."""
    return min(PORTS, key=lambda p: (p.lat - lat) ** 2 + (p.lon - lon) ** 2)
