"""Pre-flight checks. Run before packaging anything.

Three classes of bug reached the user today that none of the earlier checks
caught:

  1. An edit whose search text had drifted, so the replace did nothing and the
     mismatch only appeared as a TypeError at runtime.
  2. A missing import inside a source body — `timedelta` in ChlorophyllSource —
     which survived every test because every test stubbed the sources out.
     Stubbing the thing you are verifying verifies nothing.
  3. Silent failures that produced no error at all, only an absent finding.

    python verify.py
"""
import ast, asyncio, pathlib, subprocess, sys

import httpx

FAILURES = []


def report(title, problems):
    print(title)
    if problems:
        print("\n".join(f"    {p}" for p in problems))
        FAILURES.extend(problems)
    else:
        print("    clean")
    print()


# --------------------------------------------------- 1. call signatures
def check_signatures():
    funcs, calls = {}, []
    for path in sorted(pathlib.Path("app").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            # dataclasses generate their __init__, so record their fields as
            # the positional signature — otherwise a field inserted in the
            # middle silently reshuffles every positional call site
            if isinstance(node, ast.ClassDef) and any(
                    (isinstance(d, ast.Name) and d.id == "dataclass") or
                    (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                     and d.func.id == "dataclass")
                    for d in node.decorator_list):
                fields = [n.target.id for n in node.body
                          if isinstance(n, ast.AnnAssign)
                          and isinstance(n.target, ast.Name)]
                withdefault = sum(1 for n in node.body
                                  if isinstance(n, ast.AnnAssign) and n.value is not None)
                funcs[node.name] = {
                    "pos": fields, "defaults": withdefault, "kwonly": [],
                    "vararg": False, "kwarg": False,
                    "where": f"{path.name}:{node.lineno}",
                }
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                funcs[node.name] = {
                    "pos": [x.arg for x in a.args if x.arg not in ("self", "cls")],
                    "defaults": len(a.defaults),
                    "kwonly": [x.arg for x in a.kwonlyargs],
                    "vararg": a.vararg is not None,
                    "kwarg": a.kwarg is not None,
                    "where": f"{path.name}:{node.lineno}",
                }
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.append((path.name, node.lineno, node.func.id,
                              len(node.args),
                              [k.arg for k in node.keywords if k.arg]))

    problems = []
    for file, line, name, npos, kws in calls:
        f = funcs.get(name)
        if not f:
            continue
        allowed = set(f["pos"]) | set(f["kwonly"])
        for k in kws:
            if k not in allowed and not f["kwarg"]:
                problems.append(f"{file}:{line}  {name}(..., {k}=...) — defined at "
                                f"{f['where']} as ({', '.join(f['pos'])})")
        if not f["vararg"] and npos > len(f["pos"]):
            problems.append(f"{file}:{line}  {name}() given {npos} positional, "
                            f"takes {len(f['pos'])}")
    report(f"1. call signatures  ({len(calls)} sites, {len(funcs)} definitions)",
           problems)


# --------------------------------------------------- 2. undefined names
def check_names():
    try:
        out = subprocess.run([sys.executable, "-m", "pyflakes", "app"],
                             capture_output=True, text=True).stdout
    except Exception:
        report("2. undefined names", ["pyflakes not installed — pip install pyflakes"])
        return
    # Everything pyflakes says is worth reading. It caught a dictionary key
    # repeated in every one of nine language blocks — Python keeps the last
    # value silently, and nothing else would have noticed.
    bad = [l for l in out.splitlines() if l.strip()]
    report("2. what pyflakes sees", bad)


# --------------------------------------------------- 3. run every source body
CHL = {"table": {"columnNames": ["time", "altitude", "latitude", "longitude", "chlor_a"],
                 "rows": [["2026-08-29T12:00:00Z", 0.0, 21.5, 87.8, 1.85],
                          ["2026-08-29T12:00:00Z", 0.0, 21.6, 87.9, 2.10],
                          ["2026-08-29T12:00:00Z", 0.0, 21.7, 88.0, 2.40]]}}
MARINE = {"hourly": {"time": ["2026-08-30T00:00", "2026-08-30T01:00"],
                     "wave_height": [1.2, 1.3], "wave_period": [6.0, 6.1],
                     "wave_direction": [190, 191], "swell_wave_height": [0.8, 0.9],
                     "sea_surface_temperature": [28.4, 28.5],
                     "ocean_current_velocity": [1.6, 1.7],
                     "ocean_current_direction": [225, 226]}}
WX = {"hourly": {"time": ["2026-08-30T00:00", "2026-08-30T01:00"],
                 "wind_speed_10m": [10, 11], "wind_gusts_10m": [15, 16],
                 "wind_direction_10m": [200, 201], "precipitation": [0, 0],
                 "cape": [200, 250], "visibility": [9000, 9000]}}


def handler(request):
    u = str(request.url)
    if "erddap" in u:
        return httpx.Response(200, json=CHL)
    if "marine-api" in u:
        return httpx.Response(200, json=MARINE)
    if "api.open-meteo.com" in u:
        return httpx.Response(200, json=WX)
    if "seabulletin" in u:
        return httpx.Response(200, json=[{"area": "North West Bay",
                                          "sea": "Moderate", "wind": "20-25 kts"}])
    if "districtnowcast" in u:
        return httpx.Response(200, json=[{"Category": "11"}])
    return httpx.Response(404)


async def _sources():
    sys.path.insert(0, ".")
    from app import sources
    import app.imd as imd
    imd.IMD.key = "test-key"

    every = [("OpenMeteoOcean", sources.OpenMeteoOcean()),
             ("OpenMeteoOceanography", sources.OpenMeteoOceanography()),
             ("OpenMeteoWeather", sources.OpenMeteoWeather()),
             ("ChlorophyllSource", sources.ChlorophyllSource()),
             ("ImdWeather", sources.ImdWeather()),
             ("ImdOcean", sources.ImdOcean())]

    problems, passed = [], []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        for name, src in every:
            try:
                r = await src.fetch(c, 21.6, 87.6, days=1)
                passed.append(f"{name} → {len(r.hours)}h")
            except NotImplementedError:
                passed.append(f"{name} (not implemented, by design)")
            except Exception as e:
                problems.append(f"{name}: {type(e).__name__}: {e}")
    return problems, passed


def check_sources():
    problems, passed = asyncio.run(_sources())
    report(f"3. source bodies executed  ({len(passed)} ran)", problems)


# --------------------------------------------------- 4. every chip routes right
FISH = ("fish", "মাছ", "मछली", "मासे", "માછલી", "ମାଛ", "மீன்", "చేప", "മീൻ")
BOUND = ("boundary", "সীমা", "सीमा", "સીમા", "ସୀମା", "எல்லை", "సరిహద్దు", "അതിർത്തി")


def check_routing():
    """Every suggested question must reach the agent it implies.

    The Marathi and Malayalam words for fish were missing from the planner's
    vocabulary, so a fishing question in those two languages quietly became a
    safety question — a wrong answer with no error anywhere. Nothing but this
    check would have found it.
    """
    sys.path.insert(0, ".")
    from app import agents, ui_strings
    from app.session import Resolved

    problems = []
    checked = 0
    for code, pack in ui_strings.UI.items():
        for kind in ("starters", "follow"):
            for q in pack[kind]:
                checked += 1
                task = agents.plan(Resolved(question=q, when_key="today",
                                            intent="", boat_length_m=9.0,
                                            inherited=False))
                want = ("fishing" if any(w in q for w in FISH)
                        else "boundary" if any(w in q for w in BOUND)
                        else "safety")
                if task.intent != want:
                    problems.append(f"{code} {kind}: {q!r} routed to "
                                    f"{task.intent}, expected {want}")
    report(f"4. suggested questions routed  ({checked} chips)", problems)


# --------------------------------------------------- 5. behaviour that matters
def check_behaviour():
    """Rules the project must not silently lose.

    Each of these was either a bug that reached the user, or a decision made
    deliberately that a later edit could quietly undo.
    """
    sys.path.insert(0, ".")
    from app import agents, geofence, lang, ports, session as sess
    from app.chlorophyll import band_for, _valid

    problems = []

    def want(name, cond):
        if not cond:
            problems.append(name)

    # boat classification decides the wave limit, so its edges matter
    want("9 m boat is small", agents.classify_boat(9.0) == "small")
    want("15 m boat is medium", agents.classify_boat(15.0) == "medium")
    want("16 m boat is a trawler", agents.classify_boat(16.0) == "trawler")

    # an unseen pixel must never become a measurement
    want("NaN is not a pixel", not _valid(float("nan")))
    want("zero is not a pixel", not _valid(0.0))
    want("out-of-range is not a pixel", not _valid(2000.0))

    # a bearing has to survive the wrap at north
    want("compass wraps at north", lang.compass(0, "en") == lang.compass(360, "en"))
    for deg, name in ((0, "north"), (90, "east"), (180, "south"), (270, "west")):
        want(f"compass {deg} is {name}", lang.compass(deg, "en") == name)

    # 4 a.m. and 4 p.m. must not read the same to someone deciding to launch
    want("04:00 is night", lang.period(4, "en") == "night")
    want("16:00 is afternoon", lang.period(16, "en") == "afternoon")

    # chlorophyll bands drive the wording, so their edges matter too
    want("0.1 is low", band_for(0.1) == "low")
    want("3.0 is very high", band_for(3.0) == "very high")

    # sampling must move away from the shore, never towards it
    for p in ports.PORTS:
        la, lo = ports.seaward(p)
        if p.coast == "east":
            want(f"{p.id} samples eastward", lo > p.lon)
        elif p.coast == "west":
            want(f"{p.id} samples westward", lo < p.lon)

    # the length in the boat field must stick, or the page fills the field back
    # in from a stale session and shows 18 m beside a limit worked out for 9
    probe = sess.get("_check_field")
    sess.resolve(probe, "আজ যাওয়া নিরাপদ?", boat_override=18.0)
    want("an overridden boat length is remembered", probe.boat_length_m == 18.0)

    # one user's boat must never become another's
    a, b = sess.get("_check_a"), sess.get("_check_b")
    a.boat_length_m = 9.0
    sess.resolve(b, "boat is 25 m")
    want("sessions do not share boat length", a.boat_length_m == 9.0)

    # turning away from a boundary means turning away from it
    g = geofence.check(21.40, 89.02)
    want("turn heading is opposite the line",
         abs(((g.bearing_to_line_deg + 180) % 360) - g.turn_to_deg) < 1.5)

    report("5. behaviour that matters", problems)


# --------------------------------------------------- 5b. panel vocabulary
def check_vocabulary():
    """Every word the backend asks the panel to translate must exist, in every
    language.

    A word key that is missing simply prints itself, so the panel comes out
    half English and nothing errors. That is how "ocean" and "analytics" sat
    untranslated in the planner line.
    """
    import re
    sys.path.insert(0, ".")
    from app import lang, panel_strings

    # strip comments: the docstring shows {"w": "key"} as an example, and a
    # naive scan reads that as a real word to translate
    src = "\n".join(
        line.split("#", 1)[0] if line.strip().startswith("#") else line
        for line in pathlib.Path("app/agents.py").read_text().split("\n"))
    asked = set(re.findall(r'\{"w":\s*"([a-z_]+)"', src))
    asked |= set(re.findall(r'"w":\s*"([a-z_]+)"\}', src))
    # keys built from a variable rather than a literal
    # the three intents plan() can actually produce
    asked |= {"safety", "fishing", "boundary"}
    asked |= {"today", "tomorrow", "dayafter", "now"}                 # windows
    asked |= {"go", "caution", "stay", "unknown"}                     # verdicts
    asked |= {"clear", "warn", "urgent"}                              # fence levels
    asked |= {"sea_state", "oceanography", "chlorophyll", "weather_cap"}
    # the workers the planner lists — these came from a variable, so the scan
    # above never saw them and they sat in English while everything around them
    # turned
    asked |= {"ocean", "analytics", "pfz", "geofence"}
    # both forms, because the code picks between them by count
    asked |= {"zone", "zones", "finding", "findings"}

    problems = []
    for code in lang.LANG_NAMES:
        have = set(panel_strings.words(code))
        for missing in sorted(asked - have):
            problems.append(f"{code}: no word for '{missing}'")

    report(f"5b. panel vocabulary  ({len(asked)} keys)", problems)


# --------------------------------------------------- 6. the interface itself
def check_interface():
    """The page has to be internally consistent.

    A careless edit once deleted half the script — every handler, the renderer,
    the language loader — and the file still parsed as valid JavaScript. Nothing
    in the Python checks would ever have noticed.
    """
    import re
    from html.parser import HTMLParser

    path = pathlib.Path("static/index.html")
    html = path.read_text()
    js = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)

    problems = []

    for name in ("loadLang", "resetView", "buildPorts", "render",
                 "renderTrace", "ask"):
        if f"function {name}" not in js:
            problems.append(f"{name}() is missing from the page")
    if "loadLang('bn')" not in js:
        problems.append("the page never boots — no initial loadLang call")

    # every element the script reaches for must exist in the markup
    used = set(re.findall(r"\$\('#([\w-]+)'\)", js))
    used |= set(re.findall(r"getElementById\('([\w-]+)'\)", js))
    for missing in sorted(used - set(re.findall(r'id="([\w-]+)"', html))):
        problems.append(f"script uses #{missing}, which is not in the markup")

    # every class the script emits must be styled
    emitted = set()
    for m in re.findall(r'class="([^"$]*)\$?', js):
        emitted.update(m.split())
    defined = set(re.findall(r"\.([a-z][\w-]*)\s*[{,]", css))
    for c in sorted(emitted - defined):
        if c:
            problems.append(f"class .{c} is emitted but never styled")

    # The field can be in feet, so every send must convert. A raw read would
    # put "30" on the wire as thirty metres — a trawler's limit applied to a
    # nine-metre open boat.
    for m in re.finditer(r"boat_length_m:\s*([^,\n]+)", js):
        if "boatMetres" not in m.group(1):
            problems.append(f"a boat length is sent unconverted: {m.group(1).strip()[:40]}")
    for line in js.split("\n"):
        if "$('#boat').value" in line and "UNIT" not in line and "Number" not in line:
            problems.append("the boat field is read outside the conversion helpers")

    # the last answer is session memory, not a store: a week-old forecast
    # surviving in a browser would be worse than none at all
    if re.search(r"\b(localStorage|sessionStorage)\.", js):
        problems.append("browser storage is used — a stale forecast must not "
                        "outlive the session")
    if "LAST = {d, at:" not in js or "if(!showStale())" not in js:
        problems.append("no last-answer fallback — a boat with no signal gets "
                        "a blank screen at the moment it matters most")

    # voice output was removed on purpose; it must not creep back
    for gone in ("speechSynthesis", "SpeechSynthesisUtterance"):
        if gone in js:
            problems.append(f"{gone} is back — voice output was removed by choice")

    class Nest(HTMLParser):
        def __init__(self):
            super().__init__(); self.stack = []; self.bad = []
        def handle_starttag(self, tag, attrs):
            if tag not in ("br", "img", "input", "meta", "link", "hr"):
                self.stack.append(tag)
        def handle_endtag(self, tag):
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            elif tag in self.stack:
                self.bad.append(f"</{tag}> closes <{self.stack[-1]}>")
                while self.stack and self.stack.pop() != tag:
                    pass

    n = Nest(); n.feed(html)
    problems.extend(n.bad)
    if n.stack:
        problems.append(f"unclosed tags: {n.stack}")

    report("6. the interface itself", problems)


# --------------------------------------------------- 7. nothing defined twice
def check_duplicates():
    """A name defined twice at module level is a silent overwrite.

    A second WORDS block was appended to panel_strings.py and shadowed the
    first. Both halves looked correct in isolation; only the second one existed
    at run time, and the mismatch surfaced as a KeyError far from the cause.
    """
    import collections

    problems = []
    for path in sorted(pathlib.Path("app").glob("*.py")):
        tree = ast.parse(path.read_text())
        seen = collections.Counter()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seen[node.name] += 1
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                seen[node.target.id] += 1
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        seen[t.id] += 1
        for name, count in seen.items():
            if count > 1:
                problems.append(f"{path.name}: {name} defined {count} times")

        # A field declared twice in a dataclass is legal Python and silently
        # keeps the last one. This has now happened twice while adding fields
        # to WeatherHour and OceanographyHour, and neither the compiler nor the
        # top-level scan above noticed.
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            fields = [n.target.id for n in node.body
                      if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
            for f in {x for x in fields if fields.count(x) > 1}:
                problems.append(f"{path.name}: {node.name}.{f} declared "
                                f"{fields.count(f)} times")
    report("7. nothing defined twice", problems)


# --------------------------------------------------- 8. nothing left in English
def check_translation():
    """No English should survive into a non-English screen.

    Key coverage is not the same as a translated screen. "ocean · analytics ·
    pfz" and "(Ocean, Weather, Ocean Analytics-এর তথ্য আসেনি)" both passed a key
    check and both read as English inside another language. This renders the
    strings and looks at them.

    Product names and units are allowed through on purpose: translating
    "Open-Meteo wave model" would make a citation harder to check.
    """
    import re
    sys.path.insert(0, ".")
    from app import lang, panel_strings, ui_strings

    keep = re.compile(
        r"(Open-Meteo|NOAA|VIIRS|DINEOF|DWD|ECMWF|GFS|IMD|INCOIS|MODIS|Copernicus|"
        r"IMBL|India|Bangladesh|Sri|Lanka|Pakistan|Sir|Creek|CoastWatch|SST|"
        # OpenStreetMap must appear verbatim — its licence requires the
        # attribution to name the project, and a translated name would not
        r"OpenStreetMap|Leaflet|"
        r"km|px|mg|kn|m3|[-()\u00b7,./&:0-9\s])")

    problems = []
    for code in lang.LANG_NAMES:
        if code == "en":
            continue
        ui, panel = ui_strings.strings(code), panel_strings.panel(code)
        texts = [ui[k] for k in ("tagline", "hint", "mic", "because", "carried",
                                 "working", "failed", "none", "boat_label",
                                 "map_credit")]
        texts += [panel[k] for k in ("title", "subtitle", "idle", "parallel",
                                     "ms", "findings", "blocking", "unavailable")]
        texts += list(ui["verdict"].values()) + list(panel["verdict"].values())
        texts += ui["starters"] + ui["follow"]
        texts += [n for pair in panel["agents"].values() for n in pair]
        texts += list(panel_strings.words(code).values())
        texts += [lang.NO_DATA[code], lang.PARTIAL[code], lang.UNCONFIRMED[code]]
        texts += [v[code] for v in lang.AGENT_SHORT.values()]

        for t in texts:
            # {placeholders} are filled in at render time; the value that lands
            # in them is checked separately via AGENT_SHORT
            bare = re.sub(r"\{[a-z_]+\}", "", str(t))
            if re.search(r"[A-Za-z]{3,}", keep.sub("", bare)):
                problems.append(f"{code}: English left in {str(t)[:44]!r}")

    # A {"t": ...} part is printed exactly as it came, so anything routed
    # through one skips translation entirely. That is right for a product name
    # and wrong for our own vocabulary: "boat_switched_to_safety, time, intent"
    # reached a Bengali screen that way.
    import re as _re
    agent_src = pathlib.Path("app/agents.py").read_text()
    for m in _re.finditer(r'\{"t":\s*([^}]+)\}', agent_src):
        expr = m.group(1)
        if "resolved.carried" in expr or "task.intent" in expr \
                or "when_key" in expr:
            problems.append("a trace part prints our own vocabulary verbatim "
                            f"({expr.strip()[:40]}) — use {{'w': key}} so it "
                            "can be translated")

    report("8. nothing left in English", problems)


# --------------------------------------------------- 9. harbour names
def check_ports():
    """Every coast must read in its own language, and Hindi must be complete.

    In Hindi the picker was half Devanagari and half Latin, which looks like an
    unfinished feature. The rule now: Hindi carries all 48 because it is the
    link language and a Hindi reader could be on any coast; each other language
    carries its own coast, which is the only one a fisherman using it sails
    from. Latin for the rest is neutral and readable.
    """
    sys.path.insert(0, ".")
    from app import ports

    coast_language = {
        "West Bengal": "bn", "Odisha": "or", "Andhra Pradesh": "te",
        "Tamil Nadu": "ta", "Puducherry": "ta", "Kerala": "ml",
        "Maharashtra": "mr", "Goa": "mr", "Gujarat": "gu",
        "Lakshadweep": "ml",
        # Kannada and Konkani are not carried, and the Andamans have no single
        # local language, so those show English by design
        "Karnataka": None, "Andaman & Nicobar": None,
    }

    problems = []
    for p in ports.PORTS:
        if "en" not in p.names:
            problems.append(f"{p.id}: no English name to fall back to")
        # Hindi carries every coast because a Hindi reader could be on any of
        # them; Bengali carries every coast because it is the one language the
        # author can check line by line, and an unverifiable transliteration is
        # worse than plain English
        for full, why in (("hi", "Hindi carries all coasts"),
                          ("bn", "Bengali is the verified language")):
            if full not in p.names:
                problems.append(f"{p.id}: no {full} name ({why})")
        want = coast_language.get(p.state)
        if want and want not in p.names:
            problems.append(f"{p.id}: {p.state} should read in {want}")

    # the picker's group headings were the one untranslated thing left in it
    for state in {p.state for p in ports.PORTS}:
        for code in ("bn", "hi"):
            if ports.state_name(state, code) == state:
                problems.append(f"state {state!r} has no {code} name")

    report(f"9. harbour names  ({len(ports.PORTS)} ports)", problems)


def check_decline():
    """"Where are the fish" and "why are there fewer fish" are different.

    The first is about this morning and runs the fishing-zone estimate. The
    second is about a season and runs the year-on-year comparison. Both mention
    fish, and a planner that cannot tell them apart answers the wrong one — as
    it did for "why is the catch down?", which says catch and never says fish.
    """
    sys.path.insert(0, ".")
    from app import agents
    from app.session import Resolved

    problems = []
    cases = [
        ("কাছে মাছ কোথায়?", "fishing"),
        ("where are the fish?", "fishing"),
        ("মাছ কম পড়ছে কেন?", "decline"),
        ("why is the catch down?", "decline"),
        ("the catch has dropped", "decline"),
        ("மீன் ஏன் குறைந்தது?", "decline"),
        ("আজ সমুদ্র কেমন?", "safety"),
        ("সীমানা কত দূরে?", "boundary"),
    ]
    for question, want in cases:
        task = agents.plan(Resolved(question=question, when_key="today",
                                    intent="", boat_length_m=9.0,
                                    inherited=False))
        if task.intent != want:
            problems.append(f"{question!r} routed to {task.intent}, expected {want}")
        if want == "decline" and not task.needs_trends:
            problems.append(f"{question!r} is a decline question but runs no comparison")
        if want == "fishing" and not task.needs_pfz:
            problems.append(f"{question!r} is a fishing question but runs no zone estimate")

    report(f"9b. fishing now against fishing over time  ({len(cases)} cases)",
           problems)


def check_route():
    """A route must be a route: shortest when the water is open, longer when
    it is not, and never through land.

    Two mistakes were made building it, both worth guarding. The A* guide was
    in kilometres while the cost was weight-times-kilometres, so the search
    explored in the wrong order and wandered. And every cell was being charged
    a sanctuary penalty, because the Sundarbans are modelled as a 35 km circle
    with a 15 km band that shades half the water off Namkhana — when every cell
    costs the same, no path is better than any other.
    """
    import asyncio as _asyncio
    import httpx as _httpx
    sys.path.insert(0, ".")
    from app import route

    problems = []
    start, goal = (21.76, 88.23), (21.55, 88.70)

    def transport(kind):
        def handler(request):
            las = [float(x) for x in request.url.params["latitude"].split(",")]
            los = [float(x) for x in request.url.params["longitude"].split(",")]
            out = []
            for la, lo in zip(las, los):
                blocked = 21.55 < la < 21.75 and 88.38 < lo < 88.52
                wave = (None if kind == "land" and blocked
                        else 3.5 if kind == "rough" and blocked else 0.8)
                out.append({"hourly": {
                    "wave_height": [wave],
                    "ocean_current_velocity": [0.4],
                    "ocean_current_direction": [90.0]}})
            return _httpx.Response(200, json=out)
        return _httpx.MockTransport(handler)

    async def go(kind):
        async with _httpx.AsyncClient(transport=transport(kind)) as c:
            return await route.find(c, start, goal, gust_kn=15)

    try:
        open_water = _asyncio.run(go("open"))
        if open_water.detour_km > 1.0:
            problems.append(f"open water is not routed straight "
                            f"(+{open_water.detour_km} km for nothing)")

        blocked = _asyncio.run(go("land"))
        if blocked.detour_km <= 1.0:
            problems.append("land in the way produced no detour")

        rough = _asyncio.run(go("rough"))
        if rough.worst_wave_m > 2.0:
            problems.append(f"the route went through {rough.worst_wave_m} m "
                            f"waves it could have gone round")
    except Exception as e:
        problems.append(f"routing raised {type(e).__name__}: {e}")

    report("9c. a route goes round things", problems)


# --------------------------------------------------- 10. the map's contract
def check_map():
    """Every map field the page reads must be one the server sends.

    A renamed field would leave the map blank with no error at all — the
    tiles would load, nothing would be drawn on them, and it would look like
    there was simply nothing to show.
    """
    import re

    html = pathlib.Path("static/index.html").read_text()
    js = re.findall(r"<script>(.*?)</script>", html, re.S)[-1]

    served = set(re.findall(r'"(\w+)":',
                 re.search(r"decision\.map = \{(.*?)\n    \}",
                           pathlib.Path("app/agents.py").read_text(), re.S).group(1)))
    read = set(re.findall(r"\bm\.([a-z_]+)", js))

    problems = [f"page reads map.{f}, which the server does not send"
                for f in sorted(read - served)]

    if "typeof L === 'undefined'" not in js:
        problems.append("no fallback when Leaflet fails to load — an offline "
                        "boat would get a broken page instead of a plain answer")
    if "OpenStreetMap" not in js:
        problems.append("OpenStreetMap attribution missing — its licence requires it")

    # A GPS fix must be answered where it is, not snapped to a harbour. Someone
    # who put out from a creek 50 km along the coast is 80 km closer to the
    # boundary than the harbour is, and an answer for the harbour would be
    # wrong in the direction that matters.
    if "FIX" not in js or "navigator.geolocation" not in js:
        problems.append("no way to answer for the user's actual position")
    if "if(FIX) return [FIX.lat, FIX.lon]" not in js:
        problems.append("a GPS fix is taken but not used for the question")
    if "$('#place').value.split" not in js:
        problems.append("the harbour picker fallback is gone — a phone can "
                        "refuse, and a signal can be missing at sea")

    # /nearest was never called by any check, so a wrong function name in it
    # survived a full pass and only surfaced as a 500 in the browser. Call it.
    from fastapi.testclient import TestClient
    from app.main import app as _app
    try:
        client = TestClient(_app)
        for la, lo in ((21.76, 88.23), (26.71, 88.43)):
            r = client.get(f"/nearest?lat={la}&lon={lo}&lang_code=bn")
            if r.status_code != 200:
                problems.append(f"/nearest returned {r.status_code} for {la},{lo}")
                continue
            body = r.json()
            for field in ("name", "distance_km", "far", "inland"):
                if field not in body:
                    problems.append(f"/nearest is missing {field}")
        # a fix far inland must say so rather than be answered as a boat
        if client.get("/nearest?lat=26.71&lon=88.43").json().get("inland") is not True:
            problems.append("a fix 500 km inland is not flagged as inland")
    except ImportError:
        pass          # no test client available; the other checks still ran

    report(f"10. the map's contract  ({len(read)} fields read)", problems)


# --------------------------------------------------- 11. alerts stay quiet
def check_alerts():
    """An alert must fire on a turn for the worse, and stay quiet otherwise.

    The failure that matters here is not silence, it is noise. Telling someone
    every ten minutes that the sea is still rough teaches them to ignore the
    message, and the one they then ignore is the one that mattered.
    """
    sys.path.insert(0, ".")
    from app import alerts

    problems = []

    order = alerts.SEVERITY
    for worse, better in (("stay", "caution"), ("caution", "unknown"),
                          ("unknown", "go")):
        if order.get(worse, 0) <= order.get(better, 0):
            problems.append(f"{worse!r} should rank above {better!r}")

    # losing the data is not reassurance
    if order.get("unknown", 0) <= order.get("go", 0):
        problems.append("'unknown' must rank above 'go' — no data is not good news")

    for name in ("watch", "unwatch", "take", "check_one", "start", "stop"):
        if not hasattr(alerts, name):
            problems.append(f"alerts.{name}() is missing")

    if alerts.INTERVAL_SECONDS > 900:
        problems.append("check interval longer than 15 minutes is too slow to help")

    # taking alerts must clear them, or the same warning arrives forever
    alerts._pending["_t"] = [alerts.Alert("worsened", "x", "stay")]
    first, second = alerts.take("_t"), alerts.take("_t")
    if not first or second:
        problems.append("alerts are not delivered exactly once")

    report("11. alerts stay quiet unless things turn", problems)


def check_range():
    """A fishing zone must be one this boat can actually reach.

    The estimate used to hand a nine-metre open boat a zone 72 km offshore,
    which is a serious undertaking for that boat and a routine morning for a
    trawler. Ignoring the difference contradicted the reasoning the rest of the
    system is built on.
    """
    sys.path.insert(0, ".")
    from app import pfz

    problems = []

    for cls in ("small", "medium", "trawler"):
        if cls not in pfz.RANGE_KM:
            problems.append(f"no working range defined for a {cls} boat")
    if not (pfz.RANGE_KM.get("small", 0) < pfz.RANGE_KM.get("medium", 0)
            < pfz.RANGE_KM.get("trawler", 0)):
        problems.append("ranges must grow with boat size")

    # the filter has to actually drop what is out of reach
    far = pfz.Zone(lat=20.5, lon=87.0, score=0.9, sst_c=29.0,
                   front_c_per_10km=0.4, chl_mg_m3=1.5,
                   distance_km=0, bearing_deg=0)
    near = pfz.Zone(lat=19.85, lon=86.0, score=0.6, sst_c=29.0,
                    front_c_per_10km=0.3, chl_mg_m3=1.2,
                    distance_km=0, bearing_deg=0)
    result = pfz.PfzResult([far, near], "sst", "chl")

    small = pfz.recentre(result, 19.80, 85.82, "small")
    trawler = pfz.recentre(result, 19.80, 85.82, "trawler")
    if any(z.distance_km > pfz.RANGE_KM["small"] for z in small.zones):
        problems.append("a small boat was offered a zone beyond its range")
    if len(trawler.zones) < len(small.zones):
        problems.append("a trawler was offered fewer zones than a small boat")
    if small.zones and not small.note:
        pass          # nothing dropped is fine
    elif not small.zones and not small.note:
        problems.append("zones were dropped without saying so")

    report("11b. zones a boat can reach", problems)


def check_counts_agree():
    """The numbers on one screen must be the same number.

    The panel header counted the evidence a user can see while the Risk row
    counted what existed before fishing zones were withheld, so the same answer
    showed "6 findings" above a list of six and "8 findings" beside it. A reader
    who notices that stops trusting both.
    """
    import re

    source = pathlib.Path("app/agents.py").read_text()
    problems = []

    block = re.search(r'Trace\("Risk".*?\)\)', source, re.S)
    if not block:
        problems.append("cannot find the Risk trace row to check")
    else:
        text = block.group(0)
        if "len(findings)" in text:
            problems.append("the Risk row counts findings before withholding, "
                            "so it will disagree with the list on screen")
        if "decision.findings" not in source[:block.end()]:
            problems.append("the Risk row should count decision.findings")

    # The Visualization row once always said "1 layer" because it was written
    # above the line that builds decision.map, and counted an empty dictionary.
    source_text = pathlib.Path("app/agents.py").read_text()
    map_built = source_text.find("decision.map = {")
    vis_row = source_text.find('Trace("Visualization"')
    if 0 < vis_row < map_built:
        problems.append("the Visualization row is emitted before decision.map "
                        "is built, so its layer count will always be wrong")

    # and the panel subtitle must not promise a fixed number of agents
    from app import panel_strings
    import re as _re
    for code in panel_strings.PANEL:
        if _re.search(r"\b(Nine|nine)\b", panel_strings.PANEL[code]["subtitle"]):
            problems.append(f"{code}: the subtitle still names a fixed agent count")

    # Total counts the rows above it, so it has to be emitted after all of them
    vis_at = source_text.find('Trace("Visualization"')
    rep_at = source_text.find('Trace("Reporting"')
    tot_at = source_text.find('Trace("Total"')
    if not (vis_at < tot_at and rep_at < tot_at):
        problems.append("the Total row is emitted before Visualization or "
                        "Reporting, so its agent count will be short")

    # a follow-up label reaches the screen, so it needs words in every language
    from app import lang as _lang
    for key, pack in _lang.CARRIED.items():
        for code in _lang.LANG_NAMES:
            if code not in pack:
                problems.append(f"carried label {key!r} has no {code} translation")

    # Both the boundary and the sanctuary warning are filed under Geospatial.
    # Picking whichever came first made "how far is the boundary?" answer with
    # a sanctuary and inherit its verdict, so the badge read "safe" above a
    # sentence saying "do not enter".
    if 'next((f for f in findings if f.agent == "Geospatial"), None)' in source_text:
        problems.append("the boundary answer takes the first Geospatial finding, "
                        "which may be the sanctuary warning — filter on the "
                        "phrase kind instead")

    # a follow-up that changes nothing the answer depends on must not return
    # the same answer twice
    sess_text = pathlib.Path("app/session.py").read_text()
    if 'intent == "boundary"' not in sess_text:
        problems.append("a boundary follow-up never switches intent, so "
                        "changing the boat or the day returns an identical answer")

    report("11c. the counts on screen agree", problems)


def check_budget():
    """No single call may outlast the budget for the whole answer.

    A chlorophyll grid once tried four datasets one after another, each with a
    25-second read timeout. The answer took eighty seconds and then failed. Any
    timeout longer than the round's budget can do the same thing again.
    """
    import re
    sys.path.insert(0, ".")
    from app import agents

    budget = agents.ANSWER_BUDGET_S
    problems = []

    for name in ("app/pfz.py", "app/chlorophyll.py", "app/agents.py"):
        text = pathlib.Path(name).read_text()
        for m in re.finditer(r"httpx\.Timeout\(([^)]*)\)", text):
            reads = re.findall(r"read=([\d.]+)", m.group(1))
            for r in reads:
                if float(r) > budget:
                    problems.append(f"{name}: a read timeout of {r}s outlasts "
                                    f"the {budget}s budget for a whole answer")

    # the round must actually be bounded
    if "wait_for" not in pathlib.Path("app/agents.py").read_text():
        problems.append("the agent round is not bounded — one slow source can "
                        "hold the whole answer")

    # and the chlorophyll grid must not go back to trying datasets in series
    chl = pathlib.Path("app/chlorophyll.py").read_text()
    grid = chl[chl.index("async def grid("):]
    if "create_task" not in grid.split("async def ")[1]:
        problems.append("the chlorophyll grid is sequential again — four "
                        "datasets in series is what caused the 80-second answer")

    report(f"11d. nothing outlasts the {budget}s answer budget", problems)


def check_protected():
    """Protected areas: never claim entry, and never bury a closure.

    Two rules, both learned while building it. The geometry is a circle sized
    from a published area figure, so it cannot say which side of a gazetted
    line a boat is on and must not pretend to. And a closure in force outranks
    a nearer area with none — Bhitarkanika sits closer to Dhamra than
    Gahirmatha, and reporting only the nearer one would bury the seven-month
    ban the crew can actually be prosecuted for.
    """
    from datetime import date
    sys.path.insert(0, ".")
    from app import lang, protected

    problems = []

    # each coast should read its own sanctuary's name in its own language,
    # the same rule the harbour names follow
    coast_language = {
        "West Bengal": "bn", "Odisha": "or", "Andhra Pradesh": "te",
        "Tamil Nadu": "ta", "Kerala": "ml", "Maharashtra": "mr",
        "Goa": "mr", "Gujarat": "gu", "Andaman & Nicobar": None,
    }

    for area in protected.AREAS:
        if "en" not in area.names:
            problems.append(f"{area.id}: no English name")
        for code in ("bn", "hi"):
            if code not in area.names:
                problems.append(f"{area.id}: no {code} name")
        want = coast_language.get(area.state)
        if want and want not in area.names:
            problems.append(f"{area.id}: {area.state} should read in {want}")
        if not (area.radius_km or area.line):
            problems.append(f"{area.id}: has neither a radius nor a corridor")
        if area.closure and area.closure.reason not in lang.CLOSURE_REASON:
            problems.append(f"{area.id}: closure reason "
                            f"{area.closure.reason!r} has no translation")

    # a closure in force must win over a nearer open area
    winter = protected.check(20.79, 86.98, date(2026, 12, 1))
    if not winter or not winter.closed:
        problems.append("Gahirmatha's closure is not surfacing at Dhamra in December")
    summer = protected.check(20.79, 86.98, date(2026, 8, 1))
    if summer and summer.closed:
        problems.append("a closure is being reported outside its season")

    # the phrases the agent can emit must exist in every language
    for kind in ("mpa_closed", "mpa_soon", "mpa_near", "mpa_edge"):
        pack = lang.PHRASES.get(kind, {})
        for code in lang.LANG_NAMES:
            if code not in pack:
                problems.append(f"{kind} has no {code} translation")

    report(f"12. protected areas  ({len(protected.AREAS)} areas)", problems)


if __name__ == "__main__":
    check_signatures()
    check_names()
    check_sources()
    check_routing()
    check_behaviour()
    check_vocabulary()
    check_interface()
    check_duplicates()
    check_translation()
    check_ports()
    check_map()
    check_alerts()
    check_range()
    check_counts_agree()
    check_budget()
    check_protected()
    if FAILURES:
        print(f"{len(FAILURES)} problem(s) — do not package")
        sys.exit(1)
    print("all checks passed")
