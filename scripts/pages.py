"""Careers-page reader for companies without a job-board feed.

For each careers page it:
  1. loads the page (plain request, or a headless browser when the page only renders with JavaScript),
  2. reads any JobPosting structured data (JSON-LD) on the page itself,
  3. otherwise follows each job link and reads the JobPosting data on that job's page,
  4. falls back to the link text as the title for small single-country companies (`assume_region`).
Job pages already read are cached in data/page_cache.json so each run only opens new links.
"""
import hashlib
import json
import re
from urllib.parse import urljoin, urlparse

import fetch_jobs as fj

MAX_NEW_LINKS = 40  # job pages opened per company per run (the rest are picked up next run)
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/128.0 Safari/537.36')

_pw = None
_browser = None


def _get_browser():
    global _pw, _browser
    if _browser is None:
        from playwright.sync_api import sync_playwright
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch()
    return _browser


def close():
    global _pw, _browser
    if _browser:
        _browser.close()
        _pw.stop()
    _pw = _browser = None


def get_html(url, render=False, wait_ms=5000):
    """Page HTML. Falls back to the headless browser if a plain request is blocked or comes back empty."""
    if not render:
        try:
            r = fj.S.get(url, timeout=30, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
            if r.status_code == 200 and len(r.text) > 2000:
                return r.text, url
        except Exception:
            pass
    try:
        b = _get_browser()
    except Exception as e:  # playwright not installed (e.g. running locally without it)
        raise RuntimeError(f'needs a browser: {e}')
    ctx = b.new_context(user_agent=UA, locale='en-GB')
    page = ctx.new_page()
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(wait_ms)
        try:
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(1200)
        except Exception:
            pass
        html = page.content()
        # iCIMS and similar put the job list in an iframe; include frame HTML too
        for f in page.frames[1:]:
            try:
                if any(k in f.url for k in ('icims', 'job', 'career')):
                    html += '\n<!-- frame ' + f.url + ' -->\n' + f.content()
            except Exception:
                pass
        return html, page.url
    finally:
        ctx.close()


def _first(x):
    return x[0] if isinstance(x, list) and x else x


def _loc_text(jp):
    parts = []
    locs = jp.get('jobLocation') or []
    if isinstance(locs, dict):
        locs = [locs]
    for l in locs:
        if not isinstance(l, dict):
            continue
        a = l.get('address') or {}
        if isinstance(a, str):
            parts.append(a)
            continue
        if isinstance(a, list):
            a = _first(a) or {}
        c = a.get('addressCountry')
        if isinstance(c, dict):
            c = c.get('name')
        parts.append(', '.join(str(x) for x in (a.get('addressLocality'), a.get('addressRegion'), c) if x))
    for r in jp.get('applicantLocationRequirements') or []:
        if isinstance(r, dict) and r.get('name'):
            parts.append(r['name'])
    if jp.get('jobLocationType') == 'TELECOMMUTE' and not parts:
        parts.append('Remote')
    return ' / '.join(p for p in parts if p)


def jsonld_postings(html, base_url):
    """All JobPosting objects in the page's JSON-LD blocks."""
    out = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html or '', re.S | re.I):
        raw = m.group(1).strip()
        try:
            d = json.loads(raw)
        except Exception:
            try:
                d = json.loads(re.sub(r'[\x00-\x1f]', ' ', raw))
            except Exception:
                continue
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                t = x.get('@type')
                if t == 'JobPosting' or (isinstance(t, list) and 'JobPosting' in t):
                    out.append({'title': fj.html.unescape(str(x.get('title') or '')).strip(),
                                'location': _loc_text(x),
                                'posted': x.get('datePosted'),
                                'desc': fj.text_of(str(x.get('description') or '')),
                                'url': urljoin(base_url, str(x.get('url') or '')) if x.get('url') else None})
                for k in ('@graph', 'itemListElement', 'item', 'mainEntity'):
                    if k in x:
                        stack.append(x[k])
    return out


JOBISH = re.compile(r'/(jobs?|vacanc\w*|vacatures?|positions?|openings?|postings?|requisitions?|careers?/job|'
                    r'job-details?|jobdetail|o|j)/[^?#]{3,}', re.I)


def job_links(html, base_url, pattern=None):
    p = fj._Links()
    try:
        p.feed(html or '')
    except Exception:
        pass
    host = urlparse(base_url).netloc.split(':')[0].removeprefix('www.')
    out = {}
    for t, href in p.links:
        if not href or not t:
            continue
        t = re.sub(r'\s+', ' ', t).strip()
        if len(t) < 6 or len(t) > 160 or len(t.split()) < 2 or fj.NAV.search(t):
            continue
        full = urljoin(base_url, href).split('#')[0]
        if re.search(r'^(mailto|tel|javascript):|cdn-cgi', full, re.I) or full.rstrip('/') == base_url.rstrip('/'):
            continue
        if pattern:
            if not re.search(pattern, full, re.I):
                continue
        elif not JOBISH.search(urlparse(full).path + '/'):
            continue
        lh = urlparse(full).netloc.removeprefix('www.')
        if host not in lh and lh not in host and not re.search(r'icims|teamtailor|zenats|workable|lever|greenhouse|'
                                                               r'ashby|smartrecruiters|recruitee|personio|bamboohr|'
                                                               r'breezy|getro|consider|jobs\.', lh):
            continue
        # keep only the first line of multi-line link text (title, not "Title Location Department")
        out.setdefault(full, t[:120])
    return out


def page_jobs(company, src, cache):
    """Returns (jobs, info). `cache` is updated in place: url -> {ld: {...} | None, seen: date}."""
    url = src['url']
    render = bool(src.get('render'))
    html, final = get_html(url, render)
    body = fj.text_of(html)
    info = {'hash': hashlib.sha1(body.encode()).hexdigest(), 'chars': len(body), 'method': None}
    jobs = []

    on_page = [p for p in jsonld_postings(html, final) if p['title']]
    links = job_links(html, final, src.get('link_pattern'))
    info['postings'] = links

    if on_page:
        info['method'] = 'structured data on careers page'
        for p in on_page:
            u = p['url'] or final
            jobs.append(fj.job(p['title'], p['location'], u, u, p['desc'], p['posted']))
        return jobs, info

    opened = 0
    for u, text in links.items():
        c = cache.get(u)
        if c is None:
            if opened >= (25 if render else MAX_NEW_LINKS):
                continue
            opened += 1
            try:
                h2, f2 = get_html(u, render, wait_ms=3000)
                ld = jsonld_postings(h2, f2)
                c = {'ld': ld[0] if ld else None}
                if not ld:
                    c['text'] = fj.text_of(h2)[:3000]
                    m = re.search(r'<h1[^>]*>(.*?)</h1>', h2, re.S | re.I)
                    c['h1'] = fj.text_of(m.group(1))[:140] if m else ''
            except Exception as e:
                c = {'ld': None, 'error': str(e)[:80]}
        c['seen'] = fj.TODAY
        cache[u] = c
        ld = c.get('ld')
        if ld and ld.get('title'):
            # many JobPosting blocks leave the location empty; the link often carries the city (/jobs/team/london/...)
            loc = ld['location'] or ' '.join(re.split(r'[/_-]+', urlparse(u).path))
            j = fj.job(ld['title'], loc, u, u, ld['desc'] or '', ld['posted'])
            if not ld['location'] and src.get('default_region'):
                j['region'] = company['region']
            jobs.append(j)
        elif src.get('assume_region'):
            # small single-country company: trust the link text as the job title
            title = text.split(' - ')[0][:120]
            if re.match(r'^(view|see|read|more|apply|details|learn|open)\b', title, re.I) and c.get('h1'):
                title = c['h1']
            j = fj.job(title, '', u, u, c.get('text') or '', None, region=company['region'])
            j['_linkonly'] = True
            jobs.append(j)
    structured = sum(1 for u in links if (cache.get(u) or {}).get('ld'))
    info['method'] = ('structured data on job pages' if structured else
                      'link titles' if jobs else None)
    return jobs, info


def teamtailor(base):
    """Teamtailor career sites publish an RSS feed of open jobs at /jobs.rss."""
    base = base.rstrip('/')
    r = fj.get(f'{base}/jobs.rss', headers={'Accept': 'application/rss+xml, application/xml, text/xml'})
    out = []
    for item in re.findall(r'<item>(.*?)</item>', r.text, re.S):
        def tag(name):
            m = re.search(rf'<{name}[^>]*>(.*?)</{name}>', item, re.S)
            v = (m.group(1) if m else '').strip()
            return fj.html.unescape(re.sub(r'^<!\[CDATA\[|\]\]>$', '', v).strip())
        locs = re.findall(r'<tt:(?:city|country|name|location)[^>]*>([^<]+)</tt:', item)
        link = tag('link') or tag('guid')
        desc = fj.text_of(tag('description'))
        out.append(fj.job(tag('title'), ' / '.join(dict.fromkeys(l.strip() for l in locs if l.strip())), link,
                          link, desc, tag('pubDate')))
    return out
