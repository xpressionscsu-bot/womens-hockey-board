# Women's Hockey Board

A one-page site that shows the USCHO Division I women's poll and the WCHA women's standings.
A scraper writes both to `site/data.json`, and the page reads that file. A GitHub Actions
workflow re-runs the scraper on a schedule and publishes the site with GitHub Pages.

```
site/index.html            the page (reads data.json)
site/data.json             the data, also readable by anything else
scraper/scrape.py          fetches both sources and writes data.json
.github/workflows/update.yml   schedule + deploy
```

## Set it up (about 5 minutes)

1. Create a new GitHub repository and push this folder to the `main` branch.
2. In the repo, open **Settings > Pages** and set **Source** to **GitHub Actions**.
3. Open the **Actions** tab, choose **Update data and deploy site**, and click **Run workflow**.
4. When the run turns green, your site is at `https://<your-username>.github.io/<repo-name>/`.

The workflow then runs every day (standings) and several times on Monday and Tuesday (the poll).
To change the times, edit the `cron` lines in `.github/workflows/update.yml`. Times are in UTC.

## Check the first run

The scraper was tested against sample pages, not the live sites, so look at the first run in the
Actions tab. In the "Fetch poll and standings" step you should see `[poll] updated (15 rows)` and
`[standings] updated (8 rows)`.

If a source fails, the site keeps the last good data and shows a yellow "could not be refreshed"
note on that section. The log line starting with `FAILED` says which table it could not find.

## The JSON

`site/data.json` has two sections, `poll` and `standings`, each with `status` (`ok` or `stale`),
`updated_at`, `source`, and `rows`. Other tools can read it from
`https://<your-username>.github.io/<repo-name>/data.json`.

```json
{
  "poll": {
    "poll_date": "2026-10-12",
    "rows": [{ "rank": 1, "team": "Ohio State", "first_place_votes": 20,
               "record": "6-0-0", "points": 300, "last_rank": 2 }]
  },
  "standings": {
    "season": "2026-27",
    "rows": [{ "rank": 1, "team": "Ohio State",
               "conference": { "gp": 5, "pts": 12, "pt_pct": 0.8, "w": 4, "l": 1, "t": 0,
                               "ow": 0, "ol": 0, "sow": 0, "gf": 19, "ga": 14 },
               "overall": { "gp": 7, "w": 6, "l": 1, "t": 0, "gf": 23, "ga": 16 } }]
  }
}
```

## Things to know

- **New season:** the WCHA standings link has an ID (`standings=7`) that changes each season. In the
  repo go to **Settings > Secrets and variables > Actions > Variables**, add a variable named
  `WCHA_URL`, and paste the new standings link.
- **USCHO page:** the poll table is built with JavaScript, so the scraper opens the page in a headless
  browser (Playwright). If USCHO changes its page layout, the poll section will go stale until
  `parse_uscho` in `scraper/scrape.py` is updated.
- **Be polite:** the schedule fetches each page a few times a day. Check each site's terms of use
  before sharing the page widely.
- **Run it on your computer:** `pip install -r scraper/requirements.txt`,
  `python -m playwright install chromium`, then `python scraper/scrape.py`. To view the page, run
  `python -m http.server -d site` and open http://localhost:8000 (opening the file directly will
  not load the JSON).
