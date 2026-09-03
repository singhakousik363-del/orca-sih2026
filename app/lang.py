"""
Language layer.

The risk agent must never produce a sentence. It produces facts — a kind and
some numbers — and this module turns them into a sentence in whichever language
the user asked in. That separation is what makes eight languages a phrase pack
instead of eight copies of the reasoning code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------- detection

# Unicode blocks. Bengali and Assamese share a script; so do Hindi and Marathi.
# Script alone cannot separate those pairs — keywords below do the rest.
SCRIPTS = {
    "bn": (0x0980, 0x09FF),   # Bengali / Assamese
    "hi": (0x0900, 0x097F),   # Devanagari — Hindi / Marathi
    "gu": (0x0A80, 0x0AFF),
    "or": (0x0B00, 0x0B7F),
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
    "ml": (0x0D00, 0x0D7F),
}

# Words that appear in Marathi but not Hindi, to split the shared script.
MARATHI_MARKERS = ("आहे", "नाही", "काय", "उद्या", "समुद्रात", "किती", "माझ")


def detect(text: str) -> str:
    """Return a language code. Falls back to Bengali, our primary field language."""
    counts = {code: 0 for code in SCRIPTS}
    for ch in text:
        cp = ord(ch)
        for code, (lo, hi) in SCRIPTS.items():
            if lo <= cp <= hi:
                counts[code] += 1
                break

    if not any(counts.values()):
        return "en" if re.search(r"[A-Za-z]", text) else "bn"

    best = max(counts, key=counts.get)
    if best == "hi" and any(w in text for w in MARATHI_MARKERS):
        return "mr"
    return best


LANG_NAMES = {
    "bn": "বাংলা", "hi": "हिन्दी", "mr": "मराठी", "gu": "ગુજરાતી",
    "or": "ଓଡ଼ିଆ", "ta": "தமிழ்", "te": "తెలుగు", "ml": "മലയാളം", "en": "English",
}

# BCP-47 tags for the browser's speech engine
SPEECH_TAG = {
    "bn": "bn-IN", "hi": "hi-IN", "mr": "mr-IN", "gu": "gu-IN", "or": "or-IN",
    "ta": "ta-IN", "te": "te-IN", "ml": "ml-IN", "en": "en-IN",
}

# --------------------------------------------------------------- numerals

_DIGITS = {
    "bn": "০১২৩৪৫৬৭৮৯",
    "hi": "०१२३४५६७८९",
    "mr": "०१२३४५६७८९",
    "gu": "૦૧૨૩૪૫૬૭૮૯",
    "or": "୦୧୨୩୪୫୬୭୮୯",
}


def num(value, lang: str) -> str:
    """Localise digits. Tamil, Telugu and Malayalam use Latin digits in
    everyday writing, so they are deliberately left alone."""
    s = str(value)
    table = _DIGITS.get(lang)
    return s.translate(str.maketrans("0123456789", table)) if table else s


# --------------------------------------------------------------- time of day

# "4 o'clock" is ambiguous to a fisherman deciding whether to launch at dawn.
# Every Indian language has ordinary words for the part of the day; use them.
PERIODS: dict[str, list[str]] = {
    #        night        morning     midday        afternoon    evening
    "bn": ["রাত", "সকাল", "দুপুর", "বিকেল", "সন্ধ্যা"],
    "hi": ["रात", "सुबह", "दोपहर", "शाम", "शाम"],
    "mr": ["रात्री", "सकाळी", "दुपारी", "संध्याकाळी", "संध्याकाळी"],
    "gu": ["રાત્રે", "સવારે", "બપોરે", "સાંજે", "સાંજે"],
    "or": ["ରାତି", "ସକାଳ", "ଦ୍ୱିପହର", "ଅପରାହ୍ନ", "ସନ୍ଧ୍ୟା"],
    "ta": ["இரவு", "காலை", "மதியம்", "மாலை", "மாலை"],
    "te": ["రాత్రి", "ఉదయం", "మధ్యాహ్నం", "సాయంత్రం", "సాయంత్రం"],
    "ml": ["രാത്രി", "രാവിലെ", "ഉച്ചയ്ക്ക്", "വൈകുന്നേരം", "വൈകുന്നേരം"],
    "en": ["night", "morning", "midday", "afternoon", "evening"],
}


def period(hour24: int, lang: str) -> str:
    if hour24 < 5:
        i = 0
    elif hour24 < 12:
        i = 1
    elif hour24 < 16:
        i = 2
    elif hour24 < 19:
        i = 3
    else:
        i = 4
    return PERIODS.get(lang, PERIODS["en"])[i]


def hour12(hour24: int) -> int:
    h = hour24 % 12
    return 12 if h == 0 else h


# --------------------------------------------------------------- phrases

@dataclass(frozen=True)
class Phrase:
    """One renderable fact. `data` holds numbers, never prose."""

    kind: str
    data: dict


# {kind: {lang: template}} — templates take already-localised values
PHRASES: dict[str, dict[str, str]] = {
    "waves": {
        "bn": "ঢেউ সর্বোচ্চ {wave} মিটার, আপনার নৌকার সীমা {limit} মিটার",
        "hi": "लहरें अधिकतम {wave} मीटर, आपकी नाव की सीमा {limit} मीटर",
        "mr": "लाटा जास्तीत जास्त {wave} मीटर, तुमच्या नावेची मर्यादा {limit} मीटर",
        "gu": "મોજાં મહત્તમ {wave} મીટર, તમારી હોડીની મર્યાદા {limit} મીટર",
        "or": "ଢେଉ ସର୍ବାଧିକ {wave} ମିଟର, ଆପଣଙ୍କ ଡଙ୍ଗାର ସୀମା {limit} ମିଟର",
        "ta": "அலைகள் அதிகபட்சம் {wave} மீட்டர், உங்கள் படகின் வரம்பு {limit} மீட்டர்",
        "te": "అలలు గరిష్ఠంగా {wave} మీటర్లు, మీ పడవ పరిమితి {limit} మీటర్లు",
        "ml": "തിരമാലകൾ പരമാവധി {wave} മീറ്റർ, നിങ്ങളുടെ വള്ളത്തിന്റെ പരിധി {limit} മീറ്റർ",
        "en": "waves up to {wave} m against a {limit} m limit for your boat",
    },
    "wind": {
        "bn": "দমকা হাওয়া {gust} নট পর্যন্ত",
        "hi": "झोंकेदार हवा {gust} नॉट तक",
        "mr": "सोसाट्याचा वारा {gust} नॉटपर्यंत",
        "gu": "ઝાપટાનો પવન {gust} નોટ સુધી",
        "or": "ଝଡ଼ ପବନ {gust} ନଟ ପର୍ଯ୍ୟନ୍ତ",
        "ta": "பலத்த காற்று {gust} நாட் வரை",
        "te": "బలమైన గాలులు {gust} నాట్ల వరకు",
        "ml": "ശക്തമായ കാറ്റ് {gust} നോട്ട് വരെ",
        "en": "gusts up to {gust} kn",
    },
    "thunder": {
        "bn": "{part} {hour}টার পর বজ্রপাতের আশঙ্কা",
        "hi": "{part} {hour} बजे के बाद बिजली गिरने की आशंका",
        "mr": "{hour} वाजल्यानंतर विजेचा धोका",
        "gu": "{part} {hour} વાગ્યા પછી વીજળીનું જોખમ",
        "or": "{part} {hour}ଟା ପରେ ବଜ୍ରପାତର ଆଶଙ୍କା",
        "ta": "{part} {hour} மணிக்குப் பிறகு இடி மின்னல் அபாயம்",
        "te": "{part} {hour} గంటల తర్వాత పిడుగుల ప్రమాదం",
        "ml": "{part} {hour} മണിക്ക് ശേഷം ഇടിമിന്നൽ സാധ്യത",
        "en": "thunderstorm risk after {part} {hour}:00",
    },
    "sst": {
        "bn": "সমুদ্রের জলের তাপমাত্রা {sst}°",
        "hi": "समुद्र के पानी का तापमान {sst}°",
        "mr": "समुद्राच्या पाण्याचे तापमान {sst}°",
        "gu": "દરિયાના પાણીનું તાપમાન {sst}°",
        "or": "ସମୁଦ୍ର ଜଳର ତାପମାତ୍ରା {sst}°",
        "ta": "கடல் நீரின் வெப்பநிலை {sst}°",
        "te": "సముద్ర నీటి ఉష్ణోగ్రత {sst}°",
        "ml": "കടൽജലത്തിന്റെ താപനില {sst}°",
        "en": "sea temperature {sst}°C",
    },
    "current": {
        "bn": "স্রোত {kn} নট, {dir} দিকে",
        "hi": "धारा {kn} नॉट, {dir} की ओर",
        "mr": "प्रवाह {kn} नॉट, {dir} दिशेला",
        "gu": "પ્રવાહ {kn} નોટ, {dir} તરફ",
        "or": "ସ୍ରୋତ {kn} ନଟ, {dir} ଦିଗକୁ",
        "ta": "நீரோட்டம் {kn} நாட், {dir} திசையில்",
        "te": "ప్రవాహం {kn} నాట్లు, {dir} వైపు",
        "ml": "ഒഴുക്ക് {kn} നോട്ട്, {dir} ദിശയിൽ",
        "en": "current {kn} kn setting {dir}",
    },
    "chl": {
        "bn": "জলে প্ল্যাঙ্কটন {band} ({v} mg/m³) — মাছের সম্ভাবনার ইঙ্গিত",
        "hi": "पानी में प्लवक {band} ({v} mg/m³) — मछली की संभावना का संकेत",
        "mr": "पाण्यात प्लवक {band} ({v} mg/m³) — माशांच्या शक्यतेचा संकेत",
        "gu": "પાણીમાં પ્લવક {band} ({v} mg/m³) — માછલીની સંભાવનાનો સંકેત",
        "or": "ଜଳରେ ପ୍ଲାଙ୍କଟନ {band} ({v} mg/m³) — ମାଛର ସମ୍ଭାବନାର ସଙ୍କେତ",
        "ta": "நீரில் பிளாங்க்டன் {band} ({v} mg/m³) — மீன் வாய்ப்பின் அறிகுறி",
        "te": "నీటిలో ప్లవకాలు {band} ({v} mg/m³) — చేపల అవకాశ సూచన",
        "ml": "വെള്ളത്തിൽ പ്ലവകങ്ങൾ {band} ({v} mg/m³) — മത്സ്യസാധ്യതയുടെ സൂചന",
        "en": "plankton {band} ({v} mg/m3) — a sign of fishing potential",
    },
    "pfz": {
        "bn": "{dist} কিমি {dir} দিকে মাছের সম্ভাবনা {strength} — জলের তাপমাত্রার সীমানায় প্ল্যাঙ্কটন জমেছে",
        "hi": "{dist} किमी {dir} की ओर मछली की संभावना {strength} — तापमान की सीमा पर प्लवक जमा है",
        "mr": "{dist} किमी {dir} दिशेला माशांची शक्यता {strength} — तापमानाच्या सीमेवर प्लवक जमले आहे",
        "gu": "{dist} કિમી {dir} તરફ માછલીની સંભાવના {strength} — તાપમાનની સીમા પર પ્લવક જમા છે",
        "or": "{dist} କିମି {dir} ଦିଗରେ ମାଛର ସମ୍ଭାବନା {strength} — ତାପମାତ୍ରା ସୀମାରେ ପ୍ଲାଙ୍କଟନ ଜମିଛି",
        "ta": "{dist} கிமீ {dir} திசையில் மீன் வாய்ப்பு {strength} — வெப்பநிலை எல்லையில் பிளாங்க்டன் திரண்டுள்ளது",
        "te": "{dist} కిమీ {dir} వైపు చేపల అవకాశం {strength} — ఉష్ణోగ్రత సరిహద్దులో ప్లవకాలు పేరుకున్నాయి",
        "ml": "{dist} കിമീ {dir} ദിശയിൽ മത്സ്യസാധ്യത {strength} — താപനില അതിരിൽ പ്ലവകങ്ങൾ കൂടിയിരിക്കുന്നു",
        "en": "fishing potential {strength} {dist} km to the {dir} — plankton gathering at a temperature front",
    },
    "pfz_none": {
        "bn": "কাছাকাছি স্পষ্ট মাছের এলাকা পাওয়া যায়নি — তাপমাত্রার সীমানা আর প্ল্যাঙ্কটন একসঙ্গে মিলছে না",
        "hi": "आसपास स्पष्ट मछली क्षेत्र नहीं मिला — तापमान सीमा और प्लवक एक साथ नहीं मिल रहे",
        "mr": "जवळपास स्पष्ट मासेक्षेत्र सापडले नाही — तापमान सीमा आणि प्लवक एकत्र येत नाहीत",
        "gu": "નજીકમાં સ્પષ્ટ માછલી વિસ્તાર મળ્યો નથી — તાપમાન સીમા અને પ્લવક સાથે મળતા નથી",
        "or": "ନିକଟରେ ସ୍ପଷ୍ଟ ମାଛ କ୍ଷେତ୍ର ମିଳିଲା ନାହିଁ — ତାପମାତ୍ରା ସୀମା ଓ ପ୍ଲାଙ୍କଟନ ଏକାଠି ମିଳୁନାହିଁ",
        "ta": "அருகில் தெளிவான மீன்பிடி பகுதி இல்லை — வெப்பநிலை எல்லையும் பிளாங்க்டனும் ஒன்றாக இல்லை",
        "te": "సమీపంలో స్పష్టమైన చేపల ప్రాంతం లేదు — ఉష్ణోగ్రత సరిహద్దు, ప్లవకాలు కలిసి రావడం లేదు",
        "ml": "അടുത്ത് വ്യക്തമായ മത്സ്യമേഖല കണ്ടെത്തിയില്ല — താപനില അതിരും പ്ലവകങ്ങളും ഒരുമിച്ചു വരുന്നില്ല",
        "en": "no clear fishing zone nearby — the temperature front and the plankton are not coinciding",
    },
    "tide": {
        "bn": "জোয়ার {state}, {part} {hour}টায় {turns}",
        "hi": "ज्वार {state}, {part} {hour} बजे {turns}",
        "mr": "भरती {state}, {part} {hour} वाजता {turns}",
        "gu": "ભરતી {state}, {part} {hour} વાગ્યે {turns}",
        "or": "ଜୁଆର {state}, {part} {hour}ଟାରେ {turns}",
        "ta": "அலைமட்டம் {state}, {part} {hour} மணிக்கு {turns}",
        "te": "ఆటుపోట్లు {state}, {part} {hour} గంటలకు {turns}",
        "ml": "വേലിയേറ്റം {state}, {part} {hour} മണിക്ക് {turns}",
        "en": "tide {state}, {turns} at {part} {hour}:00",
    },
    "tide_flat": {
        "bn": "জোয়ার এখন স্থির",
        "hi": "ज्वार अभी स्थिर है",
        "mr": "भरती सध्या स्थिर आहे",
        "gu": "ભરતી અત્યારે સ્થિર છે",
        "or": "ଜୁଆର ବର୍ତ୍ତମାନ ସ୍ଥିର",
        "ta": "அலைமட்டம் இப்போது நிலையாக உள்ளது",
        "te": "ఆటుపోట్లు ప్రస్తుతం స్థిరంగా ఉన్నాయి",
        "ml": "വേലിയേറ്റം ഇപ്പോൾ സ്ഥിരമാണ്",
        "en": "tide is slack",
    },
    "system": {
        "bn": "ব্যারোমিটার দ্রুত পড়ছে ({hpa} hPa) আর প্রবল বাতাস — আবহাওয়া দপ্তরের সতর্কতা দেখে নিন",
        "hi": "बैरोमीटर तेज़ी से गिर रहा है ({hpa} hPa) और तेज़ हवा — मौसम विभाग की चेतावनी देखें",
        "mr": "बॅरोमीटर वेगाने घसरत आहे ({hpa} hPa) आणि जोरदार वारा — हवामान खात्याचा इशारा पहा",
        "gu": "બેરોમીટર ઝડપથી ઘટી રહ્યું છે ({hpa} hPa) અને તેજ પવન — હવામાન વિભાગની ચેતવણી જુઓ",
        "or": "ବାରୋମିଟର ଶୀଘ୍ର ପଡ଼ୁଛି ({hpa} hPa) ଏବଂ ପ୍ରବଳ ପବନ — ପାଗ ବିଭାଗର ସତର୍କତା ଦେଖନ୍ତୁ",
        "ta": "காற்றழுத்தம் வேகமாக குறைகிறது ({hpa} hPa), பலத்த காற்று — வானிலை மையத்தின் எச்சரிக்கையைப் பாருங்கள்",
        "te": "బారోమీటర్ వేగంగా పడుతోంది ({hpa} hPa), బలమైన గాలులు — వాతావరణ శాఖ హెచ్చరిక చూడండి",
        "ml": "മർദ്ദം വേഗത്തിൽ താഴുന്നു ({hpa} hPa), ശക്തമായ കാറ്റ് — കാലാവസ്ഥാ വകുപ്പിന്റെ മുന്നറിയിപ്പ് നോക്കുക",
        "en": "barometer falling fast ({hpa} hPa) with gale-force wind — check the IMD warning",
    },
    "mpa_closed": {
        "bn": "{name} — এখন মাছ ধরা নিষিদ্ধ ({reason}), {dist} কিমি দূরে",
        "hi": "{name} — अभी मछली पकड़ना प्रतिबंधित ({reason}), {dist} किमी दूर",
        "mr": "{name} — सध्या मासेमारी बंद ({reason}), {dist} किमी दूर",
        "gu": "{name} — હાલ માછીમારી પ્રતિબંધિત ({reason}), {dist} કિમી દૂર",
        "or": "{name} — ବର୍ତ୍ତମାନ ମାଛ ଧରା ନିଷେଧ ({reason}), {dist} କିମି ଦୂରରେ",
        "ta": "{name} — தற்போது மீன்பிடி தடை ({reason}), {dist} கிமீ தொலைவில்",
        "te": "{name} — ప్రస్తుతం చేపల వేట నిషేధం ({reason}), {dist} కిమీ దూరంలో",
        "ml": "{name} — ഇപ്പോൾ മീൻപിടിത്തം നിരോധിതം ({reason}), {dist} കിമീ അകലെ",
        "en": "{name} — fishing is banned right now ({reason}), {dist} km away",
    },
    "mpa_soon": {
        "bn": "{name} {dist} কিমি দূরে — {days} দিন পর মাছ ধরা বন্ধ হবে ({reason})",
        "hi": "{name} {dist} किमी दूर — {days} दिन बाद मछली पकड़ना बंद ({reason})",
        "mr": "{name} {dist} किमी दूर — {days} दिवसांनी मासेमारी बंद ({reason})",
        "gu": "{name} {dist} કિમી દૂર — {days} દિવસ પછી માછીમારી બંધ ({reason})",
        "or": "{name} {dist} କିମି ଦୂରରେ — {days} ଦିନ ପରେ ମାଛ ଧରା ବନ୍ଦ ({reason})",
        "ta": "{name} {dist} கிமீ தொலைவில் — {days} நாட்களில் மீன்பிடி தடை ({reason})",
        "te": "{name} {dist} కిమీ దూరంలో — {days} రోజుల్లో చేపల వేట నిషేధం ({reason})",
        "ml": "{name} {dist} കിമീ അകലെ — {days} ദിവസത്തിനുള്ളിൽ മീൻപിടിത്തം നിരോധിക്കും ({reason})",
        "en": "{name} is {dist} km away — fishing closes in {days} days ({reason})",
    },
    "mpa_near": {
        "bn": "{name} {dist} কিমি দূরে — সংরক্ষিত এলাকা, ঢুকবেন না",
        "hi": "{name} {dist} किमी दूर — संरक्षित क्षेत्र, प्रवेश न करें",
        "mr": "{name} {dist} किमी दूर — संरक्षित क्षेत्र, प्रवेश करू नका",
        "gu": "{name} {dist} કિમી દૂર — સંરક્ષિત વિસ્તાર, પ્રવેશશો નહીં",
        "or": "{name} {dist} କିମି ଦୂରରେ — ସଂରକ୍ଷିତ କ୍ଷେତ୍ର, ପ୍ରବେଶ କରନ୍ତୁ ନାହିଁ",
        "ta": "{name} {dist} கிமீ தொலைவில் — பாதுகாக்கப்பட்ட பகுதி, நுழைய வேண்டாம்",
        "te": "{name} {dist} కిమీ దూరంలో — రక్షిత ప్రాంతం, ప్రవేశించవద్దు",
        "ml": "{name} {dist} കിമീ അകലെ — സംരക്ഷിത മേഖല, പ്രവേശിക്കരുത്",
        "en": "{name} is {dist} km away — a protected area, do not enter",
    },
    "mpa_edge": {
        "bn": "{name}-এর কিনারায় আছেন — সংরক্ষিত এলাকা, সাবধান",
        "hi": "{name} के किनारे हैं — संरक्षित क्षेत्र, सावधान",
        "mr": "{name} च्या काठावर आहात — संरक्षित क्षेत्र, सावध",
        "gu": "{name} ની કિનારે છો — સંરક્ષિત વિસ્તાર, સાવધાન",
        "or": "{name}ର କଡ଼ରେ ଅଛନ୍ତି — ସଂରକ୍ଷିତ କ୍ଷେତ୍ର, ସାବଧାନ",
        "ta": "{name} விளிம்பில் உள்ளீர்கள் — பாதுகாக்கப்பட்ட பகுதி, கவனம்",
        "te": "{name} అంచున ఉన్నారు — రక్షిత ప్రాంతం, జాగ్రత్త",
        "ml": "{name} അതിരിലാണ് — സംരക്ഷിത മേഖല, ശ്രദ്ധിക്കുക",
        "en": "you are at the edge of {name} — a protected area, take care",
    },
    "fence_near": {
        "bn": "আন্তর্জাতিক সীমানা {km} কিমি দূরে — {dir} দিকে ঘুরুন",
        "hi": "अंतरराष्ट्रीय सीमा {km} किमी दूर — {dir} की ओर मुड़ें",
        "mr": "आंतरराष्ट्रीय सीमा {km} किमी दूर — {dir} दिशेला वळा",
        "gu": "આંતરરાષ્ટ્રીય સીમા {km} કિમી દૂર — {dir} તરફ વળો",
        "or": "ଆନ୍ତର୍ଜାତିକ ସୀମା {km} କିମି ଦୂରରେ — {dir} ଦିଗକୁ ବୁଲନ୍ତୁ",
        "ta": "சர்வதேச கடல் எல்லை {km} கிமீ தொலைவில் — {dir} திசையில் திரும்பவும்",
        "te": "అంతర్జాతీయ సరిహద్దు {km} కిమీ దూరంలో — {dir} వైపు తిరగండి",
        "ml": "അന്താരാഷ്ട്ര അതിർത്തി {km} കിമീ അകലെ — {dir} ദിശയിലേക്ക് തിരിയുക",
        "en": "the international maritime boundary is {km} km away — turn {dir}",
    },
    "fence_clear": {
        "bn": "আন্তর্জাতিক সীমানা {km} কিমি দূরে, আপনি নিরাপদ দূরত্বে আছেন",
        "hi": "अंतरराष्ट्रीय सीमा {km} किमी दूर, आप सुरक्षित दूरी पर हैं",
        "mr": "आंतरराष्ट्रीय सीमा {km} किमी दूर, तुम्ही सुरक्षित अंतरावर आहात",
        "gu": "આંતરરાષ્ટ્રીય સીમા {km} કિમી દૂર, તમે સુરક્ષિત અંતરે છો",
        "or": "ଆନ୍ତର୍ଜାତିକ ସୀମା {km} କିମି ଦୂରରେ, ଆପଣ ନିରାପଦ ଦୂରତାରେ ଅଛନ୍ତି",
        "ta": "சர்வதேச கடல் எல்லை {km} கிமீ தொலைவில், நீங்கள் பாதுகாப்பான தூரத்தில் உள்ளீர்கள்",
        "te": "అంతర్జాతీయ సరిహద్దు {km} కిమీ దూరంలో, మీరు సురక్షిత దూరంలో ఉన్నారు",
        "ml": "അന്താരാഷ്ട്ര അതിർത്തി {km} കിമീ അകലെ, നിങ്ങൾ സുരക്ഷിത അകലത്തിലാണ്",
        "en": "the international maritime boundary is {km} km away — you are clear",
    },
}

# Verdict sentences. {when} is a time label, {why} the leading finding.
VERDICTS: dict[str, dict[str, str]] = {
    "go": {
        "bn": "{when} সমুদ্রে যাওয়া নিরাপদ। {why}।",
        "hi": "{when} समुद्र में जाना सुरक्षित है। {why}।",
        "mr": "{when} समुद्रात जाणे सुरक्षित आहे. {why}.",
        "gu": "{when} દરિયામાં જવું સલામત છે. {why}.",
        "or": "{when} ସମୁଦ୍ରକୁ ଯିବା ନିରାପଦ। {why}।",
        "ta": "{when} கடலுக்குச் செல்வது பாதுகாப்பானது. {why}.",
        "te": "{when} సముద్రంలోకి వెళ్లడం సురక్షితం. {why}.",
        "ml": "{when} കടലിൽ പോകുന്നത് സുരക്ഷിതമാണ്. {why}.",
        "en": "{when} it is safe to go out. {why}.",
    },
    "caution": {
        "bn": "{when} শুরুতে ঠিক আছে। {why} — তার আগে ফিরে আসুন।",
        "hi": "{when} शुरुआत में ठीक है। {why} — उससे पहले लौट आएं।",
        "mr": "{when} सुरुवातीला ठीक आहे. {why} — त्याआधी परत या.",
        "gu": "{when} શરૂઆતમાં ઠીક છે. {why} — તે પહેલાં પાછા આવો.",
        "or": "{when} ଆରମ୍ଭରେ ଠିକ ଅଛି। {why} — ତା ପୂର୍ବରୁ ଫେରି ଆସନ୍ତୁ।",
        "ta": "{when} ஆரம்பத்தில் பரவாயில்லை. {why} — அதற்கு முன் திரும்பி வாருங்கள்.",
        "te": "{when} మొదట్లో ఫర్వాలేదు. {why} — దానికి ముందే తిరిగి రండి.",
        "ml": "{when} തുടക്കത്തിൽ കുഴപ്പമില്ല. {why} — അതിനുമുൻപ് മടങ്ങുക.",
        "en": "{when} the early hours are fine. {why} — be back before then.",
    },
    "stay": {
        "bn": "{when} সমুদ্রে যাওয়া নিরাপদ নয়। {why}।",
        "hi": "{when} समुद्र में जाना सुरक्षित नहीं है। {why}।",
        "mr": "{when} समुद्रात जाणे सुरक्षित नाही. {why}.",
        "gu": "{when} દરિયામાં જવું સલામત નથી. {why}.",
        "or": "{when} ସମୁଦ୍ରକୁ ଯିବା ନିରାପଦ ନୁହେଁ। {why}।",
        "ta": "{when} கடலுக்குச் செல்வது பாதுகாப்பானது அல்ல. {why}.",
        "te": "{when} సముద్రంలోకి వెళ్లడం సురక్షితం కాదు. {why}.",
        "ml": "{when} കടലിൽ പോകുന്നത് സുരക്ഷിതമല്ല. {why}.",
        "en": "{when} it is not safe to go out. {why}.",
    },
}

# Shown when every source failed. A safety tool must never default to "safe".
NO_DATA: dict[str, str] = {
    "bn": "এখন কোনো তথ্য আনা যাচ্ছে না। তথ্য ছাড়া নিরাপদ বলা যায় না — বেরোনোর আগে আবার দেখুন।",
    "hi": "अभी कोई जानकारी नहीं मिल रही। जानकारी के बिना सुरक्षित नहीं कहा जा सकता — निकलने से पहले फिर देखें।",
    "mr": "सध्या माहिती मिळत नाही. माहितीशिवाय सुरक्षित म्हणता येणार नाही — निघण्यापूर्वी पुन्हा पहा.",
    "gu": "અત્યારે માહિતી મળી રહી નથી. માહિતી વિના સલામત કહી શકાય નહીં — નીકળતાં પહેલાં ફરી જુઓ.",
    "or": "ବର୍ତ୍ତମାନ କୌଣସି ତଥ୍ୟ ମିଳୁନାହିଁ। ତଥ୍ୟ ବିନା ନିରାପଦ କୁହାଯାଇପାରିବ ନାହିଁ — ବାହାରିବା ପୂର୍ବରୁ ପୁଣି ଦେଖନ୍ତୁ।",
    "ta": "இப்போது தகவல் கிடைக்கவில்லை. தகவல் இல்லாமல் பாதுகாப்பானது எனச் சொல்ல முடியாது — புறப்படும் முன் மீண்டும் பாருங்கள்.",
    "te": "ప్రస్తుతం సమాచారం రావడం లేదు. సమాచారం లేకుండా సురక్షితం అని చెప్పలేము — బయలుదేరే ముందు మళ్లీ చూడండి.",
    "ml": "ഇപ്പോൾ വിവരം ലഭിക്കുന്നില്ല. വിവരമില്ലാതെ സുരക്ഷിതമെന്ന് പറയാനാവില്ല — പുറപ്പെടും മുൻപ് വീണ്ടും നോക്കുക.",
    "en": "No data is reaching us right now. Without data we cannot call it safe — check again before you leave.",
}

# Appended when one or more sources did not answer.
PARTIAL: dict[str, str] = {
    "bn": "({agents}-এর তথ্য আসেনি, তাই এই উত্তর অসম্পূর্ণ।)",
    "hi": "({agents} की जानकारी नहीं मिली, इसलिए यह उत्तर अधूरा है।)",
    "mr": "({agents} ची माहिती मिळाली नाही, त्यामुळे हे उत्तर अपूर्ण आहे.)",
    "gu": "({agents} ની માહિતી મળી નથી, તેથી આ જવાબ અધૂરો છે.)",
    "or": "({agents}ର ତଥ୍ୟ ମିଳିଲା ନାହିଁ, ତେଣୁ ଏହି ଉତ୍ତର ଅସମ୍ପୂର୍ଣ୍ଣ।)",
    "ta": "({agents} தகவல் கிடைக்கவில்லை, எனவே இந்த பதில் முழுமையானது அல்ல.)",
    "te": "({agents} సమాచారం రాలేదు, కాబట్టి ఈ సమాధానం అసంపూర్ణం.)",
    "ml": "({agents} വിവരം ലഭിച്ചില്ല, അതിനാൽ ഈ ഉത്തരം അപൂർണ്ണമാണ്.)",
    "en": "({agents} data did not arrive, so this answer is incomplete.)",
}

# When the sources that came back look fine but one is missing, we cannot say
# "safe" — the sentence has to match the badge, or the user learns to distrust
# both.
UNCONFIRMED: dict[str, str] = {
    "bn": "{agents}-এর তথ্য ছাড়া নিরাপদ বলা যাচ্ছে না। যতটুকু পাওয়া গেছে: {why}।",
    "hi": "{agents} की जानकारी के बिना सुरक्षित नहीं कहा जा सकता। जो मिला: {why}।",
    "mr": "{agents} च्या माहितीशिवाय सुरक्षित म्हणता येणार नाही. जे मिळाले: {why}.",
    "gu": "{agents} ની માહિતી વિના સલામત કહી શકાય નહીં. જે મળ્યું: {why}.",
    "or": "{agents}ର ତଥ୍ୟ ବିନା ନିରାପଦ କୁହାଯାଇପାରିବ ନାହିଁ। ଯାହା ମିଳିଲା: {why}।",
    "ta": "{agents} தகவல் இல்லாமல் பாதுகாப்பானது எனச் சொல்ல முடியாது. கிடைத்தது: {why}.",
    "te": "{agents} సమాచారం లేకుండా సురక్షితం అని చెప్పలేము. దొరికినది: {why}.",
    "ml": "{agents} വിവരമില്ലാതെ സുരക്ഷിതമെന്ന് പറയാനാവില്ല. ലഭിച്ചത്: {why}.",
    "en": "Without {agents} data we cannot call it safe. What we do have: {why}.",
}

# Chlorophyll productivity bands, in words the user actually uses.
CHL_BAND: dict[str, dict[str, str]] = {
    "very low":  {"bn": "খুব কম", "hi": "बहुत कम", "mr": "फार कमी", "gu": "ખૂબ ઓછું",
                  "or": "ବହୁତ କମ", "ta": "மிகக் குறைவு", "te": "చాలా తక్కువ",
                  "ml": "വളരെ കുറവ്", "en": "very low"},
    "low":       {"bn": "কম", "hi": "कम", "mr": "कमी", "gu": "ઓછું", "or": "କମ",
                  "ta": "குறைவு", "te": "తక్కువ", "ml": "കുറവ്", "en": "low"},
    "moderate":  {"bn": "মাঝারি", "hi": "मध्यम", "mr": "मध्यम", "gu": "મધ્યમ",
                  "or": "ମଧ୍ୟମ", "ta": "மிதமான", "te": "మధ్యస్థం", "ml": "മിതമായ",
                  "en": "moderate"},
    "high":      {"bn": "বেশি", "hi": "अधिक", "mr": "जास्त", "gu": "વધુ", "or": "ଅଧିକ",
                  "ta": "அதிகம்", "te": "ఎక్కువ", "ml": "കൂടുതൽ", "en": "high"},
    "very high": {"bn": "খুব বেশি", "hi": "बहुत अधिक", "mr": "खूप जास्त",
                  "gu": "ખૂબ વધુ", "or": "ବହୁତ ଅଧିକ", "ta": "மிக அதிகம்",
                  "te": "చాలా ఎక్కువ", "ml": "വളരെ കൂടുതൽ", "en": "very high"},
}


def chl_band(band: str, lang: str) -> str:
    return CHL_BAND.get(band, {}).get(lang) or band


# How confident a fishing-zone estimate is, in words.
PFZ_STRENGTH: dict[str, dict[str, str]] = {
    "strong":   {"bn": "ভালো", "hi": "अच्छी", "mr": "चांगली", "gu": "સારી",
                 "or": "ଭଲ", "ta": "நல்ல", "te": "మంచి", "ml": "നല്ല",
                 "en": "good"},
    "moderate": {"bn": "মাঝারি", "hi": "मध्यम", "mr": "मध्यम", "gu": "મધ્યમ",
                 "or": "ମଧ୍ୟମ", "ta": "மிதமான", "te": "మధ్యస్థం", "ml": "മിതമായ",
                 "en": "moderate"},
    "weak":     {"bn": "কম", "hi": "कम", "mr": "कमी", "gu": "ઓછી", "or": "କମ",
                 "ta": "குறைவு", "te": "తక్కువ", "ml": "കുറവ്", "en": "weak"},
}


def pfz_strength(level: str, lang: str) -> str:
    return PFZ_STRENGTH.get(level, {}).get(lang) or level


# Short agent names for use inside a sentence. The caveat read
# "(Ocean, Weather, Ocean Analytics-এর তথ্য আসেনি…)" — an English list dropped
# into a Bengali sentence, which is the one place a user actually reads an
# agent name rather than glancing at it in the panel.
AGENT_SHORT: dict[str, dict[str, str]] = {
    "Ocean":           {"bn": "ঢেউ", "hi": "लहरें", "mr": "लाटा", "gu": "મોજાં",
                        "or": "ଢେଉ", "ta": "அலைகள்", "te": "అలలు",
                        "ml": "തിരമാലകൾ", "en": "wave"},
    "Weather":         {"bn": "আবহাওয়া", "hi": "मौसम", "mr": "हवामान",
                        "gu": "હવામાન", "or": "ପାଗ", "ta": "வானிலை",
                        "te": "వాతావరణం", "ml": "കാലാവസ്ഥ", "en": "weather"},
    "Ocean Analytics": {"bn": "সমুদ্র বিশ্লেষণ", "hi": "समुद्र विश्लेषण",
                        "mr": "समुद्र विश्लेषण", "gu": "દરિયા વિશ્લેષણ",
                        "or": "ସମୁଦ୍ର ବିଶ୍ଳେଷଣ", "ta": "கடல் பகுப்பாய்வு",
                        "te": "సముద్ర విశ్లేషణ", "ml": "കടൽ വിശകലനം",
                        "en": "ocean analytics"},
    "PFZ":             {"bn": "মাছের এলাকা", "hi": "मछली क्षेत्र",
                        "mr": "मासेक्षेत्र", "gu": "માછલી વિસ્તાર",
                        "or": "ମାଛ କ୍ଷେତ୍ର", "ta": "மீன்பிடி பகுதி",
                        "te": "చేపల ప్రాంతం", "ml": "മത്സ്യമേഖല",
                        "en": "fishing zones"},
    "Geospatial":      {"bn": "সীমানা", "hi": "सीमा", "mr": "सीमा", "gu": "સીમા",
                        "or": "ସୀମା", "ta": "எல்லை", "te": "సరిహద్దు",
                        "ml": "അതിർത്തി", "en": "boundary"},
}


def agent_short(name: str, lang: str) -> str:
    return AGENT_SHORT.get(name, {}).get(lang) or name


# Tide, in the words a fisherman uses. Never a height: the model is 8 km and
# referenced to mean sea level rather than chart datum, so a figure would be
# unusable next to a real depth.
TIDE_STATE: dict[str, dict[str, str]] = {
    "rising":  {"bn": "বাড়ছে", "hi": "बढ़ रहा है", "mr": "वाढत आहे",
                "gu": "વધી રહી છે", "or": "ବଢ଼ୁଛି", "ta": "உயர்ந்து வருகிறது",
                "te": "పెరుగుతోంది", "ml": "ഉയരുന്നു", "en": "rising"},
    "falling": {"bn": "কমছে", "hi": "घट रहा है", "mr": "ओसरत आहे",
                "gu": "ઘટી રહી છે", "or": "କମୁଛି", "ta": "இறங்குகிறது",
                "te": "తగ్గుతోంది", "ml": "താഴുന്നു", "en": "falling"},
    "slack":   {"bn": "স্থির", "hi": "स्थिर", "mr": "स्थिर", "gu": "સ્થિર",
                "or": "ସ୍ଥିର", "ta": "நிலையாக", "te": "స్థిరంగా",
                "ml": "സ്ഥിരം", "en": "slack"},
}

TIDE_TURN: dict[str, dict[str, str]] = {
    "high": {"bn": "পূর্ণ জোয়ার", "hi": "पूर्ण ज्वार", "mr": "पूर्ण भरती",
             "gu": "પૂર્ણ ભરતી", "or": "ପୂର୍ଣ୍ଣ ଜୁଆର", "ta": "உச்ச அலை",
             "te": "పూర్ణ ఆటు", "ml": "ഉയർന്ന വേലി", "en": "high water"},
    "low":  {"bn": "পূর্ণ ভাটা", "hi": "पूर्ण भाटा", "mr": "पूर्ण ओहोटी",
             "gu": "પૂર્ણ ઓટ", "or": "ପୂର୍ଣ୍ଣ ଭଟା", "ta": "தாழ் அலை",
             "te": "పూర్ణ పోటు", "ml": "താഴ്ന്ന വേലി", "en": "low water"},
}


def tide_state(state: str, lang: str) -> str:
    return TIDE_STATE.get(state, {}).get(lang) or state


def tide_turn(turn: str, lang: str) -> str:
    return TIDE_TURN.get(turn, {}).get(lang) or turn


# Why an area is closed. Only one so far, but the shape is here for the rest.
CLOSURE_REASON: dict[str, dict[str, str]] = {
    "turtle_nesting": {
        "bn": "কচ্ছপের ডিম পাড়ার মরসুম", "hi": "कछुओं का प्रजनन काल",
        "mr": "कासवांचा प्रजनन काळ", "gu": "કાચબાની પ્રજનન ઋતુ",
        "or": "କଚ୍ଛପ ଅଣ୍ଡା ଦେବା ଋତୁ", "ta": "ஆமை முட்டையிடும் காலம்",
        "te": "తాబేళ్ల గుడ్లు పెట్టే కాలం", "ml": "ആമ മുട്ടയിടുന്ന കാലം",
        "en": "turtle nesting season",
    },
}


def closure_reason(key: str, lang: str) -> str:
    return CLOSURE_REASON.get(key, {}).get(lang) or key


# What a follow-up inherited from the question before it. These appear on
# screen — "↳ আগের প্রশ্ন থেকে ধরে রাখা: time, intent" was showing raw keys in
# English inside a Bengali sentence.
CARRIED: dict[str, dict[str, str]] = {
    "time":   {"bn": "সময়", "hi": "समय", "mr": "वेळ", "gu": "સમય", "or": "ସମୟ",
               "ta": "நேரம்", "te": "సమయం", "ml": "സമയം", "en": "time"},
    "boat":   {"bn": "নৌকা", "hi": "नाव", "mr": "नाव", "gu": "હોડી", "or": "ଡଙ୍ଗା",
               "ta": "படகு", "te": "పడవ", "ml": "വള്ളം", "en": "boat"},
    "intent": {"bn": "প্রশ্নের ধরন", "hi": "सवाल का प्रकार", "mr": "प्रश्नाचा प्रकार",
               "gu": "પ્રશ્નનો પ્રકાર", "or": "ପ୍ରଶ୍ନର ପ୍ରକାର", "ta": "கேள்வி வகை",
               "te": "ప్రశ్న రకం", "ml": "ചോദ്യ തരം", "en": "topic"},
    "time_switched_to_safety": {
        "bn": "সময় বদলেছে, তাই নিরাপত্তার হিসেব",
        "hi": "समय बदला, इसलिए सुरक्षा की गणना",
        "mr": "वेळ बदलली, म्हणून सुरक्षेची गणना",
        "gu": "સમય બદલાયો, તેથી સલામતીની ગણતરી",
        "or": "ସମୟ ବଦଳିଛି, ତେଣୁ ନିରାପତ୍ତା ହିସାବ",
        "ta": "நேரம் மாறியது, எனவே பாதுகாப்புக் கணக்கு",
        "te": "సమయం మారింది, కాబట్టి భద్రతా లెక్క",
        "ml": "സമയം മാറി, അതിനാൽ സുരക്ഷാ കണക്ക്",
        "en": "time changed, so this is the safety answer",
    },
    "boat_switched_to_safety": {
        "bn": "নৌকা বদলেছে, তাই নিরাপত্তার হিসেব",
        "hi": "नाव बदली, इसलिए सुरक्षा की गणना",
        "mr": "नाव बदलली, म्हणून सुरक्षेची गणना",
        "gu": "હોડી બદલાઈ, તેથી સલામતીની ગણતરી",
        "or": "ଡଙ୍ଗା ବଦଳିଛି, ତେଣୁ ନିରାପତ୍ତା ହିସାବ",
        "ta": "படகு மாறியது, எனவே பாதுகாப்புக் கணக்கு",
        "te": "పడవ మారింది, కాబట్టి భద్రతా లెక్క",
        "ml": "വള്ളം മാറി, അതിനാൽ സുരക്ഷാ കണക്ക്",
        "en": "boat changed, so this is the safety answer",
    },
}


def carried_label(key: str, lang: str) -> str:
    return CARRIED.get(key, {}).get(lang) or key


# Time labels
WHEN: dict[str, dict[str, str]] = {
    "today":    {"bn": "আজ", "hi": "आज", "mr": "आज", "gu": "આજે", "or": "ଆଜି",
                 "ta": "இன்று", "te": "ఈరోజు", "ml": "ഇന്ന്", "en": "Today"},
    "tomorrow": {"bn": "কাল সকালে", "hi": "कल सुबह", "mr": "उद्या सकाळी",
                 "gu": "કાલે સવારે", "or": "କାଲି ସକାଳେ", "ta": "நாளை காலை",
                 "te": "రేపు ఉదయం", "ml": "നാളെ രാവിലെ", "en": "Tomorrow morning"},
    "dayafter": {"bn": "পরশু", "hi": "परसों", "mr": "परवा", "gu": "પરમ દિવસે",
                 "or": "ପରଦିନ", "ta": "நாளை மறுநாள்", "te": "ఎల్లుండి",
                 "ml": "മറ്റന്നാൾ", "en": "The day after tomorrow"},
    "now":      {"bn": "এখন", "hi": "अभी", "mr": "आत्ता", "gu": "અત્યારે",
                 "or": "ବର୍ତ୍ତମାନ", "ta": "இப்போது", "te": "ఇప్పుడు",
                 "ml": "ഇപ്പോൾ", "en": "Right now"},
}

# Eight-point compass
COMPASS: dict[str, list[str]] = {
    "bn": ["উত্তর", "উত্তর-পূর্ব", "পূর্ব", "দক্ষিণ-পূর্ব", "দক্ষিণ",
           "দক্ষিণ-পশ্চিম", "পশ্চিম", "উত্তর-পশ্চিম"],
    "hi": ["उत्तर", "उत्तर-पूर्व", "पूर्व", "दक्षिण-पूर्व", "दक्षिण",
           "दक्षिण-पश्चिम", "पश्चिम", "उत्तर-पश्चिम"],
    "mr": ["उत्तर", "ईशान्य", "पूर्व", "आग्नेय", "दक्षिण",
           "नैऋत्य", "पश्चिम", "वायव्य"],
    "gu": ["ઉત્તર", "ઉત્તર-પૂર્વ", "પૂર્વ", "દક્ષિણ-પૂર્વ", "દક્ષિણ",
           "દક્ષિણ-પશ્ચિમ", "પશ્ચિમ", "ઉત્તર-પશ્ચિમ"],
    "or": ["ଉତ୍ତର", "ଉତ୍ତର-ପୂର୍ବ", "ପୂର୍ବ", "ଦକ୍ଷିଣ-ପୂର୍ବ", "ଦକ୍ଷିଣ",
           "ଦକ୍ଷିଣ-ପଶ୍ଚିମ", "ପଶ୍ଚିମ", "ଉତ୍ତର-ପଶ୍ଚିମ"],
    "ta": ["வடக்கு", "வடகிழக்கு", "கிழக்கு", "தென்கிழக்கு", "தெற்கு",
           "தென்மேற்கு", "மேற்கு", "வடமேற்கு"],
    "te": ["ఉత్తరం", "ఈశాన్యం", "తూర్పు", "ఆగ్నేయం", "దక్షిణం",
           "నైరుతి", "పడమర", "వాయవ్యం"],
    "ml": ["വടക്ക്", "വടക്കുകിഴക്ക്", "കിഴക്ക്", "തെക്കുകിഴക്ക്", "തെക്ക്",
           "തെക്കുപടിഞ്ഞാറ്", "പടിഞ്ഞാറ്", "വടക്കുപടിഞ്ഞാറ്"],
    "en": ["north", "north-east", "east", "south-east", "south",
           "south-west", "west", "north-west"],
}


def compass(deg: float, lang: str) -> str:
    """A heading in degrees is useless to someone steering by eye."""
    names = COMPASS.get(lang, COMPASS["en"])
    return names[int((deg + 22.5) % 360 // 45)]


def render(phrase: Phrase, lang: str) -> str:
    """Turn a fact into a sentence. Falls back to English if a pack is missing."""
    pack = PHRASES.get(phrase.kind, {})
    template = pack.get(lang) or pack.get("en") or phrase.kind

    values = {}
    data = dict(phrase.data)
    if "strength" in data:
        data["strength"] = pfz_strength(str(data["strength"]), lang)
    if "state" in data:
        data["state"] = tide_state(str(data["state"]), lang)
    if "turns" in data:
        data["turns"] = tide_turn(str(data["turns"]), lang)
    if "reason" in data:
        data["reason"] = closure_reason(str(data["reason"]), lang)
    if "band" in data:
        data["band"] = chl_band(str(data["band"]), lang)
    if "hour24" in data:
        data["part"] = period(int(data.pop("hour24")), lang)

    for k, v in data.items():
        if k == "part":
            values[k] = v
        elif k == "dir":
            values[k] = compass(v, lang)
        elif isinstance(v, (int, float)) or (
            isinstance(v, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", v)
        ):
            values[k] = num(v, lang)
        else:
            values[k] = v
    return template.format(**values)


def verdict_line(verdict: str, when_key: str, why: str, lang: str) -> str:
    pack = VERDICTS[verdict]
    when = WHEN.get(when_key, WHEN["today"]).get(lang, WHEN["today"]["en"])
    return (pack.get(lang) or pack["en"]).format(when=when, why=why)
