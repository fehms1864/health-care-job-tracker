"""One-off helper: for companies with no job feed yet, try likely board names on the common
job-board systems and report the ones that exist. Results go to data/discovery.json for review.
It never edits companies.json itself, because a matching name can belong to a different company."""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = requests.Session()
S.headers['User-Agent'] = 'Mozilla/5.0 (compatible; personal-job-tracker/1.0)'


def slugs(name):
    base = re.sub(r'\b(middle east|& africa|uk|nl|ltd|limited|group|health|healthcare)\b', '', name.lower())
    base = re.sub(r'\(.*?\)', '', base).strip()
    words = re.findall(r'[a-z0-9]+', base) or re.findall(r'[a-z0-9]+', name.lower())
    full = re.findall(r'[a-z0-9]+', name.lower())
    c = {''.join(words), '-'.join(words), ''.join(full), '-'.join(full), words[0] if words else ''}
    c |= {s + 'health' for s in (''.join(words),)} | {s + '-health' for s in (''.join(words),)}
    return [s for s in c if len(s) > 2]


def probe(slug):
    hits = []
    checks = [
        ('greenhouse', f'https://boards-api.greenhouse.io/v1/boards/{slug}', lambda d: d.get('name')),
        ('ashby', f'https://api.ashbyhq.com/posting-api/job-board/{slug}', lambda d: f"{len(d.get('jobs', []))} jobs"),
        ('lever', f'https://api.lever.co/v0/postings/{slug}?mode=json&limit=3',
         lambda d: ', '.join(j.get('text', '') for j in d[:3]) if isinstance(d, list) and d else None),
        ('workable', f'https://apply.workable.com/api/v1/widget/accounts/{slug}', lambda d: d.get('name')),
        ('smartrecruiters', f'https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=3',
         lambda d: ((d.get('content') or [{}])[0].get('company') or {}).get('name') if d.get('totalFound') else None),
        ('recruitee', f'https://{slug}.recruitee.com/api/offers/',
         lambda d: ((d.get('offers') or [{}])[0]).get('company_name') if d.get('offers') else None),
    ]
    for kind, url, info in checks:
        try:
            r = S.get(url, timeout=15)
            if r.status_code == 200 and 'json' in r.headers.get('content-type', ''):
                label = info(r.json())
                if label:
                    hits.append({'type': kind, 'token': slug, 'info': str(label)[:120]})
        except Exception:
            pass
    return hits


def main():
    cos = json.load(open(os.path.join(ROOT, 'data', 'companies.json')))
    todo = [c for c in cos if not c.get('source')]
    jobs = [(c['name'], s) for c in todo for s in slugs(c['name'])]
    with ThreadPoolExecutor(max_workers=12) as ex:
        res = list(ex.map(lambda x: (x[0], probe(x[1])), jobs))
    report = {}
    for name, hits in res:
        if hits:
            report.setdefault(name, []).extend(hits)
    json.dump(report, open(os.path.join(ROOT, 'data', 'discovery.json'), 'w'), indent=1)
    print(f'probed {len(todo)} companies / {len(jobs)} names; candidates for {len(report)}')
    for k, v in report.items():
        print(k, '->', v)


if __name__ == '__main__':
    main()
