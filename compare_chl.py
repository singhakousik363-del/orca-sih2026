"""Same water, same day, two independent products.

ISRO  : Oceansat-3 OCM analysed chlorophyll (MOSDAC L4, MOM5-TOPAZ
        assimilation), 25 km grid, read from a local NetCDF file.
NOAA  : VIIRS DINEOF gap-filled daily, 4 km, queried from ERDDAP for the
        same date rather than the latest available.

Prints both so the difference can be stated rather than assumed.
"""

import httpx
import xarray as xr

DATE = "2026-03-29"
LAT, LON = 14.0, 87.0
BOX = 0.5

NC = f"data/E06OCML4AC_{DATE.replace('-', '')}_25km_v1.0.1.nc"
HOST = "https://coastwatch.noaa.gov/erddap/griddap"
DS = "noaacwNPPN20VIIRSDINEOFDaily"


def isro():
    ds = xr.open_dataset(NC)
    pt = ds.chla.sel(lat=LAT, lon=LON, method="nearest").squeeze()
    box = ds.chla.sel(lat=slice(LAT - BOX, LAT + BOX),
                      lon=slice(LON - BOX, LON + BOX)).squeeze()
    vals = box.values.ravel()
    vals = vals[vals == vals]                      # drop NaN
    return float(pt.values), vals


def noaa():
    t = f"({DATE}T12:00:00Z):1:({DATE}T12:00:00Z)"
    url = (f"{HOST}/{DS}.json"
           f"?chlor_a[{t}][0]"
           f"[({LAT - BOX}):2:({LAT + BOX})][({LON - BOX}):2:({LON + BOX})]")
    r = httpx.get(url, headers={"User-Agent": "orca-sih2026"}, timeout=30)
    if r.status_code != 200:
        print(f"  NOAA HTTP {r.status_code}: {r.text.strip()[:200]}")
        return None
    table = r.json()["table"]
    i = table["columnNames"].index("chlor_a")
    vals = [float(row[i]) for row in table["rows"]
            if row[i] is not None and 0 < float(row[i]) < 100]
    return vals


def stats(vals):
    s = sorted(vals)
    m = len(s) // 2
    median = s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2
    return median, sum(s) / len(s), min(s), max(s), len(s)


print(f"Position {LAT}N {LON}E  ·  {DATE}  ·  ±{BOX}° box\n")

pt, iv = isro()
med, mean, lo, hi, n = stats(iv)
print("Oceansat-3 OCM L4 (MOSDAC, 25 km)")
print(f"  nearest point : {pt:.3f}")
print(f"  median        : {med:.3f}   mean {mean:.3f}   range {lo:.3f}-{hi:.3f}   n={n}")

nv = noaa()
if nv:
    med, mean, lo, hi, n = stats(nv)
    print("\nNOAA VIIRS DINEOF (4 km)")
    print(f"  median        : {med:.3f}   mean {mean:.3f}   range {lo:.3f}-{hi:.3f}   n={n}")
else:
    print("\nNOAA: no data for this date")
