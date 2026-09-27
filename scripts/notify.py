"""Builds the body of the daily 'new jobs' GitHub issue from data/new_today.json.
Prints nothing (and the workflow skips the issue) when there are no new jobs."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
new = json.load(open(os.path.join(ROOT, 'data', 'new_today.json')))
if new:
    new.sort(key=lambda j: -j['score'])
    names = {'UK': 'United Kingdom', 'NL': 'Netherlands', 'ME': 'Middle East'}
    lines = []
    for region in ('UK', 'NL', 'ME'):
        rows = [j for j in new if j['region'] == region]
        if not rows:
            continue
        lines.append(f'### {names[region]} ({len(rows)})')
        for j in rows:
            fit = ' ⭐' if j['score'] >= 25 else ''
            lines.append(f"- **[{j['title']}]({j['url']})**: {j['company']}, {j['location']} · match {j['score']}{fit}")
        lines.append('')
    site = os.environ.get('SITE_URL', '')
    if site:
        lines.append(f'Full dashboard: {site}')
    print('\n'.join(lines))
