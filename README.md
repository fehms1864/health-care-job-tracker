# Healthcare job tracker

Daily tracker of new roles at ~215 watchlist employers in the UK, the Netherlands and the Middle East.

- **Site:** `index.html`, served by GitHub Pages. It reads `data/jobs.json`.
- **Twice-daily check:** `.github/workflows/daily.yml` runs `scripts/fetch_jobs.py` twice a day, at about 05:17 and 12:43 UTC. It commits fresh results and opens an issue listing roles that are new since the previous check. GitHub emails you about each issue.
- **Companies:** `data/companies.json`. Each company has a `region` (UK / NL / ME) and a `source`, which is its job board (greenhouse, ashby, lever, workable, smartrecruiters, recruitee, workday, eightfold), a careers `page` to watch, or `null` for check-by-hand.
- **Rules:** `scripts/rules.py`. This file holds the title exclusions (engineering, analytics, finance, clinical, seniority), the Dutch/Arabic requirement check, location matching and fit scoring.
- **Run now:** Actions tab → *Daily job check* → *Run workflow*.

### How each company is read (Oct 2026 update)
- **Job-board feeds:** Greenhouse, Ashby, Lever, Workable, SmartRecruiters, Recruitee, Workday, Eightfold, Teamtailor and BambooHR.
- **Large-employer job systems** (`scripts/adapters.py`): Jibe/iCIMS (ZS, M42, Publicis), Phenom (BCG, Siemens Healthineers), SuccessFactors (Wipro, EY), Zenats (Vezeeta, Altibbi), Microsoft, Amazon, Atlassian, TomTom, HCA UK and Bupa Arabia.
- **Careers pages** (`scripts/pages.py`): the reader pulls each job's JobPosting data and opens JavaScript-only pages in a headless browser.
- **Email alerts:** companies marked `"alert": true` in `data/companies.json` (MBB, Big 4, big tech) block automated reading, so the site lists them under "Set up email alerts".
- **Language:** roles requiring Dutch or French are removed. Roles requiring Arabic are tagged and hidden by default.
- **Visa:** roles that rule out sponsorship, or require an existing right to work, are tagged "no sponsorship".
- `scripts/probe.py` (Actions → *Probe careers sites*) is a diagnostic. It opens careers pages and reports which job system each one uses.
