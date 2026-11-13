"""
Thai Mutual Fund NAV — daily updater + site builder.
Source: SEC Open APIs v2 (api.sec.or.th). Runs in GitHub Actions.

  python update.py fetch [--days N]   pull NAVs for the last N days (default 7)
                                      + refresh the fund list, write data/
  python update.py build              turn data/ into the website in site/

The "database" is just files in this repo:
  data/funds.json               active fund list (name, AMC, category, classes)
  data/daily/YYYY-MM-DD.json    one small file per NAV date (never grows)
The build step turns those into fast per-fund files for the website.

The API key is read from the SEC_API_KEY environment variable
(a GitHub Secret) — it is never written into the code or the website.
"""
import json, os, sys, time, shutil, argparse, datetime as dt
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API = "https://api.sec.or.th/v2/fund"
ROOT = Path(__file__).resolve().parent
DATA, DAILY, SITE = ROOT / "data", ROOT / "data" / "daily", ROOT / "site"
BKK = dt.timezone(dt.timedelta(hours=7))
PAGE = 100            # API maximum
GAP = 0.075           # at most ~13 calls/s; SEC limit is 5,000 calls / 5 minutes
_last = 0.0
_pause_until = 0.0    # set when SEC says "too many requests"; every thread waits
import threading
from concurrent.futures import ThreadPoolExecutor
_lock = threading.Lock()
WORKERS = 12          # weeks fetched in parallel (~9 calls/s, below the SEC limit of ~16/s)

CATEGORY = {"ตราสารทุน": "Equity", "ตราสารหนี้": "Fixed Income", "ผสม": "Mixed",
            "ทรัพย์สินทางเลือก": "Alternative", "อื่น ๆ": "Other"}


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ API
def get(path, params):
    global _last
    key = os.environ.get("SEC_API_KEY", "").strip()
    if not key:
        sys.exit("ERROR: SEC_API_KEY is missing. Add it in GitHub: Settings > Secrets and variables > Actions.")
    url = f"{API}{path}?{urlencode(params)}"
    global _pause_until
    for attempt in range(12):
        with _lock:  # space out calls across all threads
            now = time.time()
            w = max(GAP - (now - _last), _pause_until - now)
            if w > 0:
                time.sleep(w)
            _last = time.time()
        try:
            req = Request(url, headers={"Ocp-Apim-Subscription-Key": key, "Accept": "application/json"})
            with urlopen(req, timeout=90) as r:
                body = r.read()
                return json.loads(body) if body.strip() else {}
        except HTTPError as e:
            if e.code == 401:
                sys.exit("ERROR 401: the SEC rejected the API key. Check the SEC_API_KEY secret.")
            if e.code in (204, 404):
                return {}
            if e.code == 400:
                sys.exit(f"ERROR 400 from SEC: {e.read()[:300]!r}")
            delay = max(int(e.headers.get("Retry-After") or 0), min(60, 2 ** attempt))
            if e.code == 429:  # rate limit: pause everyone, not just this thread
                delay = max(delay, 15)
                with _lock:
                    if _pause_until < time.time() + delay:
                        _pause_until = time.time() + delay
                        log(f"  SEC rate limit reached — pausing {delay}s")
            else:
                log(f"  HTTP {e.code} — retry in {delay}s")
                time.sleep(delay)
        except (URLError, TimeoutError, ConnectionError) as e:
            log(f"  network: {e} — retry")
            time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"gave up after retries: {url}")


def get_all(path, params):
    rows, cursor = [], None
    while True:
        p = dict(params, page_size=PAGE)
        if cursor:
            p["next_cursor"] = cursor
        d = get(path, p)
        items = d.get("items") or []
        rows += items
        cursor = d.get("next_cursor")
        if not cursor or not items:
            return rows


# ------------------------------------------------------------------ files
def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def num(v):
    try:
        return None if v in (None, "") else round(float(v), 4)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ fetch
# --- classification -------------------------------------------------
# Official SEC specification codes -> fund type / tax labels
TYPE_CODES = {"ETF": "ETF", "ETFLI": "ETF", "IND": "Index", "GF": "Gold",
              "MM": "Money Market", "MMF": "Money Market", "FED": "Feeder",
              "FF": "Fund of Funds", "SE": "Sector", "NXCOM": "Commodity",
              "CRF": "Capital Protected", "GG": "Capital Protected", "TR": "Trigger",
              "ISL": "Islamic", "SRI": "ESG", "ESG": "ESG", "AB": "Absolute Return",
              "BH": "Fixed Term"}
TAX_CODES = {"SSF": "SSF", "RMF": "RMF", "PV": "RMF", "PV1": "RMF", "PV2": "RMF", "PV3": "RMF",
             "TESG": "ThaiESG", "TESGX": "ThaiESGX", "LTF": "LTF"}

# Theme and region keyword rules (English names, master-fund names, Thai names).
# First match wins, so the most specific rules come first.
THEMES = [
    ("Gold", ["gold fund", "gold etf", "gold trust", "gold ", "gold)", "physical gold", "ทองคำ"]),
    ("Technology", ["technology", "tech", "digital", "innovation", "semiconductor", "robot", "artificial intelligence",
                    "ai ", "ai)", "internet", "cyber", "cloud", "disruptive", "nasdaq", "fintech", "blockchain",
                    "metaverse", "เทคโนโลยี", "ดิจิทัล"]),
    ("Healthcare", ["health", "biotech", "pharma", "medical", "longevity", "ageing", "aging", "genomic", "เฮลท์แคร์", "สุขภาพ"]),
    ("Clean Energy & Climate", ["clean", "climate", "carbon", "renewable", "positive change", "energy transition",
                                "green", "พลังงานสะอาด"]),
    ("Energy & Resources", ["energy", "oil", "natural resource", "mining", "commodit", "พลังงาน", "น้ำมัน"]),
    ("Infrastructure", ["infrastructure", "infra", "โครงสร้างพื้นฐาน"]),
    ("Property & REIT", ["property", "reit", "real estate", "อสังหา", "รีท"]),
    ("Financials", ["financial", "banks", "banking", "การเงิน"]),
    ("Consumer", ["consumer", "luxury", "brand", "ผู้บริโภค"]),
    ("Private Assets", ["private equity", "private credit", "private fund", "private market", "pe k", "limited partnership"]),
    ("Dividend", ["dividend", "hidiv", "high div", "ปันผล"]),
    ("Small & Mid Cap", ["small cap", "smallcap", "mid cap", "small-mid", "smid", "small and mid"]),
]
REGIONS = [
    ("Vietnam", ["vietnam", "เวียดนาม"]), ("India", ["india", "อินเดีย"]),
    ("China", ["china", "chinese", "a-share", "a share", "hong kong", "shanghai", "shenzhen", "จีน"]),
    ("Japan", ["japan", "topix", "nikkei", "ญี่ปุ่น"]), ("Korea", ["korea", "เกาหลี"]),
    ("Taiwan", ["taiwan", "ไต้หวัน"]),
    ("Latin America", ["latin america", "latam", "brazil", "ละตินอเมริกา"]),
    ("US", ["u.s.", "us ", "us)", "usa", "america", "s&p 500", "s&p500", "us500", "nasdaq", "สหรัฐ", "อเมริกา"]),
    ("Europe", ["europe", "euro ", "eurozone", "ยุโรป"]),
    ("ASEAN", ["asean", "อาเซียน"]),
    ("Emerging Markets", ["emerging", "ตลาดเกิดใหม่"]),
    ("Asia", ["asia", "pacific", "เอเชีย"]),
    ("Global", ["global", "world", "acwi", "international", "โกลบอล", "ทั่วโลก"]),
    ("Thailand", ["thai ", "thailand", "set50", "set 50", "set100", "ประเทศไทย"]),
]


COUNTRY_FLAG = {"3": "Thailand", "1": "Global", "4": "Thailand + Global"}  # SEC invest_country_flag


def _rx(words):
    import re
    eng = [w for w in words if w.isascii()]
    thai = [w for w in words if not w.isascii()]
    rx = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in eng) + r")") if eng else None
    return rx, thai


THEME_RX = [(label, _rx(words)) for label, words in THEMES]
REGION_RX = [(label, _rx(words)) for label, words in REGIONS]


def classify(name_en, abbr, name_th, master, country_flag):
    """Theme and region from names (word-start matching, so 'Goldman' is not gold)."""
    text = f" {name_en} {master} {abbr} ".lower().replace("–", " ").replace("_", " ")
    th = f"{name_th} {master}"
    def first(rules):
        for label, (rx, thai) in rules:
            if (rx and rx.search(text)) or any(w in th for w in thai):
                return label
        return ""
    region = first(REGION_RX) or COUNTRY_FLAG.get(str(country_flag or ""), "")
    return first(THEME_RX), region


def fetch_funds():
    cached = read(DATA / "funds.json")
    if cached and cached.get("v") == 3:
        age = dt.datetime.now(BKK) - dt.datetime.fromisoformat(cached["updated"])
        if age < dt.timedelta(days=6):
            log(f"Fund list: up to date ({len(cached['funds'])} funds, refreshed weekly)")
            return {f["id"]: f for f in cached["funds"]}
    log("Fund list …")
    rows = []
    for status in ("Registered", "IPO"):
        rows += get_all("/general-info/profiles", {"fund_status": status})
    log("Fund types (SEC specifications) …")
    specs = {}
    for s in get_all("/general-info/specifications", {}):
        specs.setdefault((s.get("proj_id"), s.get("fund_class_name") or "main"), set()).add(s.get("spec_code"))
    funds = build_funds(rows, specs)
    if len(funds) < 500:
        old = read(DATA / "funds.json")
        if old:
            log(f"  only {len(funds)} funds came back — keeping previous list")
            return {f["id"]: f for f in old["funds"]}
    write(DATA / "funds.json", {"v": 3, "updated": dt.datetime.now(BKK).isoformat(timespec="minutes"),
                                "funds": sorted(funds.values(), key=lambda x: x["abbr"])})
    log(f"  {len(funds)} active funds")
    return funds


STYLE = {"AM": "Active", "AN": "Active", "PM": "Passive (tracks an index)", "PN": "Passive (tracks an index)",
         "BH": "Buy and hold", "OT": "Other"}
FX = [("dynamic", "Dynamic hedging (0–105%)"), ("fully", "Fully hedged (95–105%)"),
      ("ไม่ป้องกัน", "Unhedged"), ("ชนิดหน่วย", "Set per share class")]
COUNTRY = {"ลักเซมเบิร์ก": "Luxembourg", "ไอร์แลนด์": "Ireland", "สหรัฐอเมริกา": "United States",
           "สิงคโปร์": "Singapore", "ฮ่องกง": "Hong Kong", "สหราชอาณาจักร": "United Kingdom",
           "ญี่ปุ่น": "Japan", "ฝรั่งเศส": "France", "เกาหลีใต้": "South Korea", "จีน": "China"}


def plain(html, limit=700):
    import re, html as h
    t = h.unescape(re.sub(r"<[^>]+>", " ", html or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + " …"


def build_funds(rows, specs):
    funds = {}
    for r in rows:
        pid = r.get("proj_id")
        if not pid or r.get("fund_status") not in ("Registered", "IPO"):
            continue
        master = r.get("feederfund_master_fund") or ""
        f = funds.setdefault(pid, {
            "id": pid,
            "abbr": r.get("proj_abbr_name") or pid,
            "th": r.get("proj_name_th") or "",
            "en": r.get("proj_name_en") or "",
            "amc": (r.get("comp_name_en") or "").replace(" ASSET MANAGEMENT", "").replace(" COMPANY", "").replace(" LIMITED", "").replace(" PUBLIC", "").title().strip(),
            "amc_th": r.get("comp_name_th") or "",
            "cat": CATEGORY.get(r.get("policy_desc") or "", "Other"),
            "master": master,
            "status": r.get("fund_status"),
            "since": r.get("init_date") or r.get("regis_date") or "",
            "style": STYLE.get(r.get("management_style") or "", ""),
            "fx": next((v for k, v in FX if k in (r.get("exchange_rate_protection_policy") or "")), ""),
            "master_country": COUNTRY.get(r.get("feederfund_country") or "", r.get("feederfund_country") or ""),
            "policy": plain(r.get("investment_policy_desc")),
            "classes": {},
        })
        if master and not f["master"]:
            f["master"] = master
        theme, region = classify(f["en"], f["abbr"], f["th"], f["master"], r.get("invest_country_flag"))
        f["theme"], f["region"] = theme, region
        cls = r.get("fund_class_name") or "main"
        codes = specs.get((pid, cls), set()) | specs.get((pid, "main"), set())
        types = sorted({TYPE_CODES[c] for c in codes if c in TYPE_CODES})
        tax = next((TAX_CODES[c] for c in ("TESGX", "TESG", "SSF", "RMF", "PV", "PV1", "PV2", "PV3", "LTF") if c in codes), "")
        if not tax:  # fall back to the class's own label / name
            label = f"{r.get('fund_class_tax_incentive_type') or ''} {cls} {f['abbr']}".upper()
            tax = ("ThaiESGX" if "ESGX" in label else "ThaiESG" if "ESG" in label and "THAI" in label
                   else "SSF" if "SSF" in label else "RMF" if "RMF" in label else "")
        if "Gold" in types:
            f["theme"] = "Gold"
        f["classes"][cls] = {"tax": tax, "types": types, "detail": r.get("fund_class_detail") or "",
                             "who": plain(r.get("fund_class_description"), 160), "isin": r.get("fund_class_isin_code") or ""}
    return funds


def fetch_navs(days, start=None, until=None):
    today = dt.datetime.now(BKK).date()
    start = dt.date.fromisoformat(start) if start else today - dt.timedelta(days=days)
    today = min(today, dt.date.fromisoformat(until)) if until else today
    log(f"NAV {start} → {today} …")
    windows, d = [], start
    while d <= today:  # one-week windows, fetched in parallel
        end = min(d + dt.timedelta(days=6), today)
        windows.append((d, end))
        d = end + dt.timedelta(days=1)

    def one(win):
        a, b = win
        rows = get_all("/daily-info/nav", {"start_nav_date": a.isoformat(), "end_nav_date": b.isoformat()})
        by_date = {}
        for r in rows:
            nd, nav = (r.get("nav_date") or "")[:10], num(r.get("last_val"))
            if not nd or nav is None or nav <= 0:
                continue
            cls = r.get("fund_class_name") or "main"
            by_date.setdefault(nd, {})[(r["proj_id"], cls)] = [
                r["proj_id"], cls, nav, num(r.get("net_asset")),
                num(r.get("sell_price")), num(r.get("buy_price"))]
        changed = sum(write(DAILY / f"{nd}.json", {"date": nd, "rows": sorted(v.values())})
                      for nd, v in by_date.items())
        log(f"  {a} → {b}: {len(rows)} rows, {len(by_date)} dates, {changed} file(s) updated")
        return len(by_date)

    with ThreadPoolExecutor(max_workers=min(WORKERS, len(windows))) as pool:
        total = sum(pool.map(one, windows))
    log(f"  done: {total} NAV dates")


# ------------------------------------------------------------------ factsheet
# Monthly fund factsheet data: fees, official returns, volatility, peer average,
# benchmark, risk level. Refreshed weekly (AMCs publish on different days).
FEE_KEYS = [("Management Fee", "mgmt"), ("Total Fee", "ter"), ("Front-end", "front"),
            ("Back-end", "back"), ("SWITCHING IN", "swin"), ("SWITCHING OUT", "swout")]
PERF_TYPES = {"ผลตอบแทนกองทุนรวม": "r", "ผลตอบแทนตัวชี้วัด": "bm",
              "ค่าเฉลี่ยในกลุ่มเดียวกัน": "peer", "ความผันผวนของกองทุนรวม": "sd"}
PERIODS = {"year to date": "ytd", "1 year": "1y", "3 years": "3y", "5 years": "5y", "10 years": "10y"}


def latest_rows(rows, by_class=True):
    """Keep only each class's most recent factsheet month."""
    newest = {}
    for r in rows:
        k = (r.get("fund_class_name") or "main") if by_class else "*"
        if r.get("start_date", "") > newest.get(k, ""):
            newest[k] = r["start_date"]
    return [r for r in rows if r.get("start_date") == newest[(r.get("fund_class_name") or "main") if by_class else "*"]]


def fetch_factsheet_fund(pid, since):
    out = {}
    q = {"proj_id": pid, "start_date": since}
    for r in latest_rows(get_all("/factsheet/fees", q)):
        c = out.setdefault(r.get("fund_class_name") or "main", {"asof": r["start_date"]})
        desc = r.get("fee_type_desc") or ""
        for word, key in FEE_KEYS:
            if word.lower() in desc.lower():
                c[key] = num(r.get("actual_value"))
                if key in ("mgmt", "ter"):
                    c[key + "_max"] = num(r.get("rate"))
    for r in latest_rows(get_all("/factsheet/performance", q)):
        t, p = PERF_TYPES.get(r.get("performance_type_desc") or ""), PERIODS.get(r.get("reference_period") or "")
        if t and p:
            c = out.setdefault(r.get("fund_class_name") or "main", {"asof": r["start_date"]})
            c[f"{t}{p}"] = num(r.get("performance_value"))
    risk = latest_rows(get_all("/factsheet/risk-spectrum", q), by_class=False)
    rs = next((r.get("risk_spectrum") for r in risk if r.get("risk_spectrum")), None)
    if rs:
        for c in out.values():
            c["risk"] = rs.replace("RS", "")
        out.setdefault("*", {})["risk"] = rs.replace("RS", "")
    for c in out.values():
        for p in PERIODS.values():  # a 0.00% return with no volatility = fund too young for that period
            if c.get(f"r{p}") == 0 and c.get(f"sd{p}") in (None, 0):
                c[f"r{p}"] = None
        for k in [k for k, v in c.items() if v is None]:
            del c[k]
    return pid, out


def fetch_factsheets(funds, force=False):
    path = DATA / "factsheet.json"
    cached = read(path)
    if cached and not force:
        age = dt.datetime.now(BKK) - dt.datetime.fromisoformat(cached["updated"])
        if age < dt.timedelta(days=6):
            log(f"Factsheets: up to date ({len(cached['funds'])} funds, refreshed weekly)")
            return
    since = (dt.datetime.now(BKK).date() - dt.timedelta(days=75)).isoformat()
    part_path = DATA / "factsheet.partial.json"
    part = read(part_path) or {}
    result = part.get("funds", {}) if part.get("since") == since else {}
    tried = set(part.get("tried", [])) if part.get("since") == since else set()
    ids = [i for i in sorted(funds) if i not in tried]
    log(f"Factsheets (fees, returns, risk): {len(ids)} funds to fetch" + (f", {len(tried)} already done" if tried else ""))

    def safe(i):
        try:
            return fetch_factsheet_fund(i, since)
        except Exception as e:
            log(f"  skipped {i}: {e}")
            return i, None
    done, failed = 0, 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for pid, data in pool.map(safe, ids):
            done += 1
            if data is None:
                failed += 1
            else:
                tried.add(pid)
                if data:
                    result[pid] = data
            if done % 250 == 0:
                log(f"  {done}/{len(ids)}")
                write(part_path, {"since": since, "tried": sorted(tried), "funds": result})
    if failed:
        write(part_path, {"since": since, "tried": sorted(tried), "funds": result})
        log(f"  {failed} funds failed — they will be retried on the next run")
    elif part_path.exists():
        part_path.unlink()
    if len(result) < 300 and cached:
        log(f"  only {len(result)} factsheets came back — keeping previous data")
        return
    write(path, {"updated": dt.datetime.now(BKK).isoformat(timespec="minutes"), "funds": result})
    log(f"  {len(result)} funds with factsheet data")


# ------------------------------------------------------------------ dividends
def fetch_dividends():
    """All dividend payouts ever reported (about 45 calls) + each class's current dividend policy."""
    log("Dividends …")
    rows = get_all("/daily-info/dividend-history", {})
    payouts = sorted({(r["proj_id"], r.get("class_abbr_name") or "main", (r.get("book_close_date") or "")[:10],
                       (r.get("dividend_date") or "")[:10], num(r.get("dividend_value")))
                      for r in rows if r.get("proj_id") and r.get("book_close_date") and num(r.get("dividend_value"))})
    since = (dt.datetime.now(BKK).date() - dt.timedelta(days=75)).isoformat()
    pol_rows = get_all("/factsheet/dividend-policy", {"start_date": since})
    newest, policy = {}, {}
    for r in sorted(pol_rows, key=lambda x: x.get("start_date") or ""):
        k = (r["proj_id"], r.get("fund_class_name") or "main")
        newest[k] = r.get("dividend_policy")
    for (pid, cls), v in newest.items():
        policy.setdefault(pid, {})[cls] = v
    old = read(DATA / "dividends.json")
    if old and len(payouts) < len(old.get("payouts", [])) * 0.8:
        log(f"  only {len(payouts)} payouts came back — keeping previous data")
        return
    write(DATA / "dividends.json", {"updated": dt.datetime.now(BKK).isoformat(timespec="minutes"),
                                    "payouts": [list(x) for x in payouts], "policy": policy})
    log(f"  {len(payouts)} payouts, policy for {len(policy)} funds")


def norm(s):
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def match_class(name, classes, abbr):
    """Map a dividend record's class name onto the NAV class names of the same fund."""
    if name in classes:
        return name
    n = norm(name)
    for c in classes:
        if norm(c) == n:
            return c
    if len(classes) == 1:
        return next(iter(classes))
    if "main" in classes and n == norm(abbr):
        return "main"
    return None


# ------------------------------------------------------------------ build
def pct(a, b):
    return round((a / b - 1) * 100, 2) if a and b else None


def build():
    funds = {f["id"]: f for f in (read(DATA / "funds.json") or {"funds": []})["funds"]}
    fs = (read(DATA / "factsheet.json") or {"funds": {}})["funds"]
    dv = read(DATA / "dividends.json") or {"payouts": [], "policy": {}}
    files = sorted(DAILY.glob("*.json"))
    if not files:
        sys.exit("ERROR: no data yet — run `python update.py fetch` first.")
    hist, extra = {}, {}  # (pid, cls) -> [[date, nav, aum], …]
    for fp in files:
        day = read(fp)
        for pid, cls, nav, aum, *rest in day["rows"]:
            hist.setdefault((pid, cls), []).append([day["date"], nav, aum])
            extra[(pid, cls)] = rest  # offer/bid from the fund's latest date
    last_day = read(files[-1])

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "data" / "h").mkdir(parents=True)

    def nav_on_or_before(series, target):
        best = None
        for d, v, _ in series:
            if d <= target:
                best = v
            else:
                break
        return best

    latest, per_fund, per_div = [], {}, {}
    newest = last_day["date"]
    today = dt.datetime.now(BKK).date().isoformat()
    classes_of = {}
    for (pid, cls) in hist:
        classes_of.setdefault(pid, set()).add(cls)
    divs = {}  # (pid, cls) -> [[book_close, pay_date, baht_per_unit], …]
    for pid, name, bc, pay, val in dv["payouts"]:
        cls = match_class(name, classes_of.get(pid, set()), funds.get(pid, {}).get("abbr", ""))
        if cls:
            divs.setdefault((pid, cls), []).append([bc, pay, val])
    for (pid, cls), s in hist.items():
        s.sort()
        d, nav, aum = s[-1]
        if d < (dt.date.fromisoformat(newest) - dt.timedelta(days=14)).isoformat():
            continue  # stopped reporting
        ld = dt.date.fromisoformat(d)
        ago = lambda **k: nav_on_or_before(s, (ld - dt.timedelta(**k)).isoformat())
        # total-return index: add each dividend back on the first NAV date on/after book close
        dl = sorted(divs.get((pid, cls), []))
        tri, tr, j, applied = [], 1.0, 0, False
        while j < len(dl) and dl[j][0] <= s[0][0]:
            j += 1
        for i, (dd, v, _) in enumerate(s):
            if i:
                add = 0.0
                while j < len(dl) and dl[j][0] <= dd:
                    add += dl[j][2]; j += 1
                applied = applied or add > 0
                tr *= (v + add) / s[i - 1][1]
            tri.append([dd, tr, None])
        tago = lambda **k: nav_on_or_before(tri, (ld - dt.timedelta(**k)).isoformat())
        ttm = sum(x[2] for x in dl if (ld - dt.timedelta(days=365)).isoformat() < x[0] <= d)
        past = [x for x in dl if x[0] <= today]
        nxt = [x for x in dl if x[0] > today or (x[1] or "") >= today]
        pol = (dv["policy"].get(pid) or {})
        policy = pol.get(cls) or (pol.get("main") if len(pol) == 1 else None)
        divinfo = {"yld": round(ttm / nav * 100, 2) if ttm and nav else None,
                   "ttm": round(ttm, 4) if ttm else None,
                   "dlast": past[-1] if past else None, "dnext": nxt[0] if nxt else None,
                   "dn": len(dl) or None, "dpol": policy}
        if applied:
            divinfo.update({"tw1": pct(tr, tago(days=7)), "tm1": pct(tr, tago(days=30)), "tm3": pct(tr, tago(days=91)),
                            "tm6": pct(tr, tago(days=182)), "ty1": pct(tr, tago(days=365)),
                            "tytd": pct(tr, nav_on_or_before(tri, f"{ld.year - 1}-12-31"))})
        if dl:
            per_div.setdefault(pid, {})[cls] = dl
        f = funds.get(pid, {})
        ex = extra.get((pid, cls))
        fsf = fs.get(pid, {})
        fx = fsf.get(cls) or (fsf.get("main") if len(fsf) <= 2 else None) or {}
        fx = {**({"risk": fsf["*"]["risk"]} if "*" in fsf else {}), **fx}
        latest.append({
            **{k: v for k, v in fx.items()},
            "id": pid, "cls": cls, "abbr": f.get("abbr", pid),
            "name": cls if cls != "main" else f.get("abbr", pid),
            "en": f.get("en", ""), "th": f.get("th", ""),
            "amc": f.get("amc", ""), "cat": f.get("cat", "Other"),
            "tax": ((f.get("classes") or {}).get(cls) or {}).get("tax", ""),
            "types": ((f.get("classes") or {}).get(cls) or {}).get("types", []),
            "theme": f.get("theme", ""), "region": f.get("region", ""),
            "master": (f.get("master") or "").replace("กองทุน ", "").strip(),
            "date": d, "nav": nav, "aum": aum,
            "sell": ex[0] if ex else None, "buy": ex[1] if ex else None,
            "d1": pct(nav, s[-2][1]) if len(s) > 1 else None,
            "w1": pct(nav, ago(days=7)), "m1": pct(nav, ago(days=30)),
            "m3": pct(nav, ago(days=91)), "m6": pct(nav, ago(days=182)),
            "y1": pct(nav, ago(days=365)),
            "ytd": pct(nav, nav_on_or_before(s, f"{ld.year - 1}-12-31")),
            **{k: v for k, v in divinfo.items() if v is not None},
        })
        per_fund.setdefault(pid, {})[cls] = [[x[0], x[1], round(x[2]) if x[2] else None] for x in s]

    for pid, classes in per_fund.items():
        f = funds.get(pid, {})
        info = {k: f.get(k, "") for k in ("since", "style", "fx", "master_country", "policy", "amc_th", "en", "th")}
        info["classes"] = {c: {k: v for k, v in (m or {}).items() if k in ("detail", "who", "isin")}
                           for c, m in (f.get("classes") or {}).items()}
        write(SITE / "data" / "h" / f"{pid}.json", {"info": info, "series": classes, "divs": per_div.get(pid, {})})
    latest.sort(key=lambda x: x["name"])
    write(SITE / "data" / "latest.json", {
        "built": dt.datetime.now(BKK).isoformat(timespec="minutes"),
        "nav_date": newest, "first_date": files[0].stem,
        "days": len(files), "rows": latest})
    page = (ROOT / "index.html").read_text(encoding="utf-8")
    if "<!doctype" not in page[:200].lower():
        page = ('<!doctype html>\n<html lang="th">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                '</head>\n<body>\n' + page + '\n</body>\n</html>\n')
    (SITE / "index.html").write_text(page, encoding="utf-8")
    (SITE / ".nojekyll").write_text("")
    log(f"Site built: {len(latest)} fund classes, {len(per_fund)} funds, NAV date {newest}, {len(files)} days of history")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["fetch", "build", "factsheets"])
    ap.add_argument("--factsheets", action="store_true", help="force a factsheet refresh")
    ap.add_argument("--days", type=int, default=int(os.environ.get("DAYS") or 7))
    ap.add_argument("--from", dest="start", default=os.environ.get("FROM_DATE") or None,
                    help="YYYY-MM-DD: download history from this date (overrides --days)")
    ap.add_argument("--to", dest="until", default=os.environ.get("TO_DATE") or None,
                    help="YYYY-MM-DD: stop at this date (to fill old history in chunks)")
    a = ap.parse_args()
    if a.step == "fetch":
        if not a.start and not list(DAILY.glob("*.json")) and a.days < 400:
            log("First run: no history yet, downloading the last 400 days (about 30 minutes)")
            a.days = 400
        funds = fetch_funds()
        fetch_factsheets(funds, force=a.factsheets)
        fetch_dividends()
        fetch_navs(a.days, a.start, a.until)
    elif a.step == "factsheets":
        fetch_factsheets(fetch_funds(), force=True)
    else:
        build()
