"""
Test chlorophyll at the coordinates the app actually uses.

The standalone check passed while the app failed, and the two were not asking
the same question: the check used round numbers a little way offshore, the app
uses the harbour positions in ports.py. A harbour sits on the coast, so a box
drawn around it is half land — and land has no ocean colour at all.

This runs every port through the real client and reports what comes back, so
the difference is measured rather than argued about.

    python -m app.check_ports_chl              # a representative handful
    python -m app.check_ports_chl --all        # all 48
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from . import chlorophyll as chl
from . import ports

SAMPLE = ["digha", "namkhana", "kakdwip", "paradip", "visakhapatnam",
          "chennai", "rameswaram", "kochi", "mangaluru", "veraval", "mumbai"]


async def one(client, p):
    """Exactly what the app does: sample seaward, widening if the box is thin."""
    chl.LAST_ATTEMPTS.clear()
    la, lo = ports.seaward(p)
    hit = await chl.around(client, la, lo)
    if hit:
        return (f"  {p.name('en'):22s} harbour {p.lat:6.2f},{p.lon:6.2f} → "
                f"sea {la:6.2f},{lo:6.2f}  {hit.mg_m3:>7.3f}  "
                f"{hit.band:10s} {hit.pixels:>3d} px  {hit.when[:10]}")
    why = "; ".join(chl.LAST_ATTEMPTS[-4:]) or "no reason recorded"
    return (f"  {p.name('en'):22s} harbour {p.lat:6.2f},{p.lon:6.2f} → "
            f"sea {la:6.2f},{lo:6.2f}  FAILED — {why}")


async def main():
    every = "--all" in sys.argv
    chosen = ports.PORTS if every else [ports.BY_ID[i] for i in SAMPLE
                                        if i in ports.BY_ID]

    print(f"Testing {len(chosen)} harbours. Sampling {ports.SEAWARD_DEG}° seaward "
          f"of each, box ±{chl.BOX_DEG}° widening to ±{chl.BOX_DEG*4}° if thin.\n")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = await asyncio.gather(*[one(client, p) for p in chosen])
    for line in results:
        print(line)

    failed = sum(1 for r in results if "FAILED" in r)
    print(f"\n{len(results) - failed} of {len(results)} returned a value.")
    if failed:
        print("If the failures are coastal harbours, the box is mostly land — "
              "the fix is to sample seaward of the harbour, not around it.")


if __name__ == "__main__":
    asyncio.run(main())
