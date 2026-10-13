"""Readers for the job systems that large employers use: Jibe (iCIMS career sites), Phenom, Zenats,
SuccessFactors (RMK), Eightfold PCS (Microsoft), BambooHR, Yext (HCA UK), Bayt (Bupa Arabia),
plus the Atlassian and TomTom careers feeds. Each returns a list of fetch_jobs.job() dicts.
Formats were checked against live responses from each site; unofficial endpoints can change."""
import datetime as dt
import json
import re
from urllib.parse import quote, urljoin

import fetch_jobs as fj
import rules

PHENOM_COUNTRIES = {'UK': ['United Kingdom'], 'NL': ['Netherlands'],
                    'ME': ['United Arab Emirates', 'Saudi Arabia', 'Qatar', 'Egypt', 'Bahrain', 'Kuwait', 'Oman',
                           'Jordan', 'Lebanon']}


def _page_text(url):
    """Description for a job page: JobPosting JSON-LD if present, else the page's visible text."""
    import pages
    h, final = pages.get_html(url)
    ld = pages.jsonld_postings(h, final)
    if ld and ld[0].get('desc'):
        return ld[0]['desc']
    return fj.text_of(h)[:6000]


def _detail(url):
    return lambda: _page_text(url)


def jibe(host, regions):
    """iCIMS 'Jibe' career sites (jobs.zs.com, careers.m42.ae, careers.publicisgroupe.com): /api/jobs."""
    out, page = [], 1
    while page <= 40:
        d = fj.get(f'https://{host}/api/jobs?page={page}&limit=100&sortBy=posted_date&descending=true&internal=false').json()
        js = d.get('jobs') or []
        for w in js:
            j = w.get('data') or w
            loc = j.get('full_location') or ', '.join(x for x in (j.get('city'), j.get('state'), j.get('country')) if x)
            locs = j.get('location_name') or ''
            cc = (j.get('country_code') or '').lower()
            out.append(fj.job(j.get('title'), f'{loc} / {locs}' if locs and locs not in loc else loc,
                              f"https://{host}/jobs/{j.get('slug') or j.get('req_id')}?lang=en-us",
                              j.get('req_id') or j.get('slug'),
                              fj.text_of((j.get('description') or '') + (j.get('qualifications') or '') +
                                         (j.get('responsibilities') or '')),
                              j.get('posted_date') or j.get('create_date'), rules.COUNTRY_CODE.get(cc)))
        total = d.get('totalCount') or d.get('count') or 0
        if not js or page * 100 >= total:
            break
        page += 1
    return out


def zenats(host, slug):
    out, page = [], 1
    while page <= 10:
        d = fj.get(f'https://{host}/en/api/v1/career_page/jobs/live?page[number]={page}&page[limit]=50'
                   f'&sort[type]=created_at&sort[order]=desc&slug={slug}').json()
        for j in d.get('data') or []:
            link = j.get('public_link') or f'https://{host}/en/careers_page'
            out.append(fj.job(j.get('title'), j.get('location'), link, j.get('id'), None, j.get('created_at'),
                              None, _detail(link)))
        if not ((d.get('meta') or {}).get('pager') or {}).get('has_next_page'):
            break
        page += 1
    return out


def phenom(host, ref, path, regions, lang='en_global'):
    """Phenom career sites: the search page's own 'refineSearch' widget call, filtered by country."""
    out, seen = [], set()
    for region in regions:
        for country in PHENOM_COUNTRIES.get(region, []):
            start = 0
            while start < 1000:
                body = {'lang': lang, 'deviceType': 'desktop', 'country': path.split('/')[0], 'pageName': 'search-results',
                        'ddoKey': 'refineSearch', 'sortBy': '', 'subsearch': '', 'from': start, 'jobs': True,
                        'counts': True, 'all_fields': ['country', 'city'], 'size': 100, 'clearAll': False,
                        'jdsource': 'facets', 'isSliderEnable': False, 'pageId': 'page1', 'siteType': 'external',
                        'keywords': '', 'global': True, 'selected_fields': {'country': [country]}, 'refNum': ref,
                        'locationData': {}}
                d = (fj.post(f'https://{host}/widgets', body).json().get('refineSearch') or {})
                js = (d.get('data') or {}).get('jobs') or []
                for j in js:
                    jid = j.get('jobId') or j.get('reqId')
                    if jid in seen:
                        continue
                    seen.add(jid)
                    slug = re.sub(r'[^A-Za-z0-9]+', '-', j.get('title') or '').strip('-')
                    url = f'https://{host}/{path}/job/{jid}/{slug}'
                    locs = ' / '.join(j.get('multi_location') or [j.get('location') or j.get('cityState') or ''])
                    teaser = (j.get('descriptionTeaser') or '') + '\n' + fj.text_of(j.get('experience') or '')
                    out.append(fj.job(j.get('title'), f"{locs} / {j.get('country', '')}", url, jid, None,
                                      j.get('postedDate'), region, (lambda u=url, t=teaser: _page_text(u) or t)))
                start += 100
                if not js or start >= (d.get('totalHits') or 0):
                    break
    return out


def pcsx(host, domain, regions):
    """Eightfold 'PCS' career sites (Microsoft)."""
    names = {'UK': ['United Kingdom'], 'NL': ['Netherlands'], 'ME': ['United Arab Emirates', 'Saudi Arabia', 'Qatar', 'Egypt']}
    out, seen = [], set()
    for region in regions:
        for country in names.get(region, []):
            start = 0
            while start < 1500:
                d = fj.get(f'https://{host}/api/pcsx/search?domain={domain}&query=&location={quote(country)}'
                           f'&start={start}&sort_by=timestamp').json().get('data') or {}
                ps = d.get('positions') or []
                for p in ps:
                    if p['id'] in seen:
                        continue
                    seen.add(p['id'])
                    pid = p['id']

                    def detail(pid=pid):
                        x = fj.get(f'https://{host}/api/pcsx/position_details?position_id={pid}&domain={domain}&hl=en').json()
                        dd = x.get('data') or {}
                        return fj.text_of(dd.get('jobDescription') or dd.get('job_description') or json.dumps(dd)[:8000])
                    ts = p.get('postedTs')
                    out.append(fj.job(p.get('name'), ' / '.join(p.get('locations') or []),
                                      f"https://{host}{p.get('positionUrl') or '/careers/job/' + str(pid)}", pid, None,
                                      dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat() if ts else None,
                                      None, detail))
                start += len(ps) or 10
                if not ps or start >= (d.get('count') or 10 ** 6):
                    break
    return out


def sf_rmk(host, regions, locale='en_US'):
    """SAP SuccessFactors career sites (new RMK search API), e.g. careers.wipro.com."""
    names = {'UK': ['United Kingdom'], 'NL': ['Netherlands'], 'ME': ['United Arab Emirates', 'Saudi Arabia', 'Qatar', 'Egypt']}
    out, seen = [], set()
    for region in regions:
        for country in names.get(region, []):
            pg = 0
            while pg < 40:
                body = {'locale': locale, 'pageNumber': pg, 'sortBy': 'date', 'keywords': '', 'location': country,
                        'facetFilters': {}, 'brand': '', 'skills': [], 'categoryId': 0, 'alertId': '', 'rcmCandidateId': ''}
                d = fj.post(f'https://{host}/services/recruiting/v1/jobs', body).json()
                rs = d.get('jobSearchResult') or []
                for w in rs:
                    j = w.get('response') or {}
                    if j.get('id') in seen:
                        continue
                    seen.add(j.get('id'))
                    url = f"https://{host}/job/{j.get('urlTitle')}/{j.get('id')}-{locale}"
                    out.append(fj.job(j.get('unifiedStandardTitle'),
                                      ' / '.join((j.get('jobLocationShort') or []) + (j.get('jobLocationCountry') or [])),
                                      url, j.get('id'), None, j.get('unifiedStandardStart'), None, _detail(url)))
                pg += 1
                if not rs or pg * 10 >= (d.get('totalJobs') or 0):
                    break
    return out


def rmk_html(host, path, regions):
    """Older SuccessFactors RMK sites with no open API (EY): read the server-rendered search results."""
    names = {'UK': ['United Kingdom'], 'NL': ['Netherlands'], 'ME': ['United Arab Emirates', 'Saudi Arabia', 'Qatar', 'Egypt']}
    out, seen = [], set()
    for region in regions:
        for country in names.get(region, []):
            start = 0
            while start < 1500:
                h = fj.get(f'https://{host}/{path}/search/?q=&locationsearch={quote(country)}&startrow={start}',
                           headers={'Accept': 'text/html'}).text
                rows = re.findall(r'<a[^>]+href="(/' + re.escape(path) + r'/job/([^"/]+)/(\d+)/)"[^>]*>([^<]{4,200})</a>', h)
                fresh = 0
                for href, slug, jid, title in rows:
                    if jid in seen:
                        continue
                    seen.add(jid)
                    fresh += 1
                    url = f'https://{host}{href}'
                    loc = re.split(r'-[A-Z][a-z]', slug)[0].replace('-', ' ') + f', {country}'
                    out.append(fj.job(fj.html.unescape(title.strip()), loc, url, jid, None, None, region, _detail(url)))
                start += 25
                if not fresh:
                    break
    return out


def bamboohr(token):
    d = fj.get(f'https://{token}.bamboohr.com/careers/list').json()
    out = []
    for j in d.get('result') or []:
        loc = j.get('location') or {}
        al = j.get('atsLocation') or {}
        text = ', '.join(x for x in (loc.get('city'), loc.get('state'), al.get('country')) if x)
        jid = j.get('id')

        def detail(jid=jid):
            x = fj.get(f'https://{token}.bamboohr.com/careers/{jid}/detail').json()
            return fj.text_of(((x.get('result') or {}).get('jobOpening') or {}).get('description') or '')
        out.append(fj.job(j.get('jobOpeningName'), text, f'https://{token}.bamboohr.com/careers/{jid}', jid, None,
                          None, None, detail))
    return out


def yext_hca():
    """HCA Healthcare UK's careers search (Yext). Each job carries a Clinical / Non-Clinical flag."""
    out, off = [], 0
    while off < 2000:
        d = fj.get(f'https://www.hcahealthcare.co.uk/api/api-layer/careers/search?verticalKey=jobs&limit=50&offset={off}').json()
        res = (d.get('response') or {}).get('results') or []
        for w in res:
            j = w.get('data') or {}
            if (j.get('jobFunction') or '').lower() == 'clinical':
                continue
            url = j.get('landingPageUrl') or j.get('applicationUrl')
            out.append(fj.job(j.get('name'), f"{j.get('jobCity') or ''}, United Kingdom", url, j.get('id'),
                              fj.text_of(j.get('richDescription') or j.get('bodyPlain') or '') or None,
                              j.get('datePosted'), 'UK', _detail(url)))
        off += 50
        if not res or off >= ((d.get('response') or {}).get('resultsCount') or 0):
            break
    return out


def bayt_site(host, token, query, body):
    """Bayt-powered company career sites (Bupa Arabia)."""
    out, seen, page = [], set(), 1
    while page <= 10:
        d = fj.get(f'https://{host}/app/control/byt_job_search_manager?action=1&token={token}&query={quote(query)}'
                   f'&body={body}&lan=en&page={page}').json()
        js = d.get('jobs') or []
        fresh = 0
        for j in js:
            if j['id'] in seen:
                continue
            seen.add(j['id'])
            fresh += 1
            url = urljoin(f'https://{host}/', j.get('url') or '')
            out.append(fj.job(j.get('title'), j.get('loc'), url, j['id'], None, j.get('crtDate'), None, _detail(url)))
        if not fresh or len(seen) >= (d.get('totalJobs') or 0):
            break
        page += 1
    return out


def atlassian():
    d = fj.get('https://www.atlassian.com/endpoint/careers/listings').json()
    out = []
    for j in d:
        desc = fj.text_of(''.join(j.get(k) or '' for k in ('overview', 'responsibilities', 'qualifications')))
        out.append(fj.job(j.get('title'), ' / '.join(j.get('locations') or []),
                          f"https://www.atlassian.com/company/careers/details/{j.get('id')}", j.get('id'), desc,
                          (j.get('portalJobPost') or {}).get('updatedDate')))
    return out


def tomtom():
    d = fj.get('https://www.tomtom.com/api/careers/jobs/').json()
    out = []
    for j in d.get('jobs') or []:
        dsc = j.get('description') or {}
        body = '\n'.join(dsc.get('body') or [])
        for sec in dsc.get('sections') or []:
            body += '\n' + (sec.get('title') or '') + '\n' + '\n'.join(i.get('text', '') for i in sec.get('items') or [])
        out.append(fj.job(j.get('title'), j.get('location'),
                          f"https://www.tomtom.com/careers/jobdetails/{j.get('jobId')}/{j.get('slug')}/", j.get('jobId'),
                          body, None))
    return out


def fetch(src, regions):
    t = src['type']
    if t == 'jibe':
        return jibe(src['host'], regions)
    if t == 'zenats':
        return zenats(src['host'], src['slug'])
    if t == 'phenom':
        return phenom(src['host'], src['ref'], src['path'], regions, src.get('lang', 'en_global'))
    if t == 'pcsx':
        return pcsx(src['host'], src['domain'], regions)
    if t == 'sf_rmk':
        return sf_rmk(src['host'], regions, src.get('locale', 'en_US'))
    if t == 'rmk_html':
        return rmk_html(src['host'], src['path'], regions)
    if t == 'bamboohr':
        return bamboohr(src['token'])
    if t == 'yext_hca':
        return yext_hca()
    if t == 'bayt':
        return bayt_site(src['host'], src['token'], src['query'], src['body'])
    if t == 'atlassian':
        return atlassian()
    if t == 'tomtom':
        return tomtom()
    raise ValueError('unknown source ' + t)


TYPES = {'jibe', 'zenats', 'phenom', 'pcsx', 'sf_rmk', 'rmk_html', 'bamboohr', 'yext_hca', 'bayt', 'atlassian', 'tomtom'}
