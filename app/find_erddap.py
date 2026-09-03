"""
Find a working ERDDAP server, from this machine, on this network.

The first attempt failed for two different reasons, neither of them syntax:

  coastwatch.noaa.gov       403 Forbidden   — the server refused the request
  coastwatch.pfeg.noaa.gov  ConnectTimeout  — unreachable from here

A 403 with an HTML body is usually a firewall judging the client, not the
query: many government servers reject the default `python-httpx/x.y` user
agent. A timeout is a network path problem, and it may be specific to one ISP.

ERDDAP is federated — dozens of institutions run public mirrors, and several
carry the same NASA and NOAA ocean-colour products. So rather than guessing
which one works, this asks each in turn and reports what actually happens.

    python -m app.find_erddap

Send the output. Whichever host answers is the one to use.
"""

from __future__ import annotations

import asyncio

import httpx

# A browser-like user agent. Not a trick — it is what these servers expect,
# and ERDDAP's own terms ask only that you identify yourself and be reasonable
# about request volume.
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}

HOSTS = [
    "https://coastwatch.noaa.gov/erddap",
    "https://coastwatch.pfeg.noaa.gov/erddap",
    "https://upwell.pfeg.noaa.gov/erddap",
    "https://polarwatch.noaa.gov/erddap",
    "https://oceanwatch.pifsc.noaa.gov/erddap",
    "https://cwcgom.aoml.noaa.gov/erddap",
    "https://erddap.riddc.brown.edu/erddap",
    "https://erddap.emodnet.eu/erddap",
    "https://erddap.marine.ie/erddap",
]

LAT, LON = 21.6, 87.6          # off Digha


async def reachable(client, host, headers, label):
    """Can we talk to this server at all?"""
    try:
        r = await client.get(f"{host}/index.html", headers=headers, timeout=15)
        return r.status_code, ""
    except Exception as e:
        return None, f"{type(e).__name__}"


async def chlorophyll_datasets(client, host, headers):
    """Ask the server which chlorophyll datasets it actually carries."""
    try:
        r = await client.get(
            f"{host}/search/index.json",
            params={"searchFor": "chlorophyll", "page": 1, "itemsPerPage": 40},
            headers=headers, timeout=20)
        if r.status_code != 200:
            return []
        table = r.json()["table"]
        cols, rows = table["columnNames"], table["rows"]
        i_id = cols.index("Dataset ID")
        i_title = cols.index("Title")
        i_grid = cols.index("griddap") if "griddap" in cols else None
        out = []
        for row in rows:
            if i_grid is not None and not row[i_grid]:
                continue                      # tabledap only, wrong shape
            out.append((row[i_id], str(row[i_title])[:58]))
        return out
    except Exception:
        return []


async def try_query(client, host, dsid, headers):
    """Actually pull a value, the way the real client would."""
    url = (f"{host}/griddap/{dsid}.json"
           f"?chlor_a[last-6:1:last][0]"
           f"[({LAT-0.2}):2:({LAT+0.2})][({LON-0.2}):2:({LON+0.2})]")
    try:
        r = await client.get(url, headers=headers, timeout=25)
    except Exception as e:
        return f"{type(e).__name__}"

    if r.status_code != 200:
        # retry without the altitude dimension — not every product has one
        url2 = url.replace("[last-6:1:last][0]", "[last-6:1:last]")
        try:
            r2 = await client.get(url2, headers=headers, timeout=25)
            if r2.status_code == 200:
                return summarise(r2) + "  (no altitude dim)"
        except Exception:
            pass
        return f"HTTP {r.status_code} · {r.text.strip()[:90]}"

    return summarise(r)


def summarise(r):
    try:
        t = r.json()["table"]
        cols, rows = t["columnNames"], t["rows"]
        iv = cols.index("chlor_a")
        good = [x[iv] for x in rows
                if x[iv] is not None and str(x[iv]).lower() != "nan"]
        if not good:
            return f"OK but {len(rows)} pixels all empty (cloud)"
        return f"OK · {len(good)}/{len(rows)} pixels · e.g. {good[0]}"
    except Exception:
        return f"200 but unparsed · {r.text[:80]}"


async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        print("=== 1. which servers answer, and does the user agent matter? ===\n")
        alive = []
        for host in HOSTS:
            plain, e1 = await reachable(client, host, {}, "plain")
            withua, e2 = await reachable(client, host, UA, "browser UA")
            mark = ""
            if withua == 200:
                alive.append(host)
                mark = "  <-- usable"
            print(f"  {host:46s} plain={str(plain or e1):<16s} "
                  f"withUA={str(withua or e2):<16s}{mark}")

        if not alive:
            print("\nNo ERDDAP server answered. That points at the network here "
                  "(ISP, DNS or a captive portal) rather than at any one server.")
            return

        print("\n=== 2. what chlorophyll data do the reachable ones carry? ===")
        for host in alive:
            ds = await chlorophyll_datasets(client, host, UA)
            print(f"\n  {host}")
            if not ds:
                print("    (search returned nothing)")
                continue
            for dsid, title in ds[:8]:
                print(f"    {dsid:34s} {title}")

            print("\n    -- trying the first three against Digha --")
            for dsid, _ in ds[:3]:
                print(f"    {dsid:34s} {await try_query(client, host, dsid, UA)}")


if __name__ == "__main__":
    asyncio.run(main())
