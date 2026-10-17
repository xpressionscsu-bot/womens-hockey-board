#!/usr/bin/env python3
"""Fetch the USCHO Division I women's poll and the WCHA women's standings,
then write them to a JSON file the website reads.

Safe by design: if one source fails, the last good data for that source stays
in the file and is marked "stale", so the site never goes blank.

Usage:
    python scraper/scrape.py --out site/data.json
    python scraper/scrape.py --poll-html poll.html --standings-html st.html --out /tmp/data.json
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

# The WCHA standings page ID changes each season. Override with the WCHA_URL
# environment variable (a GitHub Actions variable works) if it stops matching.
WCHA_URL = os.environ.get("WCHA_URL") or "https://wcha.com/standings.aspx?standings=7&path=whockey"
USCHO_URL = os.environ.get("USCHO_URL") or "https://www.uscho.com/rankings/d-i-womens-poll/"
UA = "Mozilla/5.0 (compatible; WomensHockeyBoard/1.0; personal project)"

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


# ---------------------------------------------------------------- helpers
def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def to_int(text, default=None):
    m = re.search(r"-?\d+", clean(text))
    return int(m.group()) if m else default


def to_float(text, default=None):
    try:
        return float(clean(text))
    except ValueError:
        return default


def split_pair(text, sep="-"):
    """'19-14' -> (19, 14). Returns (None, None) when it does not parse."""
    parts = [p for p in clean(text).split(sep)]
    nums = [to_int(p) for p in parts]
    return nums if all(n is not None for n in nums) else None


def record_to_wlt(text):
    nums = split_pair(text)
    if not nums or len(nums) != 3:
        return {"w": None, "l": None, "t": None}
    return {"w": nums[0], "l": nums[1], "t": nums[2]}


def header_cells(table):
    row = table.select_one("thead tr:last-of-type") or table.find("tr")
    return [clean(c.get_text()) for c in row.find_all(["th", "td"])] if row else []


def body_rows(table):
    rows = table.select("tbody tr") or table.find_all("tr")[1:]
    return [r for r in rows if r.find_all(["td", "th"])]


def team_text(cell):
    link = cell.find("a")
    return clean((link or cell).get_text())


# ----------------------------------------------------------------- WCHA
def parse_wcha(html):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    m = re.search(r"(\d{4}-\d{2})", title.get_text() if title else "")
    season = m.group(1) if m else None

    for table in soup.find_all("table"):
        headers = header_cells(table)
        if "W-L-T" in headers and "Overall Record" in headers:
            break
    else:
        raise ValueError("WCHA standings table not found (page layout may have changed)")

    def idx(name):
        return headers.index(name) if name in headers else None

    col = {
        "team": idx("Team"), "pts": idx("PTS"), "ptpct": idx("PT%"), "gp": idx("GP"),
        "rec": idx("W-L-T"), "owol": idx("OW-OL"), "sow": idx("SOW"),
        "cgfga": idx("WCHA GF-GA"), "ogp": idx("Overall GP"),
        "orec": idx("Overall Record"), "ogfga": idx("GF-GA"),
    }
    missing = [k for k, v in col.items() if v is None]
    if missing:
        raise ValueError("WCHA table is missing columns: " + ", ".join(missing))

    rows = []
    for tr in body_rows(table):
        cells = tr.find_all(["td", "th"])
        if len(cells) <= max(col.values()):
            continue
        txt = lambda key: clean(cells[col[key]].get_text())
        gf_ga = split_pair(txt("cgfga")) or [None, None]
        ow_ol = split_pair(txt("owol")) or [None, None]
        o_gf_ga = split_pair(txt("ogfga")) or [None, None]
        rec = record_to_wlt(txt("rec"))
        orec = record_to_wlt(txt("orec"))
        rows.append({
            "rank": len(rows) + 1,
            "team": team_text(cells[col["team"]]),
            "conference": {
                "gp": to_int(txt("gp")), "pts": to_int(txt("pts")), "pt_pct": to_float(txt("ptpct")),
                **rec, "ow": ow_ol[0], "ol": ow_ol[1], "sow": to_int(txt("sow")),
                "gf": gf_ga[0], "ga": gf_ga[1],
            },
            "overall": {"gp": to_int(txt("ogp")), **orec, "gf": o_gf_ga[0], "ga": o_gf_ga[1]},
        })

    if len(rows) < 6:
        raise ValueError(f"Only found {len(rows)} WCHA teams; expected about 8")
    return {"season": season, "rows": rows}


# ---------------------------------------------------------------- USCHO
def parse_uscho(html):
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" "))

    poll_date = None
    m = re.search(r"Poll\s*[-–—]\s*((?:%s)\.?\s+\d{1,2},\s+\d{4})" % MONTHS, text)
    if m:
        poll_date = dt.datetime.strptime(re.sub(r"\.", "", m.group(1)), "%B %d, %Y").date().isoformat()

    for table in soup.find_all("table"):
        headers = [h.lower() for h in header_cells(table)]
        if any(h.startswith("team") for h in headers) and any(h.startswith("pts") or h == "points" for h in headers):
            break
    else:
        raise ValueError("USCHO poll table not found (page may not have rendered)")

    def find(pred):
        for i, h in enumerate(headers):
            if pred(h):
                return i
        return None

    col = {
        "rank": find(lambda h: h in ("rnk", "rk", "rank", "#")),
        "team": find(lambda h: h.startswith("team")),
        "fpv": find(lambda h: "first" in h),
        "record": find(lambda h: h.startswith("rec")),
        "pts": find(lambda h: h.startswith("pts") or h == "points"),
        "last": find(lambda h: h.startswith("last")),
    }
    if col["team"] is None or col["pts"] is None:
        raise ValueError("USCHO poll table is missing the Team or Pts column")

    rows = []
    for tr in body_rows(table):
        cells = tr.find_all(["td", "th"])
        if len(cells) <= max(v for v in col.values() if v is not None):
            continue
        get = lambda key: clean(cells[col[key]].get_text()) if col[key] is not None else ""
        team = team_text(cells[col["team"]])
        fpv = to_int(get("fpv"), 0) if col["fpv"] is not None else 0
        # Some layouts put the first-place votes in the team cell: "Ohio State (20)".
        inline = re.search(r"\((\d+)\)\s*$", team)
        if inline:
            fpv = int(inline.group(1))
            team = clean(team[: inline.start()])
        last_text = get("last")
        rows.append({
            "rank": to_int(get("rank"), len(rows) + 1),
            "team": team,
            "first_place_votes": fpv or 0,
            "record": get("record") or None,
            "points": to_int(get("pts")),
            "last_rank": to_int(last_text) if re.search(r"\d", last_text) else None,
        })

    if len(rows) < 10:
        raise ValueError(f"Only found {len(rows)} poll rows; expected 15")
    return {"poll_date": poll_date, "rows": rows}


# -------------------------------------------------------------- fetching
def fetch_static(url):
    import requests
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_rendered(url):
    """USCHO builds its poll table with JavaScript, so load it in a real browser."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_selector("table tbody tr", timeout=30000)
        html = page.content()
        browser.close()
    return html


# ------------------------------------------------------------------ main
def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def core(section):
    return {k: v for k, v in (section or {}).items() if k not in ("updated_at", "status", "error")}


def refresh(name, old, build):
    """Return the section to store. Keeps the old data (marked stale) on failure."""
    try:
        data = build()
    except Exception as exc:  # noqa: BLE001 - any failure must not blank the site
        print(f"[{name}] FAILED: {exc}", file=sys.stderr)
        if old:
            return {**old, "status": "stale", "error": str(exc)[:300]}, False
        return {"status": "error", "error": str(exc)[:300], "rows": []}, False
    if old and old.get("status") == "ok" and core(old) == core(data):
        print(f"[{name}] no change")
        return old, True
    print(f"[{name}] updated ({len(data['rows'])} rows)")
    return {**data, "status": "ok", "updated_at": now_iso()}, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data.json")
    ap.add_argument("--poll-html", help="parse this saved file instead of fetching USCHO")
    ap.add_argument("--standings-html", help="parse this saved file instead of fetching the WCHA")
    args = ap.parse_args()

    out = Path(args.out)
    old = json.loads(out.read_text()) if out.exists() else {}

    def build_poll():
        html = Path(args.poll_html).read_text() if args.poll_html else fetch_rendered(USCHO_URL)
        return {"source": USCHO_URL, "name": "USCHO.com Division I Women's Poll", **parse_uscho(html)}

    def build_standings():
        html = Path(args.standings_html).read_text() if args.standings_html else fetch_static(WCHA_URL)
        return {"source": WCHA_URL, "name": "WCHA Women's Standings", **parse_wcha(html)}

    poll, poll_ok = refresh("poll", old.get("poll"), build_poll)
    standings, st_ok = refresh("standings", old.get("standings"), build_standings)

    new = {"poll": poll, "standings": standings}
    if json.dumps(new, sort_keys=True) != json.dumps({k: old.get(k) for k in new}, sort_keys=True):
        new["generated_at"] = now_iso()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {out}")
    else:
        print("data.json unchanged")

    # Fail the run only when there is nothing usable to show at all.
    if not poll.get("rows") and not standings.get("rows"):
        sys.exit(1)


if __name__ == "__main__":
    main()
