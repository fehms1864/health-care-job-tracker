# Healthcare job tracker

Daily tracker of new roles at ~215 watchlist employers in the UK, the Netherlands and the Middle East.

- **Site:** `index.html`, served by GitHub Pages. It reads `data/jobs.json`.
- **Daily check:** `.github/workflows/daily.yml` runs `scripts/fetch_jobs.py` twice a day, at about 05:17 and 12:43 UTC. It commits fresh results and opens an issue listing roles that are new since the previous check. GitHub emails you about each issue.
- **Companies:** `data/companies.json`. Each company has a `region` (UK / NL / ME) and a `source`, which is its job board (greenhouse, ashby, lever, workable, smartrecruiters, recruitee, workday, eightfold), a careers `page` to watch, or `null` for check-by-hand.
- **Rules:** `scripts/rules.py`. This file holds the title exclusions (engineering, analytics, finance, clinical, seniority), the Dutch/Arabic requirement check, location matching and fit scoring.
- **Run now:** Actions tab → *Daily job check* → *Run workflow*.
