import json, os, sys, httpx

BASE = "https://api.imd.gov.in/api/v1"
TOKEN_URL = "https://api.imd.gov.in/api/oauth/token.php"
TIMEOUT = 20.0

def login(email, password):
    r = httpx.post(TOKEN_URL, json={"email": email, "password": password},
                   headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
    print(f"--- login: HTTP {r.status_code} ---")
    if r.status_code != 200:
        print(r.text[:2000])
        raise SystemExit("401 = wrong email/password. 403 = IP not registered. 404/5xx = endpoint moved or upstream down.")
    body = r.json()
    print(json.dumps(body, indent=2, ensure_ascii=False)[:1500])
    token = body.get("access_token")
    if not token:
        raise SystemExit(f"no 'access_token'. Keys present: {list(body)}")
    print(f"\n>>> token ok, expires_in = {body.get('expires_in')}\n")
    return token

def walk(obj, depth=0, max_depth=4):
    pad = "  " * depth
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}: {type(v).__name__}")
                if depth < max_depth:
                    walk(v, depth + 1, max_depth)
            else:
                print(f"{pad}{k}: {type(v).__name__} = {repr(v)[:70]}")
    elif isinstance(obj, list):
        print(f"{pad}[{len(obj)} items]")
        if obj and depth < max_depth:
            walk(obj[0], depth + 1, max_depth)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "seabulletin"
    params = dict(a.split("=", 1) for a in sys.argv[2:] if "=" in a)
    missing = [n for n in ("IMD_API_KEY", "IMD_EMAIL", "IMD_PASSWORD") if not os.environ.get(n)]
    if missing:
        raise SystemExit(f"not set: {', '.join(missing)} — run: set -a && source .env && set +a")

    api_key = os.environ["IMD_API_KEY"]
    token = login(os.environ["IMD_EMAIL"], os.environ["IMD_PASSWORD"])

    url = f"{BASE}/{path}"
    print(f"--- GET {url}  params={params or None} ---")
    r = httpx.get(url, params=params or None,
                  headers={"X-API-KEY": api_key, "Authorization": f"Bearer {token}"},
                  timeout=TIMEOUT)
    print(f"HTTP {r.status_code}")
    print("content-type:", r.headers.get("content-type"), "\n")
    if r.status_code != 200:
        print(r.text[:3000])
        raise SystemExit("\n401 = token rejected. 403 = key/IP. 404 = path not on v1.")
    try:
        body = r.json()
    except ValueError:
        print("not JSON:\n", r.text[:3000]); return
    print("=== FULL RESPONSE (first 6000 chars) ===")
    print(json.dumps(body, indent=2, ensure_ascii=False)[:6000])
    print("\n=== KEY MAP — diff this against imd.py ===")
    walk(body)

main()
