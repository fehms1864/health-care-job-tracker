"""Daily job check. Reads data/companies.json, pulls every company's job board, applies rules.py,
and writes data/jobs.json (plus data/pages.json for careers pages without a feed).

Run locally:  pip install requests && python scripts/fetch_jobs.py
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, quote

import requests

sys.path.insert(0, os.path.dirname(__file__))
import rules  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
TODAY = dt.date.today().isoformat()
NOW = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
UA = {'User-Agent': 'Mozilla/5.0 (compatible; personal-job-tracker/1.0)', 'Accept': 'application/json, text/html'}
S = requests.Session()
S.headers.update(UA)


def get(url, **kw):
    for attempt in range(3):
        try:
            r = S.get(url, timeout=30, **kw)
            if r.status_code in (429, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2)


def post(url, body):
    for attempt in range(3):
        try:
            r = S.post(url, json=body, timeout=30, headers={'Content-Type': 'application/json'})
            if r.status_code in (429, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, a):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if tag in ('p', 'li', 'br', 'div', 'h1', 'h2', 'h3', 'h4', 'tr'):
            self.out.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def text_of(h):
    if not h:
        return ''
    p = _Text()
    p.feed(html.unescape(h) if '&lt;' in h else h)
    return re.sub(r'[ \t\r\f\v]+', ' ', re.sub(r'\n\s*\n+', '\n', ''.join(p.out))).strip()


def tidy_location(loc):
    parts = [p.strip(' ,') for p in re.split(r'\s*[/|]\s*', loc or '')]
    out = []
    for p in parts:
        if p and not any(p.lower() == o.lower() or p.lower() in o.lower() for o in out):
            out = [o for o in out if o.lower() not in p.lower()] + [p]
    return ' / '.join(out)


def job(title, location, url, jid, desc=None, posted=None, region=None, detail=None):
    """Normalised job. `detail` is a zero-arg callable that returns the description when needed."""
    if isinstance(posted, str):
        posted = re.sub(r'^posted\s+', '', posted.strip(), flags=re.I)
    return {'title': (title or '').strip(), 'location': tidy_location(location), 'url': url, 'jid': str(jid),
            'desc': desc, 'posted': posted, 'region': region, '_detail': detail}


# ---------------- ATS readers ----------------
def greenhouse(token, eu=False):
    host = 'boards-api.eu.greenhouse.io' if eu else 'boards-api.greenhouse.io'
    d = get(f'https://{host}/v1/boards/{token}/jobs?content=true').json()
    out = []
    for j in d.get('jobs', []):
        loc = (j.get('location') or {}).get('name', '')
        offices = ' / '.join(o.get('name', '') + ' ' + (o.get('location') or '') for o in j.get('offices', []) or [])
        out.append(job(j.get('title'), f'{loc} | {offices}' if offices else loc, j.get('absolute_url'), j.get('id'),
                       text_of(j.get('content')), j.get('first_published') or j.get('updated_at')))
    return out


def ashby(token):
    d = get(f'https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false').json()
    out = []
    for j in d.get('jobs', []):
        if j.get('isListed') is False:
            continue
        locs = [j.get('location') or '']
        locs += [s.get('location', '') for s in j.get('secondaryLocations') or []]
        addr = ((j.get('address') or {}).get('postalAddress') or {}).get('addressCountry')
        if addr:
            locs.append(addr)
        out.append(job(j.get('title'), ' / '.join(x for x in locs if x), j.get('jobUrl'), j.get('id'),
                       j.get('descriptionPlain') or text_of(j.get('descriptionHtml')), j.get('publishedAt')))
    return out


def lever(token):
    out = []
    for host in ('api.lever.co', 'api.eu.lever.co'):
        try:
            d = get(f'https://{host}/v0/postings/{token}?mode=json').json()
        except Exception:
            continue
        if not isinstance(d, list):
            continue
        for j in d:
            cat = j.get('categories') or {}
            loc = ' / '.join([cat.get('location') or ''] + (cat.get('allLocations') or []) + [j.get('country') or ''])
            desc = (j.get('descriptionPlain') or '') + '\n' + '\n'.join(
                (l.get('text', '') + ': ' + text_of(l.get('content', ''))) for l in j.get('lists') or [])
            ts = j.get('createdAt')
            out.append(job(j.get('text'), loc, j.get('hostedUrl'), j.get('id'), desc,
                           dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).isoformat() if ts else None))
        if out:
            break
    return out


def workable(token):
    """Workable's v3 careers API (the older widget API now returns empty job lists)."""
    out, body, pages = [], {'query': '', 'location': [], 'department': [], 'worktype': [], 'remote': []}, 0
    while pages < 20:
        r = S.post(f'https://apply.workable.com/api/v3/accounts/{token}/jobs', json=body, timeout=30)
        r.raise_for_status()
        d = r.json()
        for j in d.get('results', []):
            locs = [j.get('location') or {}] + (j.get('locations') or [])
            text = ' / '.join(', '.join(x for x in (l.get('city'), l.get('region'), l.get('country')) if x) for l in locs)
            ccs = {(l.get('countryCode') or '').lower() for l in locs}
            region = next((rules.COUNTRY_CODE[c] for c in ccs if c in rules.COUNTRY_CODE), None)
            sc = j.get('shortcode')

            def detail(sc=sc):
                x = get(f'https://apply.workable.com/api/v2/accounts/{token}/jobs/{sc}').json()
                return text_of((x.get('description') or '') + (x.get('requirements') or '') + (x.get('benefits') or ''))
            out.append(job(j.get('title'), text, f'https://apply.workable.com/{token}/j/{sc}/', sc, None,
                           j.get('published'), region, detail))
        pages += 1
        if not d.get('nextPage'):
            break
        body = {**body, 'token': d['nextPage']}
        time.sleep(0.5)
    return out


def smartrecruiters(token):
    out, offset = [], 0
    while True:
        d = get(f'https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100&offset={offset}').json()
        for j in d.get('content', []):
            loc = j.get('location') or {}
            cc = (loc.get('country') or '').lower()
            pid = j.get('id')

            def detail(pid=pid):
                x = get(f'https://api.smartrecruiters.com/v1/companies/{token}/postings/{pid}').json()
                secs = ((x.get('jobAd') or {}).get('sections') or {})
                return '\n'.join(text_of((secs.get(k) or {}).get('text', '')) for k in
                                 ('companyDescription', 'jobDescription', 'qualifications', 'additionalInformation'))
            out.append(job(j.get('name'), ', '.join(x for x in (loc.get('city'), loc.get('region'), cc) if x),
                           f'https://jobs.smartrecruiters.com/{token}/{pid}', pid, None, j.get('releasedDate'),
                           rules.COUNTRY_CODE.get(cc), detail))
        offset += 100
        if offset >= d.get('totalFound', 0) or offset > 2000:
            break
    return out


def recruitee(token):
    d = get(f'https://{token}.recruitee.com/api/offers/').json()
    out = []
    for j in d.get('offers', []):
        locs = [j.get('location') or '', j.get('country') or '', j.get('city') or '']
        for l in j.get('locations') or []:
            locs.append(f"{l.get('city', '')} {l.get('country', '')}")
        cc = (j.get('country_code') or '').lower()
        out.append(job(j.get('title'), ' / '.join(x for x in locs if x.strip()), j.get('careers_url'), j.get('id'),
                       text_of((j.get('description') or '') + (j.get('requirements') or '')),
                       j.get('published_at') or j.get('created_at'), rules.COUNTRY_CODE.get(cc)))
    return out


def _walk_facets(facets, want):
    """Find location facet values in a Workday facet tree that fall in the wanted regions.
    Returns {facetParameter: [(id, region)]}, preferring country-level facets."""
    country, place = {}, {}
    for f in facets or []:
        param = f.get('facetParameter', '')
        for v in f.get('values') or []:
            if v.get('facetParameter'):  # nested group
                sub_c, sub_p = _walk_facets_raw([v], want)
                for k, vals in sub_c.items():
                    country.setdefault(k, []).extend(vals)
                for k, vals in sub_p.items():
                    place.setdefault(k, []).extend(vals)
                continue
            label = (param + ' ' + (f.get('descriptor') or '')).lower()
            if 'country' not in label and 'location' not in label:
                continue
            hit = rules.regions_in(v.get('descriptor') or '') & set(want)
            if len(hit) == 1:
                (country if 'country' in label else place).setdefault(param, []).append((v.get('id'), hit.pop()))
    return country, place


def _walk_facets_raw(facets, want):
    return _walk_facets(facets, want)


def _pick_facets(facets, want):
    country, place = _walk_facets(facets, want)
    return country or place


def workday(tenant, wd, site, regions):
    base = f'https://{tenant}.{wd}.myworkdayjobs.com'
    api = f'{base}/wday/cxs/{tenant}/{site}'
    first = post(f'{api}/jobs', {'appliedFacets': {}, 'limit': 20, 'offset': 0, 'searchText': ''}).json()
    facets = _pick_facets(first.get('facets'), regions)
    queries = []
    for param, vals in facets.items():
        for vid, region in vals:
            queries.append(({param: [vid]}, region))
    if not queries:  # no country facet: page through everything and classify by text
        queries = [({}, None)]
    out, seen = [], set()
    for applied, region in queries:
        offset = 0
        while True:
            d = post(f'{api}/jobs', {'appliedFacets': applied, 'limit': 20, 'offset': offset, 'searchText': ''}).json()
            posts = d.get('jobPostings') or []
            for j in posts:
                path = j.get('externalPath') or ''
                if path in seen:
                    continue
                seen.add(path)

                def detail(path=path):
                    x = get(f'{api}{path}').json()
                    return text_of((x.get('jobPostingInfo') or {}).get('jobDescription', ''))
                out.append(job(j.get('title'), j.get('locationsText'), f'{base}/{site}{path}', path, None,
                               j.get('postedOn'), region, detail))
            offset += 20
            if not posts or offset >= (d.get('total') or first.get('total') or 0) or offset >= 1500:
                break
    return out


def eightfold(host, domain, regions):
    out, seen = [], set()

    def add(ps):
        for p in ps:
            pid = p.get('id')
            if pid in seen:
                continue
            seen.add(pid)

            def detail(pid=pid):
                x = get(f'https://{host}/api/apply/v2/jobs/{pid}?domain={domain}').json()
                return text_of(x.get('job_description', ''))
            locs = ' / '.join(p.get('locations') or [p.get('location') or ''])
            out.append(job(p.get('name'), locs, p.get('canonicalPositionUrl') or f'https://{host}/careers/job/{pid}',
                           pid, None, None, None, detail))

    start = 0  # the location filter isn't reliable, so read every posting and classify by location text
    while start < 4000:
        d = get(f'https://{host}/api/apply/v2/jobs?domain={domain}&start={start}&num=100').json()
        ps = d.get('positions') or []
        add(ps)
        start += len(ps) or 100
        if not ps or start >= (d.get('count') or 0):
            break
    return out


# ---------------- Careers-page watcher ----------------
class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._buf = [], None, []

    def handle_starttag(self, tag, a):
        if tag == 'a':
            self._href, self._buf = dict(a).get('href'), []

    def handle_data(self, d):
        if self._href is not None:
            self._buf.append(d)

    def handle_endtag(self, tag):
        if tag == 'a' and self._href is not None:
            t = re.sub(r'\s+', ' ', ''.join(self._buf)).strip()
            self.links.append((t, self._href))
            self._href = None


JOBLINK = re.compile(r'(job|jobs|vacanc|vacature|career|position|opening|posting|requisition|/j/|/o/)', re.I)
NAV = re.compile(r'^(apply|apply now|read more|learn more|view|view job|see more|details|careers?|jobs?|'
                 r'search|home|about|contact|login|sign in|next|previous|back|all jobs|open positions|\d+)$|'
                 r'\b(account|log ?in|sign ?(in|up)|register|privacy|cookie|terms|faq|blog|news|press|about us|'
                 r'contact|linkedin|twitter|facebook|instagram|youtube|job alert|talent community|policy|help|'
                 r'language|english|العربية|nederlands|home|search jobs|our (people|culture|values)|life at|'
                 r'benefits|students|graduates|early careers|events|locations?)\b', re.I)


def page_watch(url, prev):
    r = get(url, headers={'Accept': 'text/html'})
    p = _Links()
    p.feed(r.text)
    postings = {}
    for t, href in p.links:
        if not href or not t or len(t) < 8 or len(t) > 140 or len(t.split()) < 2 or NAV.search(t):
            continue
        full = urljoin(url, href)
        if JOBLINK.search(full) and full.rstrip('/') != url.rstrip('/'):
            postings[full] = t
    body = text_of(r.text)
    h = hashlib.sha1(body.encode()).hexdigest()
    return {'hash': h, 'postings': postings, 'chars': len(body)}


# ---------------- Main ----------------
def read_json(name, default):
    try:
        with open(os.path.join(DATA, name)) as f:
            return json.load(f)
    except Exception:
        return default


def source_key(src):
    return json.dumps(src, sort_keys=True)


def fetch_source(src, regions):
    t = src['type']
    if t in ('greenhouse', 'greenhouse-eu'):
        return greenhouse(src['token'], eu=t == 'greenhouse-eu')
    if t == 'ashby':
        return ashby(src['token'])
    if t == 'lever':
        return lever(src['token'])
    if t == 'workable':
        return workable(src['token'])
    if t == 'smartrecruiters':
        return smartrecruiters(src['token'])
    if t == 'recruitee':
        return recruitee(src['token'])
    if t == 'workday':
        return workday(src['tenant'], src['wd'], src['site'], regions)
    if t == 'eightfold':
        return eightfold(src['host'], src['domain'], regions)
    raise ValueError('unknown source ' + t)


def main():
    companies = [c for c in read_json('companies.json', []) if not c.get('skip')]
    prev = read_json('jobs.json', {})
    prev_jobs = {j['id']: j for j in prev.get('jobs', [])}
    baseline = prev.get('baseline_date') or TODAY
    prev_pages = read_json('pages.json', {})

    # group companies that share a board (e.g. IQVIA UK / NL / ME)
    groups = {}
    for c in companies:
        s = c.get('source')
        if s and s['type'] != 'page':
            g = groups.setdefault(source_key(s), {'src': s, 'companies': [], 'regions': set()})
            g['companies'].append(c)
            g['regions'].add(c['region'])

    def run_group(g):
        try:
            return g, fetch_source(g['src'], sorted(g['regions'])), None
        except Exception as e:
            return g, [], f'{type(e).__name__}: {str(e)[:160]}'

    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(run_group, groups.values()))

    kept, status, detail_jobs = [], [], []
    for g, raw, err in results:
        regions = g['regions']
        names = [c['name'] for c in g['companies']]
        stat = {'companies': names, 'source': g['src']['type'], 'error': err, 'total': len(raw), 'in_region': 0,
                'kept': 0}
        for j in raw:
            found = {j['region']} if j['region'] else rules.regions_in(j['location'])
            hit = found & regions
            if not hit:
                continue
            stat['in_region'] += 1
            why = rules.excluded_by_title(j['title'])
            if why:
                continue
            region = sorted(hit)[0]
            company = next((c for c in g['companies'] if c['region'] == region), g['companies'][0])
            j['company'], j['region'], j['category'] = company['name'], region, company.get('category', '')
            j['id'] = hashlib.sha1(f"{g['src']['type']}|{j['jid']}|{region}".encode()).hexdigest()[:14]
            j['_stat'] = stat
            detail_jobs.append(j)
        status.append(stat)

    def fill(j):
        if j['desc'] is None and j['_detail']:
            old = prev_jobs.get(j['id'])
            if old and old.get('lang_checked') and prev.get('rules_version') == rules.RULES_VERSION:
                j['desc'] = ''  # already vetted on a previous run; skip the extra request
                j['_reuse'] = old
            else:
                try:
                    j['desc'] = j['_detail']()
                except Exception:
                    j['desc'] = ''
        return j

    with ThreadPoolExecutor(max_workers=10) as ex:
        detail_jobs = list(ex.map(fill, detail_jobs))

    for j in detail_jobs:
        reuse = j.get('_reuse')
        if reuse:
            s, hits = reuse['score'], reuse.get('hits', [])
        else:
            if rules.language_block(j['title'], j['desc']):
                continue
            s, hits = rules.score(j['title'], j['desc'], j['category'])
        old = prev_jobs.get(j['id'])
        j['_stat']['kept'] += 1
        kept.append({'id': j['id'], 'company': j['company'], 'region': j['region'], 'title': j['title'],
                     'location': j['location'][:160], 'url': j['url'], 'posted': j['posted'],
                     'first_seen': old['first_seen'] if old else TODAY, 'score': s, 'hits': hits,
                     'lang_checked': True})

    kept.sort(key=lambda x: (x['first_seen'], x['score']), reverse=True)

    # careers pages without a feed
    pages_out = {}
    page_cos = [c for c in companies if (c.get('source') or {}).get('type') == 'page']

    def run_page(c):
        url = c['source']['url']
        try:
            return c, page_watch(url, prev_pages.get(url)), None
        except Exception as e:
            return c, None, f'{type(e).__name__}: {str(e)[:120]}'

    with ThreadPoolExecutor(max_workers=8) as ex:
        for c, res, err in ex.map(run_page, page_cos):
            url = c['source']['url']
            old = prev_pages.get(url) or {}
            if err:
                pages_out[url] = {**old, 'company': c['name'], 'error': err, 'checked': NOW}
                continue
            old_links = set((old.get('postings') or {}).keys())
            new_links = {u: t for u, t in res['postings'].items()
                         if old.get('hash') and u not in old_links and not rules.excluded_by_title(t)}
            changed = bool(old.get('hash')) and old.get('hash') != res['hash']
            pages_out[url] = {'company': c['name'], 'region': c['region'], 'hash': res['hash'],
                              'postings': res['postings'], 'readable': res['chars'] > 400,
                              'checked': NOW, 'error': None,
                              'changed_on': TODAY if changed else old.get('changed_on'),
                              'new_links': new_links if new_links else (old.get('new_links') if old.get('new_on') == TODAY else {}),
                              'new_on': TODAY if new_links else old.get('new_on')}

    manual = []
    for c in companies:
        s = c.get('source') or {}
        if s.get('type') == 'page':
            p = pages_out.get(s['url'], {})
            manual.append({'company': c['name'], 'region': c['region'], 'url': c.get('careers_url') or s['url'],
                           'kind': 'page', 'readable': p.get('readable'), 'changed_on': p.get('changed_on'),
                           'new_links': [{'title': t, 'url': u} for u, t in (p.get('new_links') or {}).items()],
                           'new_on': p.get('new_on'), 'error': p.get('error')})
        elif not s:
            q = quote(f'"{c["name"]}"')
            manual.append({'company': c['name'], 'region': c['region'],
                           'url': c.get('careers_url') or f'https://www.linkedin.com/jobs/search/?keywords={q}',
                           'kind': 'link' if c.get('careers_url') else 'linkedin', 'note': c.get('note', '')})

    new_today = [j for j in kept if j['first_seen'] == TODAY and TODAY != baseline]
    out = {'generated_at': NOW, 'baseline_date': baseline, 'rules_version': rules.RULES_VERSION, 'jobs': kept, 'manual': manual,
           'status': sorted(status, key=lambda s: (s['error'] is None, s['companies'][0])),
           'counts': {'companies': len(companies), 'feeds': len(groups), 'jobs': len(kept),
                      'new_today': len(new_today), 'pages': len(page_cos)}}
    with open(os.path.join(DATA, 'jobs.json'), 'w') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    with open(os.path.join(DATA, 'pages.json'), 'w') as f:
        json.dump(pages_out, f, indent=1, ensure_ascii=False)
    with open(os.path.join(DATA, 'new_today.json'), 'w') as f:
        json.dump(new_today, f, indent=1, ensure_ascii=False)

    errs = [s for s in status if s['error']]
    print(f"{len(kept)} jobs kept from {len(groups)} feeds; {len(new_today)} new today; {len(errs)} feed errors")
    for s in errs:
        print('  ERR', s['companies'][0], s['source'], s['error'])


if __name__ == '__main__':
    main()
