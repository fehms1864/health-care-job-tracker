"""Diagnostic run (not part of the daily check).

For each company in data/probe_input.json:
  * `try`  - candidate job-board sources are fetched with the real adapters; reports counts + samples.
  * `urls` - careers pages are opened in a headless browser. Reports which job system the page uses
             (Workday, Greenhouse, SuccessFactors, iCIMS, Phenom, Eightfold, Teamtailor ...), the JSON
             requests the page makes, and whether job pages carry JobPosting structured data.
Writes data/probe_report.json and prints a compact summary.
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
import fetch_jobs as fj  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FP = {
    'workday': r'([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)',
    'greenhouse': r'(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)',
    'lever': r'jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)',
    'ashby': r'(?:jobs\.ashbyhq\.com|posting-api/job-board)/([A-Za-z0-9_.-]+)',
    'smartrecruiters': r'(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)|smartrecruiters\.com/v1/companies/([A-Za-z0-9_-]+)',
    'workable': r'apply\.workable\.com/(?:api/v\d/accounts/)?([A-Za-z0-9_-]+)',
    'recruitee': r'([a-z0-9-]+)\.recruitee\.com',
    'teamtailor': r'teamtailor',
    'personio': r'([a-z0-9-]+)\.jobs\.personio\.(?:de|com)',
    'icims': r'([a-z0-9-]+)\.icims\.com',
    'successfactors': r'successfactors\.(?:com|eu)|jobs\.sap\.com|rmkcdn|/sfcareer|career\d+\.sapsf',
    'oracle': r'([a-z0-9-]+)\.fa\.([a-z0-9-]+)\.oraclecloud\.com/hcmUI/CandidateExperience/[a-z-]+/sites/([A-Za-z0-9_]+)',
    'phenom': r'phenompeople|phenom\.com|/widgets\b',
    'avature': r'avature\.net',
    'eightfold': r'/api/apply/v2/jobs|eightfold\.ai|/api/pcsx/',
    'taleo': r'taleo\.net',
    'getro': r'getro\.com|api\.getro',
    'consider': r'consider\.com',
    'zenats': r'zenats',
    'comeet': r'comeet\.(?:co|com)',
    'bamboohr': r'([a-z0-9-]+)\.bamboohr\.com',
    'jobvite': r'jobs\.jobvite\.com/([A-Za-z0-9_-]+)',
    'pinpoint': r'pinpointhq\.com',
    'charliehr': r'charliehr\.com',
    'hibob': r'hibob\.com',
    'breezy': r'breezy\.hr',
    'join': r'join\.com/companies/([A-Za-z0-9_-]+)',
}
JOBISH = re.compile(r'/(job|jobs|vacanc|vacature|position|opening|posting|requisition|careers?/)[^?#]*\d|/j/|/o/', re.I)


def jsonld_jobs(html):
    out = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            d = json.loads(m.group(1).strip())
        except Exception:
            continue
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                if x.get('@type') in ('JobPosting', ['JobPosting']):
                    out.append(x.get('title'))
                stack.extend(v for k, v in x.items() if k in ('@graph', 'itemListElement', 'item'))
    return out


def render_probe(browser, url):
    res = {'url': url}
    ctx = browser.new_context(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                                         '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')
    page = ctx.new_page()
    reqs, jsons = [], []

    def on_resp(r):
        try:
            u = r.url
            reqs.append(u)
            ct = r.headers.get('content-type', '')
            if 'json' in ct and r.request.resource_type in ('xhr', 'fetch'):
                body = r.body()
                jsons.append((len(body), r.request.method, u[:300], (r.request.post_data or '')[:300],
                              body[:200].decode('utf8', 'replace')))
        except Exception:
            pass
    page.on('response', on_resp)
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(6000)
        try:
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)
        except Exception:
            pass
        html = page.content()
        res['final'] = page.url
        res['title'] = page.title()[:100]
        hrefs = page.eval_on_selector_all('a[href]', 'els => els.map(e => [e.href, (e.innerText||"").trim().slice(0,90)])')
        frames = [f.url for f in page.frames]
        blob = '\n'.join([html[:600000]] + [h for h, _ in hrefs] + frames + reqs)
        fps = {}
        for k, rx in FP.items():
            ms = re.findall(rx, blob, re.I)
            if ms:
                vals = sorted({'/'.join(x for x in (m if isinstance(m, tuple) else (m,)) if x) for m in ms})[:4]
                fps[k] = vals
        res['systems'] = fps
        res['jsonld_on_page'] = len(jsonld_jobs(html))
        jl = [(h, t) for h, t in hrefs if JOBISH.search(h) and len(t.split()) >= 2]
        seen, sample = set(), []
        for h, t in jl:
            if h not in seen:
                seen.add(h)
                sample.append((h, t))
        res['job_links'] = len(sample)
        res['job_link_sample'] = sample[:5]
        checks = []
        for h, t in sample[:2]:
            try:
                p2 = ctx.new_page()
                p2.goto(h, wait_until='domcontentloaded', timeout=30000)
                p2.wait_for_timeout(2500)
                checks.append({'link': h, 'jsonld': jsonld_jobs(p2.content())[:2]})
                p2.close()
            except Exception as e:
                checks.append({'link': h, 'error': str(e)[:80]})
        res['job_page_jsonld'] = checks
        res['json_requests'] = [dict(zip(('bytes', 'method', 'url', 'post', 'head'), j))
                                for j in sorted(jsons, reverse=True)[:6]]
    except Exception as e:
        res['error'] = f'{type(e).__name__}: {str(e)[:160]}'
    ctx.close()
    return res


def try_source(src):
    try:
        jobs = fj.fetch_source(src, ['UK', 'NL', 'ME'])
        locs = [j['location'] for j in jobs]
        return {'source': src, 'count': len(jobs),
                'in_region': sum(1 for l, j in zip(locs, jobs) if j['region'] or fj.rules.regions_in(l)),
                'sample': [(j['title'][:70], j['location'][:50]) for j in jobs[:4]]}
    except Exception as e:
        return {'source': src, 'error': f'{type(e).__name__}: {str(e)[:150]}'}


def main():
    items = json.load(open(os.path.join(ROOT, 'data', 'probe_input.json')))
    report = {}
    tries = [(it['name'], s) for it in items for s in it.get('try', [])]
    with ThreadPoolExecutor(8) as ex:
        for (name, _), r in zip(tries, ex.map(lambda x: try_source(x[1]), tries)):
            report.setdefault(name, {'tries': [], 'pages': []})['tries'].append(r)
    urls = [(it['name'], u) for it in items for u in it.get('urls', [])]
    if urls:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            for name, u in urls:
                report.setdefault(name, {'tries': [], 'pages': []})['pages'].append(render_probe(b, u))
            b.close()
    json.dump(report, open(os.path.join(ROOT, 'data', 'probe_report.json'), 'w'), indent=1, ensure_ascii=False)
    for name, r in report.items():
        print(f'## {name}')
        for t in r['tries']:
            print('  try', json.dumps(t['source']), '->', t.get('error') or f"{t['count']} jobs, {t['in_region']} in region {t['sample'][:2]}")
        for pg in r['pages']:
            print('  page', pg['url'], '->', pg.get('error') or
                  f"systems={pg.get('systems')} ldpage={pg.get('jsonld_on_page')} links={pg.get('job_links')} "
                  f"ldjob={[c.get('jsonld') for c in pg.get('job_page_jsonld', [])]}")


if __name__ == '__main__':
    main()
