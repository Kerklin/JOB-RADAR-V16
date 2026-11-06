"""Job Radar V16 (repaired V15).   python radar.py        collect + publish site/
                                   python radar.py test   run regression tests
Standard library for collection and scoring. Optional Playwright fallback for the Oracle sites.
No AI, no email, no user secrets, no paid API."""
import concurrent.futures as cf
import datetime as dt
import html, json, os, re, sys, time, unicodedata, unittest
import urllib.error, urllib.parse, urllib.request, urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

VERSION = 'V16'
UA = 'DamirJobRadar/16 (public vacancy reader)'
MAX_BYTES = 32_000_000
NOW = lambda: dt.datetime.now(dt.timezone.utc)
TODAY = lambda: NOW().date()

# ======================= YOUR PROFILE (edit; drives the eligibility score) =======================
PROFILE = {
    # CONFIRM: inferred from your National Officer post in Bosnia and Herzegovina.
    # Add every citizenship you actually hold (e.g. 'Croatia') - only if true.
    'nationalities': ['Bosnia and Herzegovina'],
    # Extra countries where you already have the right to work (nationalities are included automatically).
    'work_rights': [],
    'years_experience': 25,                 # professional experience 2001-2026
    'degree_level': 'phd',                  # PhD Architectural Engineering; Master's; Bachelor of Architecture
    'languages': ['english', 'french', 'italian', 'bosnian', 'croatian', 'serbian', 'montenegrin'],
    'current_staff_of': [],                 # e.g. ['UNDP'] ONLY if you now hold an appointment there
}

# ======================= SOURCES =======================
ORACLE = {  # public Oracle Recruiting Cloud career sites: (origin, site number)
    'UNDP': ('https://estm.fa.em2.oraclecloud.com', 'CX_1'),
    'IOM': ('https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com', 'CX_1001'),
}
FEEDS = {   # RSS/Atom, alternates tried in order
    'UNICEF': ['https://careers.pageuppeople.com/671/cw/en/rss'],
    'UNOPS': ['https://careers.unops.org/careersmarketplace/SearchJobs/feed/?listFilterMode=1&jobRecordsPerPage=6',
              'https://rss.careers.unops.org/'],
    'UN Careers': ['https://careers.un.org/jobfeed?language=en', 'https://careers.un.org/jobfeed?isPage=true'],
}
HTML_SOURCES = {'Impactpool': ('https://www.impactpool.org/search?occupational_groups%5B%5D=Engineering', r'/jobs/\d+')}
MANUAL = [
    ('UNDP careers', 'https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions'),
    ('IOM careers', 'https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions'),
    ('UNICEF careers', 'https://jobs.unicef.org/cw/en-us/listing/'),
    ('UNOPS careers', 'https://careers.unops.org/'),
    ('UN Careers', 'https://careers.un.org/'),
    ('UNjobs civil engineering (manual only: robots.txt)', 'https://unjobs.org/skills/civil-engineer'),
    ('Impactpool engineering', 'https://www.impactpool.org/search?occupational_groups%5B%5D=Engineering'),
    ('UNJobsFeed', 'https://unjobsfeed.org/'),
]
ORACLE_DETAIL_CAP = 40          # detail requests per Oracle site per run
ORACLE_MAX_JOBS = 1000          # listing cap per Oracle site per run

# ======================= RELEVANCE (title weight; description counts one third) =======================
TRACKS = {
    'Construction': {'project manager infrastructure': 24, 'project manager construction': 24, 'construction engineer': 24,
        'construction manager': 24, 'construction specialist': 24, 'construction officer': 24, 'construction supervisor': 24,
        'construction project manager': 24, 'construction management': 20, 'site engineer': 24, 'resident engineer': 24,
        'clerk of works': 24, 'engineering officer': 20, 'engineering associate': 18, 'construction supervision': 18,
        'civil works': 18, 'construction': 16, 'rehabilitation': 12, 'reconstruction': 12},
    'Infrastructure': {'civil engineer': 24, 'engineer civil': 24, 'structural engineer': 24, 'engineer structural': 24,
        'road engineer': 24, 'bridge engineer': 24, 'infrastructure engineer': 24, 'infrastructure field engineer': 24,
        'infrastructure specialist': 24, 'infrastructure officer': 24, 'building services engineer': 24,
        'geotechnical engineer': 24, 'energy efficiency engineer': 24, 'project engineer': 20, 'field engineer': 20,
        'engineering assistant': 16, 'engineering technician': 16, 'engineer': 16, 'engineering': 16,
        'infrastructure': 16, 'reinforced concrete': 12, 'pavement': 12},
    'WASH': {'wash engineer': 24, 'wash officer': 20, 'wash specialist': 20, 'wash consultant': 20, 'water engineer': 24,
        'sanitation engineer': 24, 'water supply': 16, 'water treatment': 16, 'sewerage': 16, 'wastewater': 16, 'boreholes': 12},
    'Contracts': {'quantity surveyor': 24, 'fidic': 20, 'contract manager': 20, 'contracts manager': 20, 'cost engineer': 24,
        'works contracts': 20, 'procurement specialist': 16, 'procurement officer': 16, 'bill of quantities': 16,
        'bills of quantities': 16, 'boq': 16},
    'Facilities': {'facilities manager': 24, 'facility manager': 24, 'facilities management': 20, 'common premises': 20,
        'building maintenance': 16, 'refurbishment': 12, 'property management': 16},
    'Architecture': {'architect': 24, 'architectural': 20, 'heritage conservation': 20, 'restoration': 12,
        'urban planner': 20, 'urban planning': 16, 'housing reconstruction': 20, 'shelter': 12},
}
RELEVANCE_MIN = 16
TITLE_EXCLUDE = ['intern', 'internship', 'driver', 'finance officer', 'finance associate', 'communications officer',
    'communication associate', 'human resources', 'software', 'cloud', 'data engineer', 'solutions architect',
    'enterprise architect', 'data architect', 'digital infrastructure', 'digital public infrastructure',
    'it infrastructure', 'ict', 'network engineer', 'security guard', 'medical', 'nurse', 'translator', 'interpreter']
WORKS_CONTEXT = ['construction', 'infrastructure', 'civil works', 'works contract', 'works contracts', 'boq',
                 'bill of quantities', 'engineering', 'rehabilitation']

# ======================= GEOGRAPHY =======================
COUNTRIES = ('Afghanistan|Albania|Algeria|Andorra|Angola|Antigua and Barbuda|Argentina|Armenia|Australia|Austria|Azerbaijan|'
 'Bahamas|Bahrain|Bangladesh|Barbados|Belarus|Belgium|Belize|Benin|Bhutan|Bolivia|Bosnia and Herzegovina|Botswana|Brazil|'
 'Brunei|Bulgaria|Burkina Faso|Burundi|Cabo Verde|Cambodia|Cameroon|Canada|Central African Republic|Chad|Chile|China|'
 'Colombia|Comoros|Republic of the Congo|Costa Rica|Cote d Ivoire|Croatia|Cuba|Cyprus|Czechia|'
 'Democratic Republic of the Congo|Denmark|Djibouti|Dominica|Dominican Republic|Ecuador|Egypt|El Salvador|'
 'Equatorial Guinea|Eritrea|Estonia|Eswatini|Ethiopia|Fiji|Finland|France|Gabon|Gambia|Georgia|Germany|Ghana|Greece|'
 'Grenada|Guatemala|Guinea|Guinea Bissau|Guyana|Haiti|Honduras|Hungary|Iceland|India|Indonesia|Iran|Iraq|Ireland|Israel|'
 'Italy|Jamaica|Japan|Jordan|Kazakhstan|Kenya|Kiribati|Kosovo|Kuwait|Kyrgyzstan|Laos|Latvia|Lebanon|Lesotho|Liberia|Libya|'
 'Liechtenstein|Lithuania|Luxembourg|Madagascar|Malawi|Malaysia|Maldives|Mali|Malta|Marshall Islands|Mauritania|'
 'Mauritius|Mexico|Micronesia|Moldova|Monaco|Mongolia|Montenegro|Morocco|Mozambique|Myanmar|Namibia|Nauru|Nepal|'
 'Netherlands|New Zealand|Nicaragua|Niger|Nigeria|North Korea|North Macedonia|Norway|Oman|Pakistan|Palau|Palestine|Panama|'
 'Papua New Guinea|Paraguay|Peru|Philippines|Poland|Portugal|Qatar|Romania|Russia|Rwanda|Saint Kitts and Nevis|'
 'Saint Lucia|Saint Vincent and the Grenadines|Samoa|San Marino|Sao Tome and Principe|Saudi Arabia|Senegal|Serbia|'
 'Seychelles|Sierra Leone|Singapore|Slovakia|Slovenia|Solomon Islands|Somalia|South Africa|South Korea|South Sudan|Spain|'
 'Sri Lanka|Sudan|Suriname|Sweden|Switzerland|Syria|Tajikistan|Tanzania|Thailand|Timor Leste|Togo|Tonga|'
 'Trinidad and Tobago|Tunisia|Turkiye|Turkmenistan|Tuvalu|Uganda|Ukraine|United Arab Emirates|United Kingdom|'
 'United States|Uruguay|Uzbekistan|Vanuatu|Venezuela|Vietnam|Yemen|Zambia|Zimbabwe').split('|')
ALIASES = {'bosnia': 'Bosnia and Herzegovina', 'bih': 'Bosnia and Herzegovina', 'ivory coast': 'Cote d Ivoire',
    'turkey': 'Turkiye', 'turkiye': 'Turkiye', 'drc': 'Democratic Republic of the Congo', 'dr congo': 'Democratic Republic of the Congo',
    'congo dr': 'Democratic Republic of the Congo', 'syrian arab republic': 'Syria', 'republic of moldova': 'Moldova',
    'lao pdr': 'Laos', 'lao people s democratic republic': 'Laos', 'viet nam': 'Vietnam', 'czech republic': 'Czechia',
    'swaziland': 'Eswatini', 'cape verde': 'Cabo Verde', 'timor-leste': 'Timor Leste', 'united republic of tanzania': 'Tanzania',
    'russian federation': 'Russia', 'state of palestine': 'Palestine', 'occupied palestinian territory': 'Palestine',
    'iran islamic republic of': 'Iran', 'usa': 'United States', 'united states of america': 'United States',
    'uk': 'United Kingdom', 'republic of korea': 'South Korea', 'macedonia': 'North Macedonia',
    'bolivarian republic of venezuela': 'Venezuela', 'plurinational state of bolivia': 'Bolivia',
    'new york': 'United States', 'geneva': 'Switzerland', 'vienna': 'Austria', 'nairobi': 'Kenya', 'bangkok': 'Thailand',
    'rome': 'Italy', 'copenhagen': 'Denmark', 'sarajevo': 'Bosnia and Herzegovina', 'banja luka': 'Bosnia and Herzegovina',
    'mostar': 'Bosnia and Herzegovina', 'tuzla': 'Bosnia and Herzegovina', 'belgrade': 'Serbia', 'pristina': 'Kosovo',
    'podgorica': 'Montenegro', 'skopje': 'North Macedonia', 'tirana': 'Albania', 'zagreb': 'Croatia', 'istanbul': 'Turkiye',
    'ankara': 'Turkiye', 'gaziantep': 'Turkiye', 'amman': 'Jordan', 'beirut': 'Lebanon', 'baghdad': 'Iraq', 'erbil': 'Iraq',
    'kabul': 'Afghanistan', 'juba': 'South Sudan', 'addis ababa': 'Ethiopia', 'dakar': 'Senegal', 'bonn': 'Germany',
    'brussels': 'Belgium', 'the hague': 'Netherlands', 'budapest': 'Hungary', 'kyiv': 'Ukraine', 'kiev': 'Ukraine',
    'mykolaiv': 'Ukraine', 'odesa': 'Ukraine', 'kharkiv': 'Ukraine', 'dnipro': 'Ukraine', 'port au prince': 'Haiti',
    'entebbe': 'Uganda', 'kampala': 'Uganda', 'goma': 'Democratic Republic of the Congo', 'kinshasa': 'Democratic Republic of the Congo',
    'mogadishu': 'Somalia', 'mogadiscio': 'Somalia', 'tunis': 'Tunisia', 'cairo': 'Egypt', 'damascus': 'Syria',
    'sanaa': 'Yemen', 'aden': 'Yemen', 'khartoum': 'Sudan', 'port sudan': 'Sudan', 'dhaka': 'Bangladesh',
    'cox s bazar': 'Bangladesh', 'islamabad': 'Pakistan', 'manila': 'Philippines', 'jakarta': 'Indonesia',
    'kuala lumpur': 'Malaysia', 'ulaanbaatar': 'Mongolia', 'ulan bator': 'Mongolia', 'bishkek': 'Kyrgyzstan',
    'tashkent': 'Uzbekistan', 'astana': 'Kazakhstan', 'chisinau': 'Moldova', 'tbilisi': 'Georgia', 'yerevan': 'Armenia',
    'baku': 'Azerbaijan', 'panama city': 'Panama', 'abidjan': 'Cote d Ivoire', 'maiduguri': 'Nigeria', 'abuja': 'Nigeria',
    'kathmandu': 'Nepal', 'canberra': 'Australia', 'pretoria': 'South Africa', 'monrovia': 'Liberia', 'honiara': 'Solomon Islands',
    'bridgetown': 'Barbados', 'paramaribo': 'Suriname', 'la habana': 'Cuba', 'havana': 'Cuba', 'antananarivo': 'Madagascar'}
EU = {'Austria', 'Belgium', 'Bulgaria', 'Croatia', 'Cyprus', 'Czechia', 'Denmark', 'Estonia', 'Finland', 'France', 'Germany',
      'Greece', 'Hungary', 'Ireland', 'Italy', 'Latvia', 'Lithuania', 'Luxembourg', 'Malta', 'Netherlands', 'Poland',
      'Portugal', 'Romania', 'Slovakia', 'Slovenia', 'Spain', 'Sweden'}
BALKANS = {'Serbia', 'Montenegro', 'Croatia', 'North Macedonia', 'Albania', 'Kosovo', 'Slovenia'}
EUROPE = EU | BALKANS | {'Switzerland', 'Norway', 'Iceland', 'United Kingdom', 'Ukraine', 'Moldova', 'Turkiye', 'Georgia',
                         'Armenia', 'Azerbaijan', 'Belarus'}
OTHER_LANGS = ['arabic', 'spanish', 'portuguese', 'russian', 'chinese', 'ukrainian', 'turkish', 'german', 'dari', 'pashto',
    'amharic', 'swahili', 'kiswahili', 'farsi', 'persian', 'urdu', 'hindi', 'bengali', 'bangla', 'somali', 'hausa',
    'tigrinya', 'kurdish', 'albanian', 'macedonian', 'romanian', 'greek', 'polish', 'japanese', 'korean', 'indonesian',
    'thai', 'burmese', 'khmer', 'lao', 'vietnamese', 'georgian', 'armenian', 'azerbaijani', 'kazakh', 'kyrgyz', 'uzbek',
    'tajik', 'mongolian', 'creole', 'dutch', 'hungarian', 'bulgarian', 'malagasy', 'tetum', 'nepali', 'sinhala', 'tamil']


# ======================= TEXT HELPERS =======================
def norm(s):
    s = html.unescape(re.sub(r'<[^>]*>', ' ', s or ''))
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def has(text_normed, phrase):
    return f' {norm(phrase)} ' in f' {text_normed} '


def plain(s, limit=None):
    s = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', s or ''))).strip()
    return s[:limit] if limit else s


def safe_url(u):
    try:
        p = urllib.parse.urlsplit(u)
        return p.scheme in ('https', 'http') and bool(p.hostname) and not p.username
    except ValueError:
        return False


def canonical(u):
    p = urllib.parse.urlsplit(u)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith('utm_')]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, urllib.parse.urlencode(q), ''))


_COUNTRY_KEYS = sorted([(norm(c), c) for c in COUNTRIES] + [(norm(k), v) for k, v in ALIASES.items()],
                       key=lambda kv: -len(kv[0]))


def find_country(text):
    """Earliest mention wins; ties go to the longer name ('papua new guinea' beats 'guinea')."""
    t = f' {norm(text)} '
    best = None
    for key, country in _COUNTRY_KEYS:
        i = t.find(f' {key} ')
        if i >= 0 and (best is None or i < best[0]):
            best = (i, country)
    return best[1] if best else None


def iso_date(value):
    m = re.match(r'(\d{4}-\d{2}-\d{2})', str(value or ''))
    if not m:
        return None
    try:
        return dt.date.fromisoformat(m[1]).isoformat()
    except ValueError:
        return None


def labelled_deadline(text):
    """Only labelled, unambiguous dates. Never guessed."""
    m = re.search(r'(?:deadline|closing date|application deadline|apply by|apply before|closes on)\s*:?\s*'
                  r'(\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})', plain(text), re.I)
    if not m:
        return None
    for fmt in ('%Y-%m-%d', '%d %B %Y', '%d %b %Y', '%B %d, %Y', '%B %d %Y', '%b %d, %Y', '%b %d %Y'):
        try:
            return dt.datetime.strptime(m[1], fmt).date().isoformat()
        except ValueError:
            pass
    return None


# ======================= RELEVANCE =======================
def relevance(title, desc=''):
    t, d = norm(title), norm(desc)
    if any(has(t, x) for x in TITLE_EXCLUDE):
        return 0, ''
    if any(has(t, x) for x in ('procurement specialist', 'procurement officer')) and not any(has(t + ' ' + d, x) for x in WORKS_CONTEXT):
        return 0, ''
    scores = {}
    for track, terms in TRACKS.items():
        scores[track] = sum(w if has(t, p) else (w // 3 if has(d, p) else 0) for p, w in terms.items())
    track = max(scores, key=scores.get)
    return (scores[track], track) if scores[track] >= RELEVANCE_MIN else (0, '')


# ======================= ELIGIBILITY =======================
LOCAL_POST = re.compile(r'\b(no [abcd1-4]|no[abcd]|national officer|national unv|national un volunteer|national professional officer|npsa ?\d*|'
    r'national personnel service agreement|national consultant|local consultant|national individual consultant|'
    r'lica ?\d*|local individual contractor|g ?[1-7]|gs ?[1-7]|general service|nationals? only|national position|'
    r'local recruitment|locally recruited)\b')
GRADE_IN_TEXT = re.compile(r'\b(?:position level|grade|level|contract type)\s*:?\s*(npsa ?\d+|no ?[a-d1-4]|g ?[1-7]|gs ?[1-7]|'
                           r'national psa|lica ?\d*|national officer)\b', re.I)
LANG_CONTEXT = ('fluency', 'fluent', 'proficiency', 'proficient', 'knowledge of', 'command of', 'language', 'languages',
                'written and spoken', 'oral and written', 'spoken and written')
REQUIRED = ('required', 'essential', 'mandatory', 'must', 'is a requirement', 'requirement')
DESIRABLE = ('desirable', 'asset', 'advantage', 'advantageous', 'preferred', 'an added', 'a plus', 'would be')
WORDNUM = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
           'ten': 10, 'eleven': 11, 'twelve': 12, 'fifteen': 15, 'twenty': 20}


def sentences(text):
    return [s for s in re.split(r'[.;\n\u2022]+', plain(text)) if s.strip()]


def level_points(t):
    if re.search(r'\b(p ?[56]|d ?[12]|no ?d|nod|no ?4|ipsa ?1[2-6]|senior|chief|head of|lead|principal)\b', t):
        return 20, 'Senior level'
    if re.search(r'\b(p ?4|no ?c|noc|no ?3|ipsa ?1[01]|manager|specialist|team leader|coordinator)\b', t):
        return 20, 'Specialist/manager level'
    if re.search(r'\b(p ?3|no ?b|nob|no ?2|ipsa ?[89]|officer|engineer|consultant|architect|surveyor)\b', t):
        return 16, 'Professional level'
    if re.search(r'\b(p ?[12]|no ?a|noa|no ?1|npsa ?(8|9|10)|associate|analyst)\b', t):
        return 8, 'Junior professional level (you are overqualified)'
    if re.search(r'\b(g ?[1-7]|gs ?[1-7]|npsa ?[1-7]|assistant|technician|support)\b', t):
        return 4, 'Support level (you are strongly overqualified)'
    return 10, 'Level not stated'


def duty_country(title, location, desc):
    for src in (location, title):
        c = find_country(src or '')
        if c:
            return c
    for s in sentences(desc)[:80]:
        m = re.search(r'(?:duty station|location|based in|place of assignment)\s*:?\s*(.{0,80})', s, re.I)
        if m:
            c = find_country(m[1])
            if c:
                return c
    return None


def eligibility(job):
    """Rules-based estimate against PROFILE. Returns status, score 0-100, reasons [(mark, text)]."""
    title, desc, loc = job.get('title', ''), job.get('text', ''), job.get('location', '')
    head = norm(' '.join([title, loc, job.get('grade', '')]))
    full = norm(' '.join([title, loc, job.get('grade', ''), desc]))
    nat = set(PROFILE['nationalities'])
    rights = nat | set(PROFILE['work_rights'])
    reasons, hard, soft, unknown = [], False, 0, False

    def add(mark, text):
        reasons.append((mark, text))

    # --- hard gates ---------------------------------------------------------
    tier = re.search(r'\b(?:tiers?|niveaux?|niveles?)\s+((?:\d\s*(?:and|et|y)?\s*)+)', head)
    staff = job.get('source') in PROFILE['current_staff_of']
    external = any(has(head, w) for w in ('external', 'externes', 'externos', 'all applicants'))
    if tier and '3' not in re.findall(r'\d', tier[1]) and not external and not staff:
        hard = True; add('✖', 'Internal tiers only (Tier 3/external not invited)')
    if any(has(full, p) for p in ('internal candidates only', 'internal applicants only', 'open to internal candidates only',
                                  'current staff members only', 'internal vacancy')) and not staff:
        hard = True; add('✖', 'Internal candidates only')
    country = duty_country(title, loc, desc)
    remote = any(has(head, p) for p in ('home based', 'remote', 'homebased'))
    m = re.search(r'([a-z][a-z ]{2,40}?) nationals? only', full) or re.search(r'nationals? of ([a-z ]{3,60}?) only', full) \
        or re.search(r'only (?:open to |for )?nationals of ([a-z ]{3,60})', full)
    if m or has(full, 'nationals only'):
        nc = (find_country(m[1]) if m else None) or country
        if nc is None:
            unknown = True; add('?', 'Nationals-only post; country not identified - check')
        elif nc in nat:
            add('✔', f'Nationals-only post in {nc}: you qualify')
        else:
            hard = True; add('✖', f'Open only to nationals of {nc}')
    if re.search(r'nationals of (the )?(eu|european union)|eu nationals|eu eea|european union nationals', full):
        if nat & EU:
            add('✔', 'EU/EEA nationality requirement met')
        else:
            hard = True; add('✖', 'Open only to EU/EEA/Swiss nationals')
    local = LOCAL_POST.search(head) or GRADE_IN_TEXT.search(plain(desc))
    if local and not hard:
        if country is None:
            unknown = True; add('?', 'Locally recruited post; duty country not identified - check work rights')
        elif country in rights:
            add('✔', f'Local post in {country}: you have work rights')
        else:
            hard = True; add('✖', f'Locally recruited post in {country}: requires nationality/work permit there')
    years_req = []
    for s in sentences(desc):
        sn = norm(s)
        if 'experience' in sn and 'year' in sn and re.search(
                r'\b(minimum|at least|required|requires|requirement|years? of (relevant|professional|progressive|'
                r'progressively|work|working|practical)|years? (relevant|professional) experience)\b', sn):
            for n in re.findall(r'\b(\d{1,2})\s*(?:\+\s*)?(?:years?|yrs)', sn):
                if int(n) <= 35:
                    years_req.append(int(n))
            for w, n in WORDNUM.items():
                if re.search(rf'\b{w}\s+(?:\d+\s+)?years?\b', sn):
                    years_req.append(n)
    if years_req and max(years_req) > PROFILE['years_experience']:
        hard = True; add('✖', f'Requires {max(years_req)} years experience; you have {PROFILE["years_experience"]}')

    # --- deadline -------------------------------------------------------------
    end = job.get('deadline')
    if end:
        days = (dt.date.fromisoformat(end) - TODAY()).days
        if days < 0:
            hard = True; add('✖', f'Deadline passed ({end})')
        else:
            add('✔', f'Open until {end} ({days} day{"s" if days != 1 else ""} left)')
    else:
        unknown = True; soft += 3; add('?', 'Deadline not published by source - check before applying')

    # --- fit points -------------------------------------------------------------
    rel = job.get('relevance', 0)
    tech = min(40, rel)
    add('✔' if tech >= 24 else '•', f'Technical match {job.get("track", "")}: {tech}/40')
    lvl, lvl_txt = level_points(head)
    add('✔' if lvl >= 16 else '•', f'{lvl_txt}: {lvl}/20')
    if country in rights:
        loc_pts, loc_txt = 15, f'Duty station in {country}'
    elif remote:
        loc_pts, loc_txt = 12, 'Home-based/remote'
    elif country in BALKANS:
        loc_pts, loc_txt = 10, f'Western Balkans ({country})'
    elif country in EUROPE:
        loc_pts, loc_txt = 8, f'Europe ({country})'
    elif country:
        loc_pts, loc_txt = 5, f'Duty station {country}'
    else:
        loc_pts, loc_txt = 5, 'Duty station not identified'
    add('✔' if loc_pts >= 10 else '•', f'{loc_txt}: {loc_pts}/15')

    have_desc = len(plain(desc)) >= 300
    req = 0
    if not have_desc:
        unknown = True; req = 10
        add('?', 'Full description not available: experience, degree and language requirements not verified (10/25)')
    else:
        if years_req:
            req += 10; add('✔', f'Experience requirement {max(years_req)} years: you have {PROFILE["years_experience"]}')
        else:
            req += 6; add('?', 'Years of experience not stated')
        deg = [norm(s) for s in sentences(desc) if 'degree' in norm(s)]
        if deg:
            req += 5; add('✔', 'Degree level met (PhD)')
            dtext = ' '.join(deg)
            if any(has(dtext, f) for f in ('architecture', 'architectural', 'architect', 'built environment', 'heritage',
                                           'urban planning', 'related field', 'related discipline', 'relevant field',
                                           'related area', 'equivalent')):
                req += 5; add('✔', 'Degree field matches (architecture/engineering or related)')
            elif has(dtext, 'civil engineering'):
                soft += 8; req += 1; add('?', 'Asks for civil engineering degree: confirm your architecture/architectural engineering degrees are accepted')
            elif has(dtext, 'engineering'):
                req += 5; add('✔', 'Engineering degree requested: PhD Architectural Engineering')
            else:
                req += 2; add('?', 'Degree field unclear')
        else:
            req += 7; add('?', 'Degree requirement not stated')
        missing = []
        for lang in OTHER_LANGS:
            for s in sentences(desc):
                sn = norm(s)
                if has(sn, lang) and any(has(sn, c) for c in LANG_CONTEXT) \
                        and any(has(sn, r) for r in REQUIRED + ('fluency', 'fluent', 'proficiency', 'proficient')) \
                        and not any(has(sn, d) for d in DESIRABLE):
                    missing.append(lang.capitalize())
                    break
        if missing:
            soft += 25; add('✖', f'Required language(s) not in your profile: {", ".join(sorted(set(missing)))}')
        else:
            req += 5; add('✔', 'No unmet required language found')
    score = max(0, min(100, tech + lvl + loc_pts + req - soft))
    if hard:
        status, score = 'INELIGIBLE', 0
    elif unknown or soft >= 8:
        status = 'CHECK'
    else:
        status = 'ELIGIBLE'
    return dict(status=status, score=score, reasons=reasons, country=country)


# ======================= NETWORK =======================
def http_get(url, accept='*/*'):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError(f'Response exceeds {MAX_BYTES} byte safety limit')
        return raw, r.headers.get('Content-Type', ''), r.geturl()


_ROBOTS = {}


def permitted(url, get=http_get):
    """RFC 9309: robots 4xx = no restrictions; 5xx/network failure = do not crawl."""
    p = urllib.parse.urlsplit(url)
    origin = f'{p.scheme}://{p.netloc}'
    if origin not in _ROBOTS:
        try:
            raw, _, _ = get(origin + '/robots.txt', 'text/plain')
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(raw.decode('utf-8', 'replace').splitlines())
            _ROBOTS[origin] = rp
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                _ROBOTS[origin] = None
            else:
                raise PermissionError(f'robots.txt unavailable (HTTP {e.code}); not crawling')
    rp = _ROBOTS[origin]
    if rp is not None and not rp.can_fetch('DamirJobRadar', url):
        raise PermissionError('robots.txt disallows automated collection')


# ======================= ORACLE RECRUITING CLOUD (UNDP, IOM) =======================
def oracle_list_url(origin, site, offset, limit=25, version='latest'):
    finder = f'findReqs;siteNumber={site},limit={limit},offset={offset},sortBy=POSTING_DATES_DESC'
    return (f'{origin}/hcmRestApi/resources/{version}/recruitingCEJobRequisitions?onlyData=true'
            f'&expand=requisitionList.secondaryLocations&finder={urllib.parse.quote(finder, safe=";,=")}')


def oracle_detail_url(origin, site, job_id, version='latest'):
    finder = f'ById;Id="{job_id}",siteNumber={site}'
    return (f'{origin}/hcmRestApi/resources/{version}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true'
            f'&finder={urllib.parse.quote(finder, safe=";,=")}')


def oracle_job_url(origin, site, job_id):
    return f'{origin}/hcmUI/CandidateExperience/en/sites/{site}/job/{job_id}'


def oracle_parse_list(payload):
    items = (payload or {}).get('items') or []
    if not items:
        return [], 0
    head = items[0]
    total = int(head.get('TotalJobsCount') or 0)
    return list(head.get('requisitionList') or []), total


def flatten_strings(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (str, int, float)) and k in ('Prompt', 'Name', 'Label'):
                out.append(str(v))
            flatten_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            flatten_strings(v, out)
    elif isinstance(obj, str) and obj.strip():
        out.append(obj)


def end_date_from(item):
    for k, v in item.items():
        if 'enddate' in k.lower().replace('_', ''):
            d = iso_date(v)
            if d:
                return d
    return None


def oracle_collect(name, origin, site, get_json, sleep=0.25):
    """get_json(url) -> dict. Returns (jobs, info)."""
    rows, offset, total, version = [], 0, None, 'latest'
    while True:
        try:
            payload = get_json(oracle_list_url(origin, site, offset, version=version))
        except urllib.error.HTTPError as e:
            if e.code == 404 and version == 'latest' and offset == 0:
                version = '11.13.18.05'
                continue
            raise
        page, total = oracle_parse_list(payload)
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total or offset >= ORACLE_MAX_JOBS:
            break
        time.sleep(sleep)
    if not rows:
        raise ValueError(f'Oracle API returned no requisitions (TotalJobsCount={total})')
    candidates, rejected = [], []
    for r in rows:
        title = r.get('Title') or ''
        pre, _ = relevance(title, r.get('ShortDescriptionStr') or '')
        loose = re.search(r'engineer|construct|infrastructur|wash|water|sanitation|architect|facilit|works|shelter|'
                          r'rehabilit|technical officer|site ', title, re.I)
        (candidates if (pre or loose) else rejected).append((pre, r))
    candidates.sort(key=lambda x: -x[0])
    jobs, detailed, expired = [], 0, 0
    for i, (_, r) in enumerate(candidates):
        jid = str(r.get('Id') or '').strip()
        if not jid:
            continue
        text_parts = [r.get('ShortDescriptionStr') or '']
        end = end_date_from(r)
        grade = ''
        if i < ORACLE_DETAIL_CAP:
            try:
                det = (get_json(oracle_detail_url(origin, site, jid, version)) or {}).get('items') or []
                if det:
                    d = det[0]
                    detailed += 1
                    end = iso_date(d.get('ExternalPostedEndDate')) or end
                    flex = []
                    flatten_strings({k: v for k, v in d.items() if 'flex' in k.lower()}, flex)
                    grade = ' '.join([str(d.get(k) or '') for k in ('JobGrade', 'JobLevel', 'ContractType', 'WorkerType')] + flex)
                    parts = []
                    flatten_strings({k: v for k, v in d.items() if k not in ('ExternalContactEmail', 'HiringManager')}, parts)
                    text_parts.append(' '.join(parts))
                time.sleep(sleep)
            except Exception:
                pass
        if end and end < TODAY().isoformat():
            expired += 1
            continue
        text = ' '.join(text_parts)
        rel, track = relevance(r.get('Title') or '', text)
        if not rel:
            rejected.append((0, r))
            continue
        jobs.append(dict(title=plain(r.get('Title')), url=oracle_job_url(origin, site, jid), source=name,
                         location=plain(r.get('PrimaryLocation') or ''), grade=plain(grade), deadline=end,
                         text=plain(text, 6000), relevance=rel, track=track,
                         oracle=dict(origin=origin, site=site, id=jid)))
    info = dict(format='Oracle JSON', parsed=len(rows), expired=expired, detailed=detailed,
                rejected=[plain(r.get('Title')) for _, r in rejected[:10]])
    return jobs, info


def json_getter(get=http_get):
    def get_json(url):
        raw, ctype, _ = get(url, 'application/json')
        return json.loads(raw.decode('utf-8', 'replace'))
    return get_json


def oracle_browser_run(name, origin, site):
    """Fallback: load the public page in Chromium, then call the same JSON endpoints from that browser session."""
    from playwright.sync_api import sync_playwright
    page_url = f'{origin}/hcmUI/CandidateExperience/en/sites/{site}/requisitions'
    permitted(page_url)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(page_url, wait_until='networkidle', timeout=90000)

            def get_json(url):
                resp = page.request.get(url, headers={'Accept': 'application/json'}, timeout=30000)
                if resp.status >= 400:
                    raise urllib.error.HTTPError(url, resp.status, resp.status_text, None, None)
                return resp.json()
            return oracle_collect(name, origin, site, get_json)
        finally:
            browser.close()


def oracle_run(name, origin, site, get=http_get, browser=oracle_browser_run):
    errors = []
    try:
        permitted(f'{origin}/hcmRestApi/resources/latest/recruitingCEJobRequisitions', get)
    except PermissionError as e:
        return name, [], dict(ok=False, message=f'PermissionError: {e}')
    try:
        jobs, info = oracle_collect(name, origin, site, json_getter(get))
        return name, jobs, status_ok(info, len(jobs))
    except Exception as e:
        errors.append(f'JSON API: {type(e).__name__}: {str(e)[:150]}')
    try:
        jobs, info = browser(name, origin, site)
        info['format'] = 'Oracle JSON via browser session'
        return name, jobs, status_ok(info, len(jobs))
    except ImportError:
        errors.append('Browser fallback: Playwright not installed')
    except Exception as e:
        errors.append(f'Browser fallback: {type(e).__name__}: {str(e)[:150]}')
    return name, [], dict(ok=False, message=' | '.join(errors))


def status_ok(info, matches):
    extra = f", {info['detailed']} detailed" if 'detailed' in info else ''
    return dict(ok=True, message=f"{info['format']}: {info['parsed']} records{extra}, {matches} relevant, "
                                 f"{info['expired']} expired removed", rejected_examples=info.get('rejected', []))


# ======================= RSS / ATOM / HTML SOURCES =======================
class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href, self.text, self.rows, self.base = None, [], [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'base' and a.get('href') and self.base is None:
            self.base = a['href']
        if tag == 'a':
            self.href, self.text = a.get('href'), [a.get('aria-label') or a.get('title') or '']

    def handle_data(self, s):
        if self.href is not None:
            self.text.append(s)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.rows.append((self.href, re.sub(r'\s+', ' ', ' '.join(self.text)).strip()))
            self.href = None


def decode(raw, ctype):
    m = re.search(r'charset=([\w-]+)', ctype or '', re.I)
    try:
        return raw.decode(m[1] if m else 'utf-8', errors='replace').lstrip('\ufeff').strip()
    except LookupError:
        return raw.decode('utf-8', errors='replace').lstrip('\ufeff').strip()


def parse_feed(raw, ctype, base, source, pattern=None):
    text = decode(raw, ctype)
    if not text:
        raise ValueError('Empty response')
    if re.search(r'captcha|verify you are human|just a moment|access denied', text[:4000], re.I):
        raise PermissionError('Access challenge; not bypassed')
    rows, mode = [], 'XML'
    if not re.search(r'<(?:rss|feed|rdf:RDF)\b', text[:2000], re.I) and re.search(r'<!doctype\s+html|<html\b', text[:2000], re.I):
        mode = 'HTML'
        if not pattern:
            raise ValueError('HTML page returned where a feed was expected')
        p = Links()
        p.feed(text)
        page_base = urllib.parse.urljoin(base, p.base) if p.base else base
        for href, title in p.rows:
            if not href:
                continue
            url = urllib.parse.urljoin(page_base, href)
            if re.search(pattern, urllib.parse.urlsplit(url).path, re.I) and len(title) > 5:
                rows.append((title, url, '', ''))
    else:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            fixed = re.sub(r'&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]+;)', '&amp;', text)
            fixed = re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f]', '', fixed)
            root = ET.fromstring(fixed)
            mode = 'XML (limited repair)'
        if root.tag.split('}')[-1].lower() not in ('rss', 'feed', 'rdf'):
            raise ValueError('Response is not a supported feed')
        for item in root.iter():
            if item.tag.split('}')[-1] not in ('item', 'entry'):
                continue
            fields = {c.tag.split('}')[-1]: c for c in item}

            def val(k):
                e = fields.get(k)
                return ''.join(e.itertext()).strip() if e is not None else ''
            link = val('link')
            if not link and fields.get('link') is not None:
                link = fields['link'].get('href', '')
            loc = val('location') or val('city') or val('country')
            rows.append((val('title'), urllib.parse.urljoin(base, link),
                         val('description') or val('summary') or val('content') or val('encoded'), loc))
    jobs, rejected, expired = [], [], 0
    for title, url, desc, loc in rows:
        if not safe_url(url):
            continue
        end = labelled_deadline(desc)
        if end and end < TODAY().isoformat():
            expired += 1
            continue
        rel, track = relevance(title, desc)
        if not rel:
            rejected.append(plain(title))
            continue
        jobs.append(dict(title=plain(title), url=canonical(url), source=source, location=plain(loc), grade='',
                         deadline=end, text=plain(desc, 6000), relevance=rel, track=track))
    return jobs, dict(format=mode, parsed=len(rows), expired=expired, rejected=rejected[:10])


def feed_run(name, urls, get=http_get, pattern=None):
    attempts = []
    for url in urls:
        try:
            permitted(url, get)
            raw, ctype, final = get(url, 'application/rss+xml,application/atom+xml,text/xml,text/html;q=0.8,*/*;q=0.5')
            jobs, info = parse_feed(raw, ctype, final, name, pattern)
            if not info['parsed']:
                raise ValueError('No recognized vacancy records (site layout may have changed)')
            return name, jobs, status_ok(info, len(jobs))
        except Exception as e:
            attempts.append(f'{type(e).__name__}: {str(e)[:150]}')
    return name, [], dict(ok=False, message=' | '.join(attempts))


# ======================= RETENTION + MERGE =======================
CLOSED_MARKERS = re.compile(r'no longer available|position has been filled|vacancy (?:is|has been) closed|'
                            r'posting has expired|job (?:is|has) closed|no longer accepting', re.I)


def still_open(job, get=http_get):
    """'open' | 'closed' | 'unverified'."""
    if job.get('deadline') and job['deadline'] < TODAY().isoformat():
        return 'closed'
    try:
        if job.get('oracle'):
            o = job['oracle']
            items = (json_getter(get)(oracle_detail_url(o['origin'], o['site'], o['id'])) or {}).get('items') or []
            return 'open' if items else 'closed'
        raw, ctype, _ = get(job['url'], 'text/html,*/*')
        return 'closed' if CLOSED_MARKERS.search(decode(raw, ctype)[:200000]) else 'unverified'
    except urllib.error.HTTPError as e:
        return 'closed' if e.code in (404, 410) else 'unverified'
    except Exception:
        return 'unverified'


def merge(old, results, verify=still_open):
    previous = {j['url']: j for j in (old or {}).get('jobs', []) if safe_url(j.get('url', ''))}
    out, health = {}, {}
    for name, jobs, status in results:
        health[name] = status
        if not status['ok']:
            kept = []
            for j in previous.values():
                if j.get('source') != name:
                    continue
                try:
                    age = NOW() - dt.datetime.fromisoformat(j['last_seen'])
                except (KeyError, ValueError, TypeError):
                    continue
                if age > dt.timedelta(days=7):
                    continue
                state = verify(j)
                if state == 'closed':
                    continue
                if state == 'unverified' and not j.get('deadline') and age > dt.timedelta(days=3):
                    continue
                kept.append(dict(j, retained=True, verified=state))
            jobs = kept
        for j in jobs:
            j = dict(j)
            j.setdefault('last_seen', NOW().isoformat())
            j.setdefault('retained', False)
            j['new'] = j['url'] not in previous
            j.update(eligibility(j))
            out.setdefault(j['url'], j)
    order = {'ELIGIBLE': 0, 'CHECK': 1, 'INELIGIBLE': 2}
    ranked = sorted(out.values(), key=lambda j: (order[j['status']], -j['score'], j.get('deadline') or '9999', j['title']))
    return dict(updated=NOW().strftime('%Y-%m-%d %H:%M'), version=VERSION, jobs=ranked, sources=health,
                profile=dict(nationalities=PROFILE['nationalities'], years=PROFILE['years_experience']))


# ======================= DASHBOARD =======================
PAGE = r"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Damir Job Radar</title><style>
body{font:15px/1.45 system-ui,Segoe UI,Arial,sans-serif;max-width:1040px;margin:0 auto;padding:16px;background:#f2f5f8;color:#14212e}
header{background:#123a55;color:#fff;padding:20px 24px;border-radius:12px}header h1{margin:0 0 4px;font-size:24px}
#stats{margin:6px 0 0;opacity:.92}.bar{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
input,select{padding:10px;border:1px solid #b8c4cf;border-radius:8px;font-size:15px}input{flex:1;min-width:220px}
article{display:flex;gap:14px;background:#fff;border:1px solid #dbe3ea;border-radius:10px;padding:14px;margin:10px 0}
.sc{flex:0 0 64px;height:64px;border-radius:50%;display:flex;align-items:center;justify-content:center;font:700 22px system-ui;color:#fff}
.ELIGIBLE .sc{background:#1a7f37}.CHECK .sc{background:#b07800}.INELIGIBLE .sc{background:#8c959f}
.st{font-weight:700;font-size:12px;letter-spacing:.04em}.ELIGIBLE .st{color:#1a7f37}.CHECK .st{color:#9a6700}.INELIGIBLE .st{color:#6e7781}
h2{font-size:17px;margin:2px 0 4px}a{color:#0b5cad;text-decoration:none}a:hover{text-decoration:underline}
.meta{color:#4b5a68;font-size:13px}.tag{display:inline-block;background:#0969da;color:#fff;border-radius:5px;padding:0 6px;font-size:12px;margin-left:6px}
.urgent{color:#cf222e;font-weight:600}details{margin-top:6px}summary{cursor:pointer;color:#0b5cad;font-size:13px}
ul.r{margin:6px 0 0;padding-left:18px;font-size:13px}.box{background:#fff;border:1px solid #dbe3ea;border-radius:10px;padding:12px 16px;margin:12px 0}
.warn{background:#fff8c5;border:1px solid #d4a72c;border-radius:10px;padding:12px}footer{color:#4b5a68;font-size:13px;margin:16px 0}
</style>
<header><h1>Damir's Job Radar</h1><div>Construction · Infrastructure · WASH · Contracts · Facilities · Architecture</div><div id=stats></div></header>
<div class=bar><input id=q placeholder="Search title, organisation, country" aria-label=Search>
<select id=status aria-label=Status><option value=active>Eligible + Check</option><option value=ELIGIBLE>Eligible only</option>
<option value=CHECK>Check only</option><option value=INELIGIBLE>Ineligible (with reason)</option><option value=all>All</option></select>
<select id=track aria-label=Track><option value="">All tracks</option></select></div>
<main id=jobs></main>
<details class=box><summary>Source health</summary><ul id=health></ul></details>
<details class=box><summary>Manual search links (not automatically collected)</summary><ul id=manual></ul></details>
<footer>Eligibility score (0-100) = technical match 40 + level 20 + location 15 + requirements 25, minus penalties.
Hard gates (internal-only, nationals-only elsewhere, local posts without work rights, EU-only, experience, passed deadline) set INELIGIBLE.
✔ met · ✖ not met · ? not verifiable from the posting · • information. CHECK = something could not be verified. It is a rules-based estimate from the posting text and the profile in radar.py,
not an official decision: confirm on the original vacancy. Retained = source failed this run; vacancy re-checked where possible.
No AI, no email, no paid API.</footer>
<script>
const D=__DATA__,el=id=>document.getElementById(id);
function card(j){const a=document.createElement('article');a.className=j.status;
const sc=document.createElement('div');sc.className='sc';sc.textContent=j.status==='INELIGIBLE'?'–':String(j.score);
const b=document.createElement('div');const st=document.createElement('div');st.className='st';st.textContent=j.status;
const h=document.createElement('h2');let u;try{u=new URL(j.url)}catch(e){u=null}
if(u&&['http:','https:'].includes(u.protocol)){const l=document.createElement('a');l.href=u.href;l.target='_blank';l.rel='noopener noreferrer';l.textContent=j.title;h.append(l)}else h.textContent=j.title;
if(j.new){const t=document.createElement('span');t.className='tag';t.textContent='NEW';h.append(t)}
if(j.retained){const t=document.createElement('span');t.className='tag';t.style.background='#6e7781';t.textContent='RETAINED ('+j.verified+')';h.append(t)}
const m=document.createElement('div');m.className='meta';
const parts=[j.source,j.location||j.country||'Location n/a',j.track];if(j.grade)parts.push(j.grade);m.textContent=parts.join(' · ');
const dl=document.createElement('div');dl.className='meta';
if(j.deadline){const days=Math.round((new Date(j.deadline+'T23:59:59Z')-Date.now())/864e5);dl.textContent='Deadline '+j.deadline+' ('+days+' days)';if(days<=3)dl.classList.add('urgent')}
else dl.textContent='Deadline not published by source';
const det=document.createElement('details');const su=document.createElement('summary');su.textContent='Why this result';
const ul=document.createElement('ul');ul.className='r';for(const [mk,tx] of j.reasons){const li=document.createElement('li');li.textContent=mk+' '+tx;ul.append(li)}
det.append(su,ul);b.append(st,h,m,dl,det);a.append(sc,b);return a}
function render(){const q=el('q').value.toLowerCase(),s=el('status').value,t=el('track').value;el('jobs').replaceChildren();let n=0;
for(const j of D.jobs){if(s==='active'&&j.status==='INELIGIBLE')continue;if(!['active','all'].includes(s)&&j.status!==s)continue;
if(t&&j.track!==t)continue;if(![j.title,j.source,j.location,j.country,j.track].join(' ').toLowerCase().includes(q))continue;el('jobs').append(card(j));n++}
if(!n){const p=document.createElement('p');p.className='warn';p.textContent='No results for this filter. Check Source health below: an empty list is not proof that no vacancies exist.';el('jobs').append(p)}}
const c=k=>D.jobs.filter(j=>j.status===k).length,src=Object.values(D.sources);
el('stats').textContent=`Updated ${D.updated} UTC · ${c('ELIGIBLE')} eligible · ${c('CHECK')} to check · ${c('INELIGIBLE')} ineligible · ${src.filter(s=>s.ok).length}/${src.length} sources OK`;
for(const [n,s] of Object.entries(D.sources)){const li=document.createElement('li');
li.textContent=`${n}: ${s.ok?'OK':'UNAVAILABLE'} - ${s.message}`+(s.rejected_examples&&s.rejected_examples.length?` | Not relevant (examples): ${s.rejected_examples.join('; ')}`:'');el('health').append(li)}
for(const t of [...new Set(D.jobs.map(j=>j.track))].sort())el('track').add(new Option(t,t));
for(const [n,u] of D.manual){const li=document.createElement('li'),a=document.createElement('a');a.href=u;a.target='_blank';a.rel='noopener noreferrer';a.textContent=n;li.append(a);el('manual').append(li)}
el('q').oninput=render;el('status').onchange=render;el('track').onchange=render;render();
</script></html>"""


def build_page(data):
    slim = [{k: v for k, v in j.items() if k not in ('text', 'oracle')} for j in data['jobs']]
    payload = json.dumps(dict(data, jobs=slim, manual=MANUAL), ensure_ascii=True)
    payload = payload.replace('<', r'\u003c').replace('>', r'\u003e').replace('&', r'\u0026')
    return PAGE.replace('__DATA__', payload)


def summary_md(data):
    c = lambda k: sum(j['status'] == k for j in data['jobs'])
    ok = sum(s['ok'] for s in data['sources'].values())
    lines = [f'# Job Radar {VERSION}', '', f"{c('ELIGIBLE')} eligible · {c('CHECK')} to check · {c('INELIGIBLE')} ineligible · "
             f"{ok}/{len(data['sources'])} sources OK", '', '| Status | Score | Job | Source | Deadline |', '|---|---:|---|---|---|']
    for j in [j for j in data['jobs'] if j['status'] != 'INELIGIBLE'][:25]:
        lines.append(f"| {j['status']} | {j['score']} | [{j['title'].replace('|', '/')}]({j['url']}) | {j['source']} | {j.get('deadline') or 'n/a'} |")
    lines += ['', '## Sources', ''] + [f"- {n}: {'OK' if s['ok'] else 'UNAVAILABLE'} - {s['message']}" for n, s in data['sources'].items()]
    return '\n'.join(lines) + '\n'


def run():
    old = {}
    try:
        raw, _, _ = http_get(os.environ.get('PREVIOUS_DATA_URL', ''), 'application/json')
        old = json.loads(raw)
    except Exception:
        pass
    tasks = [(oracle_run, (n, o, s)) for n, (o, s) in ORACLE.items()]
    tasks += [(feed_run, (n, urls)) for n, urls in FEEDS.items()]
    tasks += [(lambda n, u, p: feed_run(n, [u], pattern=p), (n, u, p)) for n, (u, p) in HTML_SOURCES.items()]
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda t: t[0](*t[1]), tasks))
    data = merge(old, results)
    Path('site').mkdir(exist_ok=True)
    Path('site/index.html').write_text(build_page(data), encoding='utf-8')
    Path('site/jobs.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    md = summary_md(data)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(md)
    print(md)


# ======================= TESTS =======================
class Tests(unittest.TestCase):
    def setUp(self):
        _ROBOTS.clear()

    @staticmethod
    def job(title, text='', location='', deadline='2099-01-01', source='UNDP', grade=''):
        rel, track = relevance(title, text)
        return dict(title=title, text=text, location=location, deadline=deadline, source=source, grade=grade,
                    relevance=rel, track=track, url='https://x.org/1')

    LONG = (' Duties include construction supervision of civil works, BoQ review and contract management. ' * 4 +
            'Advanced university degree in architecture, civil engineering or related field. '
            'Minimum 7 years of experience in construction management. Fluency in English is required.')

    # --- Oracle ---
    def test_oracle_list_url(self):
        u = oracle_list_url('https://h', 'CX_1', 25)
        self.assertIn('/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true', u)
        self.assertIn('finder=findReqs;siteNumber=CX_1,limit=25,offset=25,sortBy=POSTING_DATES_DESC', u)

    def test_oracle_detail_url(self):
        self.assertIn('finder=ById;Id=%2235117%22,siteNumber=CX_1', oracle_detail_url('https://h', 'CX_1', '35117'))

    def test_oracle_job_url(self):
        self.assertEqual(oracle_job_url('https://h', 'CX_1001', '22280'),
                         'https://h/hcmUI/CandidateExperience/en/sites/CX_1001/job/22280')

    def _oracle_api(self, rows, details):
        calls = []

        def get_json(url):
            calls.append(url)
            if 'recruitingCEJobRequisitions?' in url:
                off = int(re.search(r'offset=(\d+)', url)[1])
                return {'items': [{'TotalJobsCount': len(rows), 'requisitionList': rows[off:off + 25]}]}
            jid = re.search(r'Id=%22(\d+)%22', url)[1]
            return {'items': [details[jid]] if jid in details else []}
        return get_json, calls

    def test_oracle_collect_pagination_details_deadline(self):
        rows = [{'Id': str(i), 'Title': 'Finance Analyst', 'PrimaryLocation': 'Dakar, Senegal'} for i in range(30)]
        rows += [{'Id': '900', 'Title': 'Civil Engineer', 'PrimaryLocation': 'Sarajevo, Bosnia and Herzegovina'},
                 {'Id': '901', 'Title': 'Infrastructure Field Engineer (Consultant)', 'PrimaryLocation': 'Mykolaiv, Ukraine'},
                 {'Id': '902', 'Title': 'Construction Engineer', 'PrimaryLocation': 'Juba, South Sudan'}]
        details = {'900': {'ExternalPostedEndDate': '2099-11-20T22:59:00+00:00', 'ExternalDescriptionStr': '<p>Build</p>'},
                   '901': {'ExternalPostedEndDate': '2099-11-12', 'requisitionFlexFields': [{'Prompt': 'Grade', 'Value': 'IICA-2'}]},
                   '902': {'ExternalPostedEndDate': '2001-01-01'}}
        get_json, calls = self._oracle_api(rows, details)
        jobs, info = oracle_collect('UNDP', 'https://h', 'CX_1', get_json, sleep=0)
        self.assertEqual(info['parsed'], 33)
        self.assertEqual(sum('recruitingCEJobRequisitions?' in c for c in calls), 2)
        self.assertEqual(sorted(j['oracle']['id'] for j in jobs), ['900', '901'])
        self.assertEqual(info['expired'], 1)
        j900 = next(j for j in jobs if j['oracle']['id'] == '900')
        self.assertEqual(j900['deadline'], '2099-11-20')
        self.assertTrue(j900['url'].endswith('/sites/CX_1/job/900'))
        self.assertIn('Finance Analyst', info['rejected'])
        self.assertIn('IICA-2', next(j for j in jobs if j['oracle']['id'] == '901')['text'])

    def test_oracle_empty_raises(self):
        get_json, _ = self._oracle_api([], {})
        with self.assertRaises(ValueError):
            oracle_collect('IOM', 'https://h', 'CX_1001', get_json, sleep=0)

    def test_oracle_version_fallback(self):
        seen = []

        def get_json(url):
            seen.append(url)
            if '/latest/' in url:
                raise urllib.error.HTTPError(url, 404, 'nf', None, None)
            if 'Details' in url:
                return {'items': []}
            return {'items': [{'TotalJobsCount': 1, 'requisitionList': [{'Id': '5', 'Title': 'Civil Engineer'}]}]}
        jobs, _ = oracle_collect('IOM', 'https://h', 'CX_1001', get_json, sleep=0)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(any('11.13.18.05' in u for u in seen))

    def test_oracle_run_uses_browser_fallback(self):
        def get(url, accept='*/*'):
            if url.endswith('robots.txt'):
                raise urllib.error.HTTPError(url, 404, 'nf', None, None)
            raise urllib.error.HTTPError(url, 403, 'Forbidden', None, None)
        fb = lambda n, o, s: ([dict(title='Civil Engineer', url='https://h/job/1', source=n)],
                              dict(format='Oracle JSON', parsed=1, expired=0, detailed=0, rejected=[]))
        name, jobs, st = oracle_run('UNDP', 'https://h', 'CX_1', get, fb)
        self.assertTrue(st['ok'])
        self.assertIn('browser', st['message'])

    def test_oracle_run_reports_both_failures(self):
        def get(url, accept='*/*'):
            raise urllib.error.HTTPError(url, 404 if 'robots' in url else 500, 'x', None, None)

        def fb(*a):
            raise ImportError
        _, jobs, st = oracle_run('UNDP', 'https://h', 'CX_1', get, fb)
        self.assertFalse(st['ok'])
        self.assertIn('JSON API', st['message'])
        self.assertIn('Playwright not installed', st['message'])

    # --- robots ---
    def test_robots_4xx_allows(self):
        def get(url, accept='*/*'):
            raise urllib.error.HTTPError(url, 403, 'x', None, None)
        permitted('https://a.org/x', get)

    def test_robots_5xx_blocks(self):
        def get(url, accept='*/*'):
            raise urllib.error.HTTPError(url, 503, 'x', None, None)
        with self.assertRaises(PermissionError):
            permitted('https://b.org/x', get)

    def test_robots_disallow(self):
        get = lambda url, accept='*/*': (b'User-agent: *\nDisallow: /', 'text/plain', url)
        with self.assertRaises(PermissionError):
            permitted('https://c.org/x', get)

    # --- feeds ---
    def test_rss(self):
        raw = b'<rss><item><title>Construction Engineer</title><link>https://x/1</link></item></rss>'
        self.assertEqual(len(parse_feed(raw, 'text/xml', 'https://x', 'UNOPS')[0]), 1)

    def test_rss_bare_ampersand_and_controls(self):
        raw = b'<rss><item><title>Civil Engineer & Site\x01 Lead</title><link>https://x/1?a=1&b=2</link></item></rss>'
        jobs, info = parse_feed(raw, 'text/xml', 'https://x', 'UNOPS')
        self.assertEqual((len(jobs), info['format']), (1, 'XML (limited repair)'))

    def test_atom(self):
        raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Site Engineer</title><link href="https://x/2"/></entry></feed>'
        self.assertEqual(len(parse_feed(raw, 'text/xml', 'https://x', 'UNOPS')[0]), 1)

    def test_malformed_xml_raises(self):
        with self.assertRaises(ET.ParseError):
            parse_feed(b'<rss><item>', 'text/xml', 'https://x', 'UNOPS')

    def test_html_where_feed_expected(self):
        with self.assertRaises(ValueError):
            parse_feed(b'<!doctype html><html></html>', 'text/html', 'https://x', 'UN Careers')

    def test_html_base_href_and_aria_label(self):
        raw = (b'<html><base href="/root/"><a href="jobs/123" aria-label="Civil Engineer"></a>'
               b'<a href="/about">Construction Engineer</a></html>')
        jobs, info = parse_feed(raw, 'text/html', 'https://imp.org/search', 'Impactpool', r'/jobs/\d+')
        self.assertEqual(jobs[0]['url'], 'https://imp.org/root/jobs/123')
        self.assertEqual(info['parsed'], 1)

    def test_access_challenge(self):
        with self.assertRaises(PermissionError):
            parse_feed(b'<html>Verify you are human</html>', 'text/html', 'https://x', 'Impactpool', r'/jobs/\d+')

    def test_unsafe_link_dropped(self):
        raw = b'<rss><item><title>Civil Engineer</title><link>javascript:alert(1)</link></item></rss>'
        self.assertEqual(parse_feed(raw, 'text/xml', 'https://x', 'UNOPS')[0], [])

    def test_expired_feed_item(self):
        raw = (b'<rss><item><title>Civil Engineer</title><link>https://x/1</link>'
               b'<description>Deadline: 2001-01-01</description></item></rss>')
        jobs, info = parse_feed(raw, 'text/xml', 'https://x', 'UNOPS')
        self.assertEqual((jobs, info['expired']), ([], 1))

    def test_labelled_deadline_formats(self):
        self.assertEqual(labelled_deadline('Closing date: 12 November 2099'), '2099-11-12')
        self.assertEqual(labelled_deadline('Apply before November 12, 2099'), '2099-11-12')
        self.assertIsNone(labelled_deadline('posted 12 November 2099'))

    def test_canonical(self):
        self.assertEqual(canonical('https://X.org/a?utm_source=z&id=1#t'), 'https://x.org/a?id=1')

    # --- relevance ---
    def test_relevance_un_secretariat_style(self):
        self.assertGreater(relevance('ENGINEER (CIVIL), P3')[0], 0)
        self.assertGreater(relevance('Engineer, P4')[0], 0)

    def test_relevance_exclusions(self):
        for t in ('Software Engineer', 'Cloud Infrastructure Engineer', 'Construction Intern', 'Driver',
                  'Digital Public Infrastructure Specialist', 'Network Engineer'):
            self.assertEqual(relevance(t, 'construction')[0], 0, t)

    def test_relevance_international_is_not_intern(self):
        self.assertGreater(relevance('International Construction Engineer')[0], 0)

    def test_procurement_needs_works_context(self):
        self.assertEqual(relevance('Procurement Officer', 'vaccines')[0], 0)
        self.assertGreater(relevance('Procurement Officer', 'civil works')[0], 0)

    # --- geography ---
    def test_country_detection(self):
        self.assertEqual(find_country('Port Moresby, Papua New Guinea'), 'Papua New Guinea')
        self.assertEqual(find_country('Niamey, Niger'), 'Niger')
        self.assertEqual(find_country('Abuja, Nigeria'), 'Nigeria')
        self.assertEqual(find_country('Abidjan, Côte d’Ivoire'), 'Cote d Ivoire')
        self.assertEqual(find_country('Sarajevo'), 'Bosnia and Herzegovina')
        self.assertIsNone(find_country('Somewhere'))

    # --- eligibility gates ---
    def test_tier_only_ineligible(self):
        e = eligibility(self.job('Civil Engineer [Open to Tier 0, 1 & 2 applicants]', location='Sarajevo, Bosnia and Herzegovina'))
        self.assertEqual(e['status'], 'INELIGIBLE')

    def test_tier3_and_external_allowed(self):
        for t in ('Civil Engineer [Open to Tier 1, 2 & 3 applicants]', 'Civil Engineer [Open to internal and external applicants]'):
            self.assertNotEqual(eligibility(self.job(t, location='Sarajevo, Bosnia and Herzegovina'))['status'], 'INELIGIBLE', t)

    def test_internal_only(self):
        self.assertEqual(eligibility(self.job('Construction Engineer', 'For internal candidates only.'))['status'], 'INELIGIBLE')

    def test_nationals_only_other_country(self):
        e = eligibility(self.job('National Officer - Engineer (Solomon Islands Nationals Only)', location='Honiara, Solomon Islands'))
        self.assertEqual(e['status'], 'INELIGIBLE')

    def test_nationals_only_own_country(self):
        e = eligibility(self.job('Construction Engineer, Sarajevo, Bosnia and Herzegovina (Nationals only)'))
        self.assertNotEqual(e['status'], 'INELIGIBLE')
        self.assertTrue(any('you qualify' in r[1] for r in e['reasons']))

    def test_eu_only(self):
        e = eligibility(self.job('Civil Engineer', 'Open to applicants who are nationals of the EU, EEA and Switzerland.' + self.LONG))
        self.assertEqual(e['status'], 'INELIGIBLE')

    def test_local_post_abroad(self):
        for t, loc in (('Engineering Associate (NPSA-8)', 'Mykolaiv, Ukraine'), ('Civil Engineer NO-B', 'Nairobi, Kenya'),
                       ('Site Engineer (G5)', 'Faya, Chad')):
            self.assertEqual(eligibility(self.job(t, location=loc))['status'], 'INELIGIBLE', t)

    def test_local_post_home(self):
        e = eligibility(self.job('Civil Engineer NO-C', location='Sarajevo, Bosnia and Herzegovina'))
        self.assertNotEqual(e['status'], 'INELIGIBLE')

    def test_international_consultant_abroad_allowed(self):
        e = eligibility(self.job('Infrastructure Field Engineer (Consultant)', self.LONG, location='Mykolaiv, Ukraine'))
        self.assertNotEqual(e['status'], 'INELIGIBLE')

    def test_local_post_unknown_country_is_check(self):
        e = eligibility(self.job('Civil Engineer NPSA-9'))
        self.assertEqual(e['status'], 'CHECK')

    def test_experience_gate(self):
        e = eligibility(self.job('Civil Engineer', 'A minimum of 30 years of experience is required.' + self.LONG,
                                 location='Sarajevo, Bosnia and Herzegovina'))
        self.assertEqual(e['status'], 'INELIGIBLE')

    def test_deadline_passed(self):
        e = eligibility(self.job('Civil Engineer', self.LONG, location='Sarajevo, Bosnia and Herzegovina', deadline='2001-01-01'))
        self.assertEqual((e['status'], e['score']), ('INELIGIBLE', 0))

    # --- eligibility scoring ---
    def test_full_eligible_high_score(self):
        e = eligibility(self.job('Senior Construction Engineer', self.LONG, location='Sarajevo, Bosnia and Herzegovina'))
        self.assertEqual(e['status'], 'ELIGIBLE')
        self.assertGreaterEqual(e['score'], 85)

    def test_required_language_penalised(self):
        base = eligibility(self.job('Civil Engineer', self.LONG, location='Amman, Jordan'))
        arab = eligibility(self.job('Civil Engineer', self.LONG + ' Fluency in Arabic is required.', location='Amman, Jordan'))
        self.assertEqual(arab['status'], 'CHECK')
        self.assertEqual(base['score'] - arab['score'], 30)

    def test_desirable_language_not_penalised(self):
        e1 = eligibility(self.job('Civil Engineer', self.LONG, location='Amman, Jordan'))
        e2 = eligibility(self.job('Civil Engineer', self.LONG + ' Knowledge of Arabic is desirable.', location='Amman, Jordan'))
        self.assertEqual(e1['score'], e2['score'])

    def test_civil_only_degree_flagged(self):
        txt = self.LONG.replace('architecture, civil engineering or related field', 'civil engineering')
        e = eligibility(self.job('Civil Engineer', txt, location='Sarajevo, Bosnia and Herzegovina'))
        self.assertEqual(e['status'], 'CHECK')

    def test_no_description_is_check(self):
        e = eligibility(self.job('Construction Engineer', location='Sarajevo, Bosnia and Herzegovina'))
        self.assertEqual(e['status'], 'CHECK')

    def test_unknown_deadline_is_check(self):
        e = eligibility(self.job('Construction Engineer', self.LONG, location='Sarajevo, Bosnia and Herzegovina', deadline=None))
        self.assertEqual(e['status'], 'CHECK')

    def test_location_ranking(self):
        s = lambda loc: eligibility(self.job('Civil Engineer', self.LONG, location=loc))['score']
        self.assertGreater(s('Sarajevo, Bosnia and Herzegovina'), s('Belgrade, Serbia'))
        self.assertGreater(s('Belgrade, Serbia'), s('Juba, South Sudan'))

    def test_overqualified_lower(self):
        s = lambda t: eligibility(self.job(t, self.LONG, location='Sarajevo, Bosnia and Herzegovina'))['score']
        self.assertGreater(s('Construction Specialist'), s('Engineering Assistant'))

    def test_score_bounds(self):
        for t in ('Civil Engineer', 'Engineering Assistant', 'Senior Construction Manager'):
            sc = eligibility(self.job(t, self.LONG + ' Fluency in Arabic is required.'))['score']
            self.assertTrue(0 <= sc <= 100)

    def test_unicef_no_grade_abroad(self):
        e = eligibility(self.job('Construction Officer, NO-2, Kabul, Afghanistan, #12345'))
        self.assertEqual(e['status'], 'INELIGIBLE')

    def test_unicef_no_grade_home(self):
        e = eligibility(self.job('Construction Officer, NO-3, Sarajevo, Bosnia and Herzegovina, #12345'))
        self.assertNotEqual(e['status'], 'INELIGIBLE')

    def test_grade_in_text_detected(self):
        txt = self.LONG + ' Position Level: NPSA-9. Contract Type: National PSA- Regular.'
        e = eligibility(self.job('Civil Engineer', txt, location='Antananarivo, Madagascar'))
        self.assertEqual(e['status'], 'INELIGIBLE')

    def test_corporate_history_not_requirement(self):
        txt = 'With over 75 years of experience, IOM is the leading agency. ' + self.LONG
        e = eligibility(self.job('Civil Engineer', txt, location='Sarajevo, Bosnia and Herzegovina'))
        self.assertNotEqual(e['status'], 'INELIGIBLE')

    def test_country_word_not_language(self):
        txt = self.LONG + ' Close coordination with Ukrainian authorities is required.'
        e1 = eligibility(self.job('Civil Engineer', self.LONG, location='Kyiv, Ukraine'))
        e2 = eligibility(self.job('Civil Engineer', txt, location='Kyiv, Ukraine'))
        self.assertEqual(e1['score'], e2['score'])

    def test_duty_station_from_text(self):
        txt = self.LONG + ' Duty Station: Belgrade, Serbia. The project also covers Montenegro.'
        self.assertEqual(eligibility(self.job('Civil Engineer', txt))['country'], 'Serbia')

    def test_earliest_country_wins(self):
        self.assertEqual(find_country('Amman, Jordan - Syria response'), 'Jordan')

    def test_french_tiers(self):
        e = eligibility(self.job('Ingenieur civil [Ouvert aux candidats de Niveaux 1 & 2]', location='Dakar, Senegal'))
        self.assertEqual(e['status'], 'INELIGIBLE')

    def test_robots_disallow_stops_oracle_without_browser(self):
        get = lambda url, accept='*/*': (b'User-agent: *\nDisallow: /hcmRestApi/', 'text/plain', url)
        called = []
        _, _, st = oracle_run('UNDP', 'https://r.org', 'CX_1', get, lambda *a: called.append(1))
        self.assertFalse(st['ok']); self.assertEqual(called, [])

    def test_oracle_flex_grade_used(self):
        rows = [{'Id': '7', 'Title': 'Civil Engineer', 'PrimaryLocation': 'Honiara, Solomon Islands'}]
        det = {'7': {'ExternalPostedEndDate': '2099-01-01', 'requisitionFlexFields': [{'Prompt': 'Grade', 'Value': 'NO-A'}]}}
        get_json, _ = self._oracle_api(rows, det)
        jobs, _ = oracle_collect('IOM', 'https://h', 'CX_1001', get_json, sleep=0)
        self.assertIn('NO-A', jobs[0]['grade'])
        self.assertEqual(eligibility(jobs[0])['status'], 'INELIGIBLE')

    def test_page_payload_has_no_text(self):
        j = dict(self.job('Civil Engineer', 'SECRET-LONG-TEXT'), status='CHECK', score=1, reasons=[], new=False, retained=False)
        self.assertNotIn('SECRET-LONG-TEXT', build_page(dict(jobs=[j], sources={}, updated='t')))

    # --- merge / retention ---
    def test_merge_order_and_new(self):
        a = self.job('Senior Construction Engineer', self.LONG, location='Sarajevo, Bosnia and Herzegovina'); a['url'] = 'https://x/a'
        b = self.job('Civil Engineer NO-B', location='Nairobi, Kenya'); b['url'] = 'https://x/b'
        c = self.job('Construction Engineer', location='Sarajevo, Bosnia and Herzegovina', deadline=None); c['url'] = 'https://x/c'
        d = merge({'jobs': [dict(c, last_seen=NOW().isoformat())]}, [('UNDP', [b, c, a], {'ok': True})])
        self.assertEqual([j['status'] for j in d['jobs']], ['ELIGIBLE', 'CHECK', 'INELIGIBLE'])
        self.assertEqual([j['new'] for j in d['jobs']], [True, False, True])

    def test_retention_rules(self):
        fresh = NOW().isoformat()
        old4 = (NOW() - dt.timedelta(days=4)).isoformat()
        prev = {'jobs': [
            dict(self.job('Civil Engineer'), url='https://x/open', source='UNOPS', last_seen=fresh),
            dict(self.job('Civil Engineer'), url='https://x/closed', source='UNOPS', last_seen=fresh),
            dict(self.job('Civil Engineer', deadline=None), url='https://x/old', source='UNOPS', last_seen=old4),
            dict(self.job('Civil Engineer', deadline='2001-01-01'), url='https://x/past', source='UNOPS', last_seen=fresh),
            dict(self.job('Civil Engineer'), url='https://x/stale', source='UNOPS',
                 last_seen=(NOW() - dt.timedelta(days=8)).isoformat())]}
        verify = lambda j: 'closed' if j['url'].endswith(('closed', 'past')) else 'unverified'
        d = merge(prev, [('UNOPS', [], {'ok': False, 'message': 'x'})], verify)
        self.assertEqual([j['url'] for j in d['jobs']], ['https://x/open'])
        self.assertTrue(d['jobs'][0]['retained'])

    def test_still_open(self):
        def g404(url, accept='*/*'):
            raise urllib.error.HTTPError(url, 404, 'nf', None, None)
        self.assertEqual(still_open(dict(url='https://x/1'), g404), 'closed')
        gtxt = lambda url, accept='*/*': (b'<p>This job is no longer available</p>', 'text/html', url)
        self.assertEqual(still_open(dict(url='https://x/1'), gtxt), 'closed')
        gok = lambda url, accept='*/*': (b'<p>Apply now</p>', 'text/html', url)
        self.assertEqual(still_open(dict(url='https://x/1'), gok), 'unverified')
        gora = lambda url, accept='*/*': (b'{"items":[{"Id":"1"}]}', 'application/json', url)
        self.assertEqual(still_open(dict(url='https://x/1', oracle=dict(origin='https://h', site='CX_1', id='1')), gora), 'open')

    # --- page ---
    def test_page_escapes_script(self):
        j = dict(self.job('Civil </script><script>alert(1)</script>'), url='https://x/1', status='CHECK', score=50,
                 reasons=[['?', 'x']], new=True, retained=False)
        p = build_page(dict(jobs=[j], sources={}, updated='t'))
        self.assertNotIn('</script><script>alert', p)
        self.assertIn('Civil \\u003c/script', p)


if __name__ == '__main__':
    if sys.argv[1:] == ['test']:
        unittest.main(argv=[sys.argv[0]], verbosity=1)
    else:
        run()
