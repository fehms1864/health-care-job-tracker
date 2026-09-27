"""Filtering and scoring rules. Edit this file to tune what shows up on the site."""
import re

# Bump this whenever you change the rules below, so every job is re-checked and re-scored.
RULES_VERSION = 2

# ---------- Locations ----------
UK_WORDS = ['united kingdom', 'england', 'scotland', 'wales', 'northern ireland', 'great britain', 'london',
            'manchester', 'birmingham', 'bristol', 'leeds', 'glasgow', 'edinburgh', 'cambridge', 'oxford',
            'liverpool', 'nottingham', 'sheffield', 'newcastle', 'reading', 'belfast', 'cardiff', 'brighton',
            'milton keynes', 'guildford', 'slough', 'uxbridge', 'harrogate', 'stevenage', 'macclesfield']
UK_CODES = [r'\buk\b', r'\bgb\b', r'\bgbr\b']
NL_WORDS = ['netherlands', 'nederland', 'holland', 'amsterdam', 'rotterdam', 'utrecht', 'the hague', 'den haag',
            "'s-gravenhage", 'eindhoven', 'leiden', 'groningen', 'delft', 'haarlem', 'amstelveen', 'hoofddorp',
            'schiphol', 'nijmegen', 'tilburg', 'breda', 'arnhem', 'maastricht', 'zwolle', 'enschede', 'best, ',
            'hilversum', 'diemen', 'almere', 'amersfoort', 'leiderdorp', 'oss', 'hoofddorp']
NL_CODES = [r'\bnl\b', r'\bnld\b']
ME_WORDS = ['united arab emirates', 'emirates', 'dubai', 'abu dhabi', 'sharjah', 'ajman', 'al ain',
            'saudi', 'riyadh', 'jeddah', 'jedda', 'dammam', 'khobar', 'mecca', 'makkah', 'medina', 'neom',
            'qatar', 'doha', 'bahrain', 'manama', 'kuwait', 'oman', 'muscat', 'egypt', 'cairo', 'giza',
            'alexandria', 'jordan', 'amman', 'lebanon', 'beirut', 'middle east', 'gcc']
ME_CODES = [r'\buae\b', r'\bksa\b', r'\bmena\b', r'\bmea\b']
COUNTRY_CODE = {'gb': 'UK', 'uk': 'UK', 'nl': 'NL', 'ae': 'ME', 'sa': 'ME', 'qa': 'ME', 'bh': 'ME', 'kw': 'ME',
                'om': 'ME', 'eg': 'ME', 'jo': 'ME', 'lb': 'ME'}
REGION_COUNTRIES = {  # names used to pick Workday / Eightfold country facets
    'UK': ['united kingdom', 'great britain', 'england', 'scotland'],
    'NL': ['netherlands'],
    'ME': ['united arab emirates', 'saudi arabia', 'qatar', 'bahrain', 'kuwait', 'oman', 'egypt', 'jordan',
           'lebanon'],
}


def regions_in(text):
    """Every region (UK / NL / ME) that a location string mentions."""
    t = (text or '').lower()
    found = set()
    if any(w in t for w in UK_WORDS) or any(re.search(p, t) for p in UK_CODES):
        found.add('UK')
    if any(w in t for w in NL_WORDS) or any(re.search(p, t) for p in NL_CODES):
        found.add('NL')
    if any(w in t for w in ME_WORDS) or any(re.search(p, t) for p in ME_CODES):
        found.add('ME')
    return found


# ---------- Title exclusions ----------
# Checked against the job TITLE only, as whole words / phrases.
EXCLUDE = {
    'engineering': ['engineer', 'engineering', 'developer', 'devops', 'sre', 'site reliability', 'programmer',
                    'software', 'firmware', 'architect', 'qa', 'tester', 'test automation', 'machine learning',
                    'ml', 'ai researcher', 'research scientist', 'full stack', 'fullstack', 'front end', 'frontend',
                    'back end', 'backend', 'ios', 'android', 'infrastructure', 'cloud', 'cyber', 'security operations',
                    'penetration', 'technician', 'application support', 'technical support', 'it support', 'service desk',
                    'support engineer', 'sql', 'api', 'apis', 'fhir', 'integration engineer', 'programming', 'systems administrator', 'technical lead', 'tech lead', 'mechanical', 'electrical'],
    'analytics': ['analytics', 'data analyst', 'data scientist', 'data science', 'business intelligence', 'bi',
                  'insights analyst', 'reporting analyst', 'statistician', 'biostatistician', 'quantitative',
                  'quant', 'data engineer', 'data manager', 'data management', 'data specialist', 'data lead',
                  'analytical', 'econometric', 'modeller', 'modeler', 'rwe analyst', 'statistics', 'statistical',
                  'psychometrics', 'biostatistics', 'epidemiologist', 'data governance'],
    'finance': ['finance', 'financial', 'accountant', 'accounting', 'accounts payable', 'accounts receivable',
                'tax', 'treasury', 'audit', 'auditor', 'controller', 'fp&a', 'payroll', 'bookkeeper', 'credit',
                'actuary', 'actuarial', 'underwriter', 'underwriting', 'investment', 'trader', 'trading',
                'billing', 'procurement', 'pricing', 'revenue accountant', 'cfo', 'banking', 'lending',
                'collections', 'fraud', 'aml', 'kyc'],
    # kept from the original fit rules: clinical practitioners, too senior, too junior, clearly unrelated
    'clinical': ['nurse', 'nursing', 'physician', 'doctor', 'pharmacist', 'psychiatrist', 'psychologist',
                 'therapist', 'counsellor', 'counselor', 'dentist', 'dental', 'radiographer', 'sonographer',
                 'midwife', 'surgeon', 'paramedic', 'physiotherapist', 'dietitian', 'gp', 'consultant psychiatrist',
                 'medical officer', 'care assistant', 'healthcare assistant', 'carer', 'support worker',
                 'phlebotomist', 'optometrist', 'veterinary', 'vet', 'clinician', 'lab technician',
                 'laboratory', 'scientist', 'specialist registrar', 'resident'],
    'seniority': ['director', 'vp', 'vice president', 'head of', 'chief', 'svp', 'evp', 'associate partner',
                  'managing director', 'cto', 'ceo', 'coo', 'general manager', 'country manager'],
    'level': ['intern', 'internship', 'werkstudent', 'working student', 'stage', 'stagiair', 'apprentice',
              'apprenticeship', 'graduate scheme', 'student'],
    'other': ['sales', 'key account', 'account manager', 'business development', 'sales representative', 'account executive', 'sales executive', 'business development representative',
              'sdr', 'bdr', 'recruiter', 'talent acquisition', 'warehouse', 'driver', 'courier', 'chef', 'cook',
              'cleaner', 'receptionist', 'teacher', 'designer', 'copywriter', 'legal counsel', 'lawyer',
              'solicitor', 'paralegal', 'field sales', 'medical representative', 'sales rep', 'picker',
              'shopper', 'rider', 'customer service representative', 'call centre', 'call center',
              'marketing manager', 'performance marketing', 'seo'],
}
_EXCLUDE_RE = {k: re.compile(r'\b(' + '|'.join(re.escape(w) for w in v) + r')\b', re.I) for k, v in EXCLUDE.items()}


def excluded_by_title(title):
    """Return the reason a title is excluded, or None."""
    for reason, rx in _EXCLUDE_RE.items():
        m = rx.search(title or '')
        if m:
            return f'{reason}: {m.group(1).lower()}'
    return None


# ---------- Language requirement ----------
LANG = re.compile(r'\b(dutch|nederlands|nederlandse|flemish|arabic|arab speaker|arabic[- ]speaking|'
                  r'dutch[- ]speaking|عربي|العربية)\b', re.I)
OPTIONAL = re.compile(r'\b(plus|bonus|advantage|advantageous|nice[- ]to[- ]have|nice to haves|preferred|'
                      r'preferable|desirable|desired|beneficial|a benefit|ideally|not required|not necessary|'
                      r'not essential|not a requirement|no need|optional|would be great|helpful|welcome|'
                      r'is an asset|asset|or willing to learn|willingness to learn|learn dutch|dutch lessons|'
                      r'dutch classes|language course)\b', re.I)
CUE = re.compile(r'\b(fluent|fluency|native|mother tongue|speak|speaks|speaking|spoken|written|verbal|language|'
                 r'languages|proficient|proficiency|bilingual|command of|business[- ]level|c1|c2|b2|required|'
                 r'requirement|must|mandatory|essential)\b', re.I)
DUTCH_TEXT = re.compile(r'\b(wij|jij|je|jouw|ons|onze|het|een|voor|met|zijn|werkzaamheden|vacature|functie|'
                        r'ervaring|kennis|solliciteer|wat ga je doen|wie ben jij|wat bieden wij)\b', re.I)
ENGLISH_TEXT = re.compile(r'\b(the|and|you|your|with|we|our|for|will|experience|team|role)\b', re.I)
ARABIC_CHARS = re.compile(r'[؀-ۿ]')


def language_block(title, text):
    """Return 'Dutch required' / 'Arabic required' when the posting needs it, else None."""
    t = f'{title or ""}\n{text or ""}'
    # posting written in Dutch or Arabic -> effectively required
    words = max(1, len(t.split()))
    nl, en = len(DUTCH_TEXT.findall(t)), len(ENGLISH_TEXT.findall(t))
    if words > 40 and nl > en and nl / words > 0.04:
        return 'Dutch required (posting in Dutch)'
    if len(ARABIC_CHARS.findall(t)) > 0.3 * len(t.replace(' ', '')) and len(t) > 60:
        return 'Arabic required (posting in Arabic)'
    if re.search(r'\b(dutch|arabic)[- ]speaking\b', title or '', re.I) or re.search(r'\((nl|dutch|arabic)\)', title or '', re.I):
        return ('Dutch' if re.search('dutch|nl', title, re.I) else 'Arabic') + ' required (title)'
    # look at the words around each mention of Dutch / Arabic
    for m in LANG.finditer(t):
        window = t[max(0, m.start() - 90): m.end() + 90]
        if OPTIONAL.search(window):
            continue
        if CUE.search(window):
            lang = 'Arabic' if re.search(r'arab|عرب', m.group(0), re.I) else 'Dutch'
            return f'{lang} required'
    return None


# ---------- Fit scoring ----------
BOOST = {
    # domain
    'healthcare': 6, 'health care': 6, 'health': 4, 'clinical': 5, 'patient': 6, 'medical': 4, 'hospital': 6,
    'care': 2, 'digital health': 9, 'healthtech': 9, 'health tech': 9, 'life science': 4, 'life sciences': 4,
    'pharma': 3, 'medtech': 6, 'medical device': 4, 'ehealth': 7, 'telehealth': 8, 'telemedicine': 8,
    'mental health': 8, 'nhs': 6, 'payer': 4, 'provider': 3, 'health system': 7, 'population health': 7,
    'value-based care': 8, 'care coordination': 8, 'patient experience': 8, 'patient journey': 8,
    'wellbeing': 3, 'insurance': 2,
    # function
    'strategy': 6, 'operations': 6, 'operational': 4, 'consultant': 6, 'consulting': 6, 'advisory': 3,
    'implementation': 8, 'transformation': 6, 'program manager': 7, 'programme manager': 7,
    'project manager': 5, 'product manager': 4, 'product operations': 6, 'business analyst': 4,
    'process improvement': 6, 'service delivery': 5, 'customer success': 4, 'onboarding': 4, 'workflow': 5,
    'governance': 4, 'stakeholder': 3, 'change management': 6, 'operations manager': 6, 'associate': 2,
    'coordinator': 3, 'specialist': 1, 'launch': 3, 'engagement manager': 5, 'solutions consultant': 6,
    'client': 2, 'partnerships': 3, 'market access': 4, 'quality improvement': 6, 'training': 2,
    'strategy & operations': 9, 'strategy and operations': 9, 'bizops': 7, 'business operations': 7,
    # her tools
    'epic': 5, 'cerner': 5, 'emr': 6, 'ehr': 6, 'eclinicalworks': 6, 'servicenow': 3, 'zendesk': 2,
}


def score(title, text, company_category=''):
    """Title words count double; description words count half and are capped, so a long
    boilerplate description can't outscore a well-matched title."""
    t = (title or '').lower()
    body = (text or '')[:5000].lower()
    title_pts, body_pts, hits = 0, 0, []
    for k, v in BOOST.items():
        rx = r'\b' + re.escape(k) + r'\b'
        if re.search(rx, t):
            title_pts += 2 * v
            if v >= 4:
                hits.append(k)
        elif re.search(rx, body):
            body_pts += v / 2
            if v >= 6:
                hits.append(k)
    s = title_pts + min(body_pts, 20)
    if 'health' in company_category.lower():
        s += 3
    return round(s), list(dict.fromkeys(hits))[:4]
