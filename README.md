# ORCA — prototype

Marine EcOsystem Reasoning with Collaborative Agents
SIH 2026 · SIH26176 · ISRO · Disaster Management · Team Losers, SIT

A fisherman asks a question out loud in Bengali. Specialist agents fetch live
marine and weather data, a risk agent decides what those numbers mean *for that
boat*, and the answer comes back spoken in Bengali with its evidence attached.

---

## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 in **Chrome** (voice input uses the Web Speech API,
which Firefox does not support).

Check the sources are live:

```bash
curl http://127.0.0.1:8000/health
```

## Deploy for the submission link

```bash
gcloud run deploy orca \
  --source . --region asia-south1 --allow-unauthenticated
```

Paste the URL it prints into the Proposed Solution slide. A judge clicking a
working link is worth more than any diagram.

---

## Layout

```
app/sources.py    the source catalogue — one ranked chain per capability
app/imd.py        IMD client and bulletin parsers (sea state, wind, nowcast)
app/chlorophyll.py NOAA ERDDAP ocean-colour client, with cloud-gap fallback
app/pfz.py        fishing-zone estimate — SST fronts crossed with chlorophyll
app/panel_strings.py  agent panel labels, per language
app/alerts.py     the part that speaks without being asked
app/protected.py  sanctuaries and seasonal fishing closures
app/route.py      a lower-risk way across, by grid search
app/geofence.py   distance to the India–Bangladesh maritime boundary
app/agents.py     user interaction, discovery, planner, ocean, ocean analytics,
                  weather, geospatial, risk
app/main.py       FastAPI
static/index.html the phone UI, Bengali, voice in and out
```

### Why it is built this way

**Agents never call an API directly.** They ask the Marine Data Discovery agent
for a capability — `sea_state`, `weather` — and it walks a ranked chain of
sources until one answers. Official Indian sources rank above global models, but
a fallback that works beats an official source that is down.

The trace shows when it fell back and from what, so a judge can see the chain
working rather than take it on trust. When they ask what happens if government
access never arrives, the answer is visible on screen.

**The model produces no numbers.** Every value in an answer is fetched, and
every finding carries the source and timestamp it came from. The language layer
only phrases what the risk agent decided. That is the whole safety argument —
an LLM cannot hallucinate a sea state it was never asked to generate.

**Under a "do not go" verdict, the fishing zones are withheld.** A headline
saying stay ashore with "good fishing 37 km east" listed underneath is mixed
messaging, and the second line is the one someone in a hurry acts on. The zones
are still found and the agent trace records that they were withheld and why —
nothing is hidden from review, only from a user who has just been told the sea
is dangerous.

**A fishing question gets a fishing answer, unless it is unsafe.** Ask where
the fish are in calm water and the answer names a zone with its distance and
bearing. Ask the same thing when the waves are over the boat's limit and the
answer is "do not go" — the zone is never mentioned. Safety outranks catch, and
that ordering is in `risk_agent()`, not left to the user to work out.

**`risk_agent()` is the project.** Fetching a wave height is easy. Deciding that
1.8 m is fine for a trawler and dangerous for a 9 m boat, and that a lightning
warning outranks wave height either way, is the part that is actually hard.
Point at that function when asked what you built.

---

## Checks

    python verify.py

Five checks, all of them written after a bug reached the user:

1. **Call signatures.** Four times an edit's search text had drifted, the
   replace did nothing, and the mismatch surfaced as a TypeError on the user's
   machine. Dataclasses are included, because inserting a field in the middle
   of one silently reshuffles every positional call site.
2. **Undefined names.** A missing `timedelta` import inside a source body
   survived every test, because every test stubbed the sources out. Stubbing
   the thing you are verifying verifies nothing.
3. **Every source body executed** against a fake HTTP layer — the real parsing
   code, not a stand-in.
4. **Every suggested question routed.** The Marathi and Malayalam words for
   fish were missing from the planner, so a fishing question in those languages
   quietly became a safety question. No error, just a wrong answer.
5. **Behaviour that matters** — boat class edges, pixel validity, compass wrap,
   4 a.m. against 4 p.m., seaward sampling direction, session isolation.
5b. **Panel vocabulary.** Every word the backend asks the panel to translate
   must exist in every language. A missing key silently prints itself, so the
   panel comes out half English with no error — which is how "ocean" and
   "analytics" sat untranslated in the planner line.
6. **The interface itself.** A careless edit once deleted half the script —
   every handler, the renderer, the language loader — and the file still parsed
   as valid JavaScript. This checks that every function the page needs exists,
   every id the script reaches for is in the markup, every class it emits is
   styled, and the markup nests correctly.

7. **Nothing defined twice.** A second vocabulary block was appended to
   `panel_strings.py` and shadowed the first. Both halves looked right alone.
8. **Nothing left in English.** Key coverage is not a translated screen:
   "ocean · analytics · pfz" and "(Ocean, Weather-এর তথ্য আসেনি)" both passed a
   key check and both read as English inside another language.
9. **Harbour names.** Hindi carries all 48 coasts; each other language carries
   its own.
10. **The map's contract.** A renamed field would leave the map blank with no
    error — tiles loading, nothing drawn, looking like there was nothing to show.

Run it before packaging, and run it again on the unpacked archive rather than
the working copy.


## Before the internal round

**0. A fishing zone is filtered by what the boat can reach.** `RANGE_KM` in
`pfz.py` — 40 km for an open boat under 9 m, 80 m for a decked boat, 150 for a
trawler. Before this, a nine-metre open boat was being handed a zone 72 km
offshore: a serious undertaking for that boat, a routine morning for a trawler.
Ignoring the difference contradicted the reasoning the rest of the system is
built on.

These are placeholders in the same way the wave limits are, taken from what
boats of each size are generally described as doing rather than from anyone who
fishes. Question three of the field interviews replaces them.

**1. Replace the thresholds.** `WAVE_LIMIT_M` and `WIND_LIMIT_KN` in
`agents.py` are placeholders I chose. The numbers must come from the fishermen
interviewed in South 24 Parganas — ask "how high do the waves have to be before
you stay in", and ask the length of their boat. That one answer makes both the
risk agent and the research slide defensible.

**2. Replace the boundary geometry.** `BOUNDARIES` in `geofence.py` holds three
approximate lines — India–Bangladesh, India–Sri Lanka (Palk Bay and the Gulf of
Mannar) and India–Pakistan at Sir Creek. All three are demonstration geometry.
Swap in the published IMBL coordinates before the finale, and say plainly in the
deck that the demo used approximations until then. A boundary warning that is
wrong by a few kilometres is worse than no warning, because it will be trusted.

**2b. Check the harbour coordinates.** `ports.py` carries 48 harbours across 12
coastal states and UTs. The positions are approximate — good enough to fetch a
forecast for the right stretch of water, not good enough to navigate by.

**3. IMD is wired but unverified.** `app/imd.py` and the `ImdWeather` /
`ImdOcean` sources in `sources.py` are written against the published sample
payloads in the IMD API reference. They have NOT been checked against a live
response, because access is still pending.

Set `IMD_API_KEY` and the source catalogue routes to IMD automatically, with
Open-Meteo as the fallback. On the first successful call, check the field names
in `imd.py` against what actually comes back — `row.get("sea")`, `row.get("wind")`
and the nowcast category field are the three most likely to differ.

Two approximations to declare in the deck:
- A Sea Area Bulletin covers a whole sea area, not a coordinate. We map the
  user's position to the nearest area centre.
- The bulletin gives sea state in words. `SEA_STATE_M` converts them using the
  WMO scale, taking the upper end of each band — for a safety call, the
  pessimistic reading of an ambiguous word is the right one.

---

## Known limits — say these before a judge finds them

- Wave and wind data come from a global model (Open-Meteo / DWD), not from IMD.
  The IMD account is applied for; the swap is a one-line change.
- The maritime boundary is approximate.
- Harbour and state names follow a deliberate rule. Hindi carries all 48
  because it is the link language and a Hindi reader could be on any coast.
  Bengali carries all 48 because it is the one language the author reads, so
  every line of it has actually been checked. The other six carry their own
  coast — the only one a fisherman using that language sails from — and show
  English elsewhere.

  The reason for stopping there is worth stating plainly: generating
  transliterations into six scripts nobody on the team can read would look
  finished and might be wrong, and a wrong place name in Malayalam is a defect
  that would survive to the finale unnoticed. English is honest about what has
  not been verified.
- Eight languages are carried: Bengali, Hindi, Marathi, Gujarati, Odia, Tamil,
  Telugu and Malayalam. Kannada and Konkani are not, so Karnataka and Goa
  harbours show English names. Bengali and Assamese share a script and are not
  separated; Hindi and Marathi are separated by keyword, not script.
- Voice is input only. Spoken answers were removed deliberately: a synthesised
  voice reading a safety verdict adds a layer that can mishear or mispronounce,
  and the written answer is already short enough to read at a glance. The
  microphone stays, because typing is the barrier for this user, not reading.
- Speech recognition accuracy varies by language in the browser. Bengali, Hindi
  and Tamil are reliable in Chrome; Odia and Malayalam are weaker. Every
  language can still be used by tapping a suggestion.
- The agent panel is fully translated — names, roles, and the detail lines
  themselves. A trace line is sent as pieces rather than a finished sentence:
  `{"t": ...}` is printed verbatim, `{"w": key}` is one of our words,
  `{"n": 3, "w": key}` is a count with its noun. Product names and exception
  types stay in English on purpose: "Open-Meteo wave model (DWD/NOAA)" is a
  name, and translating it would make a citation harder to check rather than
  easier.
- Chlorophyll comes from NOAA CoastWatch ERDDAP (open, no key). Which server
  and which product took probing rather than guessing — `python -m app.find_erddap`
  is kept in the repo so the next person can re-run it. What it established:

  - coastwatch.noaa.gov returns 403 to a plain Python client and 200 to a
    browser-shaped user agent, so the user agent is not optional.
  - coastwatch.pfeg.noaa.gov and upwell.pfeg.noaa.gov time out entirely from an
    Indian consumer connection. Dropped.
  - polarwatch.noaa.gov mirrors the same products and needs no user agent, so
    it is the fallback host.
  - The DINEOF gap-filled products are the reason this works at all. A plain
    daily ocean-colour query at Digha returned 252 pixels, every one of them
    cloud. The gap-filled product for the same day returned 42 usable pixels
    out of 63.

  A third thing the probe caught, worth remembering beyond this project: a
  dataset can go stale without going down. The MODIS 8-day product answered
  cheerfully on 30 August 2026 with an image from April 2022 — its `last` index
  is frozen four years back, and nothing in the response says so. Only the
  timestamp gives it away. The client now refuses anything older than 21 days
  and prints the age in every citation. Serving 2022 water as today's would
  have been worse than serving nothing, and no error would ever have fired.

  Two more things to say plainly in the deck rather than let a judge find:

  - **DINEOF is interpolation, not measurement.** It reconstructs what the
    sensor could not see from the surrounding water and the recent past. That
    is standard practice and a reasonable estimate, but it is not the satellite
    having looked at that pixel. Every citation says which product was used and
    whether it was gap-filled or measured.
  - **Ocean colour reads high over turbid coastal water.** Near the Hooghly
    mouth, suspended river sediment is misread as chlorophyll, so values off
    Digha and Namkhana are inflated. We take the median of the pixels in the box
    rather than the mean so a few contaminated pixels cannot drag the figure,
    but the band should still be read as relative — is this water richer than
    the water beside it — not as an absolute concentration.

- **The fishing-zone estimate is ours, not INCOIS's.** INCOIS has issued PFZ
  advisories since the late 1990s on a published principle: *regions where SST
  gradients occur along with higher chlorophyll are strong potential for
  fishing*. We follow that principle, and differ from it in two ways that
  belong in the deck:

  - INCOIS uses NOAA-AVHRR infrared SST at about 1 km and detects fronts with
    the Cayula-Cornillon histogram algorithm. We use a model SST field at about
    8 km and a plain gradient magnitude. A model field is smoothed, so our
    fronts are weaker and blurrier than theirs, and small fronts vanish.
  - Because of that, cells are scored *relative to the others in the same
    grid* — "the strongest front around here today" — not against an absolute
    threshold. Claiming an absolute front strength from a smoothed field would
    dress up a weaker measurement as a stronger one.

  Zones near an international maritime boundary are dropped before they can be
  recommended, and the count of dropped cells is reported. A productive patch
  on the wrong side of the line is not an opportunity.

- The map shows only what the answer is about: the boat, the boundary that
  matters to it, and any fishing zone worth going to. Not all 48 harbours, not
  all three boundaries. A screen full of things this person cannot use is worse
  than a sparse one.
- Tiles come from OpenStreetMap over a CDN, so a boat with no signal gets no
  map. That is handled rather than left to break: the map element removes
  itself and the written answer stands on its own, which is the part that
  matters at 4 a.m.
- **Alerts are a poll, not a push.** The app asks the server whether anything
  has changed. Reaching a phone that is asleep on a boat needs Firebase or SMS,
  and SMS is the one that reaches the feature phone that actually matters here.
  That is a deployment question rather than a reasoning one, and the deck should
  say so rather than imply notifications already reach a boat at sea.
- An alert fires only when the verdict turns *worse*. Conditions staying rough
  raise nothing, and conditions improving raise nothing. Telling someone every
  ten minutes that the sea is still rough teaches them to ignore the message,
  and the one they then ignore is the one that mattered.
- The check interval is 60 seconds so a demonstration shows something within a
  minute. In use it would be 15 to 30 minutes, which is the rate at which any of
  the underlying data changes.
- **Protected areas never claim a boat is inside one.** The geometry is a
  circle sized from a published area figure, or a corridor along a coast. That
  is enough to say "Gahirmatha is 7 km away" and nowhere near enough to say
  which side of a gazetted line a boat is on. Telling someone they have
  committed an offence on the strength of a circle would be worse than saying
  nothing. Replace these with the notified boundaries from the state forest
  departments or the WDPA before the finale.

- **A closure in force outranks a nearer area with none.** Bhitarkanika sits
  closer to Dhamra than Gahirmatha does, and reporting only the nearer one
  would bury the fact that Gahirmatha shuts to fishing every year from
  1 November to 31 May for olive ridley nesting — which is the thing a crew can
  actually be prosecuted for. A closure starting within 45 days is reported too,
  because a ban three weeks out is something to plan around rather than to
  discover on the morning it takes effect.

- **A boundary question leads with the boundary.** The maritime line and the
  sanctuary warning are both Geospatial findings, and the sanctuary one is added
  first. Taking whichever came first meant "how far is the boundary?" answered
  with a sanctuary and inherited its verdict, so the badge read "safe" directly
  above a sentence saying "do not enter". The sanctuary is still mentioned, but
  after the boundary and never as the badge.

- **Changing the boat or the day after a boundary question switches to safety.** Hull
  length has no bearing on the distance to a line, so "what if my boat is 18 m"
  used to inherit the boundary intent and return a word-for-word identical
  answer — the user asked something and got nothing back. Boat length is a
  safety parameter and nothing else, so changing it means asking what it
  changes, and the reply says so.

- **A GPS fix is answered where it is, not snapped to a harbour.** The picker
  covers 48 harbours, but a boat does not put out from a list. Someone leaving
  a creek 50 km along the coast from Frasergunj is 80 km closer to the
  international boundary than the harbour is — snapping to the nearest harbour
  would be wrong in the direction that matters. The nearest harbour is used
  only to tell the user where we think they are, and the answer says how far
  off it is.

  The picker stays as the fallback, and always will: a phone can refuse the
  permission, and a signal can be missing at four in the morning on the water —
  which is exactly when this is used.

- **Boat length can be given in feet.** The wave limits are written in metres,
  but a fisherman in Bengal says "thirty foot boat", and the register a licence
  is written in is not the one people speak. The field switches unit and
  converts; a spoken or typed "৩০ ফুট" is understood too. Everything on the
  wire is metres.

- **The last answer survives the signal.** This app claims to be for someone at
  sea, and at sea there is often no signal — which is exactly when the answer
  matters. Showing a blank screen at that moment would be the worst thing it
  could do, so the last answer that arrived is shown again, marked plainly as
  old and with how long ago it was.

  It is kept in memory for the session, not in browser storage. A forecast that
  survived a week in a store and reappeared looking current would be worse than
  none at all.

- **"Where are the fish" and "why are there fewer fish" are different
  questions.** Both mention fish; the first is about this morning and runs the
  zone estimate, the second is about a season and compares this year's water
  with the same weeks a year ago. A planner that cannot tell them apart answers
  the wrong one — which it did for "why is the catch down?", a sentence that
  says catch and never says fish.

  The comparison answer never claims to explain a catch. A catch is fish minus
  effort minus gear minus market, and a satellite sees none of that. It reports
  what the water did, says in the same breath what it cannot see, and leaves
  the conclusion to the person who knows the ground.

- **Twelve seconds is the whole budget for an answer.** Not per call — for the
  round. Past that a partial answer that names what is missing beats a complete
  one nobody waited for, and the risk agent already refuses to say "safe" on
  incomplete data.

  This came from a real failure: the chlorophyll grid tried four datasets one
  after another, each with a 25-second read timeout, and an answer took eighty
  seconds and then failed anyway. The datasets now run at the same time, every
  individual timeout sits inside the budget, and `verify.py` checks that neither
  slips back.

- **The route is a direction, not navigation.** There is no depth in it, no
  sandbar, no wreck, no channel marker, no other vessel. A skipper who followed
  a line from this instead of his own knowledge of the ground would be worse
  off, not better — so the answer says that every time, not only when the route
  bends.

  What it does do is real: a grid between the boat and where it is going, each
  cell scored on wave height, gusts, current across the track, and how near it
  passes a boundary or a sanctuary, then the cheapest way across. "Twelve
  kilometres further to keep out of a steep beam sea" is a decision this data
  can genuinely inform.

  Land needs no coastline file. The marine model returns nothing over land, so
  a cell with no wave height is not sea — the model's own opinion about where
  the water is, arriving free with the wave cost in the same bulk request.

  Two mistakes are worth recording. The A* guide was in kilometres while the
  cost was weight-times-kilometres, so the search explored in the wrong order
  and wandered south before turning back. And every cell was being charged a
  sanctuary penalty, because the Sundarbans are a 35 km circle here with a
  15 km warning band, which shades half the water off Namkhana; when every cell
  costs the same, no path is better than any other. Routing now charges for
  entering a protected area, not for being near one.
