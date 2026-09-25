#!/usr/bin/env python3
"""Book Times data build: one JSON file per minute of the day (docs/m/HHMM.json, 1440 files) for the polling URL.

The selection is a port of tiny-paper's literature clock (plugins/litclock/converter/src/text.ts, posters()):
per 12-hour minute the best Project Gutenberg public-domain row, else the best sfw row of the quote collections.
TRMNL shows a 24-hour day, so each 12-hour pick is checked against the half of the day it lands in: a row that
names its half (the collections' time24; midnight / noon / midday in the time words) and names the other one gives
way to the best eligible row of that minute that names the right half; if there is none, the pick serves both halves.

Usage:
  python3 tools/build_data.py                        # data/passages.jsonl -> docs/m/*.json
  python3 tools/build_data.py --import PASSAGES.json # refresh data/passages.jsonl from tiny-paper's passages.json

Stdlib only.
SPDX-License-Identifier: MIT
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROWS_FILE = ROOT / 'data' / 'passages.jsonl'
OUT_DIR = ROOT / 'docs' / 'm'

MINUTES = 720

# --- text.ts port ---------------------------------------------------------------------------------------------

WORD = re.compile(r"\d+(?:[.:]\d+)*[A-Za-z]*|[A-Za-z]+(?:['-][A-Za-z]+)*")
ABBREV = {'MR', 'MRS', 'DR', 'ST', 'MESSRS', 'MME', 'MLLE', 'MM', 'JR', 'SR', 'REV', 'COL', 'CAPT', 'GEN', 'LT', 'SGT',
          'PROF', 'HON', 'VOL'}
OPENERS = {'(', '‘', '“'}
SENTENCE_END = {'.', '!', '?'}
PUNCT = set(".,;:!?'\"()&-/")


def minute_of(time):
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', time)
    if not m:
        raise ValueError(f'bad time {time}')
    return (int(m.group(1)) % 12) * 60 + int(m.group(2))


def time_of(minute):
    h = minute // 60
    return f'{12 if h == 0 else h}:{minute % 60:02d}'


def fold(s):
    """ASCII folding as text.ts fold(), without the upper-casing (the plugin keeps the book's case)."""
    s = unicodedata.normalize('NFD', s)
    s = re.sub('[̀-ͯ]', '', s)
    return s.replace('ø', 'o').replace('Ø', 'O')


def units(text, emph_words=()):
    """Splits text into units {pre, word, post, emph} exactly as text.ts units(); words keep their case.

    `|` (a collection's phrase marker, never a WORD) is dropped first; tiny-paper never renders such a row.
    """
    text = text.replace('|', '')
    out = []
    pending = []
    emph = set(emph_words)
    wi = 0
    at = 0

    def add_punct(ch, before, after):
        nonlocal pending
        sym = ch
        opening = (before == '' or re.match(r'[\s(‘“"\']', before) is not None) and after != '' and not after.isspace()
        if ch == '"':
            sym = '“' if opening else '”'
        elif ch == "'":
            sym = '‘' if opening else '’'
        if sym in OPENERS:
            pending.append(sym)
            return
        if not out or pending:
            pending.append(sym)
        else:
            out[-1]['post'].append(sym)

    def gap(a, b):
        nonlocal pending
        for i in range(a, b):
            ch = text[i]
            if ch.isspace():
                continue
            if ch not in PUNCT:
                raise ValueError(f'unexpected character {ch!r} in {text!r}')
            if ch in '&/':
                out.append({'pre': pending, 'word': ch, 'post': [], 'emph': False})
                pending = []
                continue
            add_punct(ch, text[i - 1] if i > 0 else '', text[i + 1] if i + 1 < len(text) else '')

    def capital_next(frm):
        return re.match(r'\s*[A-Z]', text[frm:]) is not None

    for m in WORD.finditer(text):
        if m.start() < at:
            wi += 1  # the M of an A.M. already taken
            continue
        gap(at, m.start())
        word = fold(m.group(0)).replace("'", '’')
        at = m.end()
        e = wi in emph
        post = []
        meridian = re.match(r'\.\s?[mM]\.', text[at:]) if word.upper() in ('A', 'P') else None
        if meridian:
            at += len(meridian.group(0))
            e = e or (wi + 1) in emph
            word += '.' + meridian.group(0)[-2]
            if capital_next(at):
                post.append('.')
            else:
                word += '.'
        elif word.upper() in ABBREV and at < len(text) and text[at] == '.':
            word += '.'
            at += 1
        elif (re.fullmatch(r'\d+', word) and not e and out and any(p in SENTENCE_END for p in out[-1]['post'])
              and capital_next(at)):
            wi += 1
            continue
        out.append({'pre': pending, 'word': word, 'post': post, 'emph': e})
        pending = []
        wi += 1
    gap(at, len(text))
    if not out:
        raise ValueError(f'no words in {text!r}')
    return out


def author_name(author, source):
    m = re.fullmatch(r'([^,\s]+), ([^,]+)', author.strip()) if source == 'utrost' else None
    return f'{m.group(2)} {m.group(1)}' if m else author


def short_title(t):
    s = re.sub(r'\s*\([^)]*\)', '', t)
    s = re.sub(r'\s+-\s+.*$', '', s)
    s = re.sub(r'[:;].*$', '', s).strip()
    if len(s) > 40 and ', ' in s:
        s = s[:s.index(', ')]
    return re.sub(r'[.,]+$', '', s).strip()


# --- selection ------------------------------------------------------------------------------------------------

def is_gutenberg_pd(r):
    return r['source'] == 'gutenberg' and r['rights'] == 'public_domain'


def eligible(r):
    """A row tiny-paper can pick: Gutenberg public domain, or any sfw row."""
    return is_gutenberg_pd(r) or bool(r['sfw'])


def half_of(r):
    """0 (AM, 00:00-11:59), 1 (PM) or None: the half of the day the row names."""
    t24 = r.get('time24')
    if t24:
        return 0 if int(t24.split(':')[0]) < 12 else 1
    words = ' '.join(r['time_words']).lower()
    if 'midnight' in words:
        return 0
    if re.search(r'\b(noon|midday|mid-day)\b', words):
        return 1
    return None


def pick12(cands):
    """tiny-paper posters(): the best-ranked Gutenberg public-domain row, else the best-ranked sfw row."""
    best = [r for r in cands if is_gutenberg_pd(r)]
    if best:
        return min(best, key=lambda r: r['rank'])
    other = [r for r in cands if r['sfw']]
    return min(other, key=lambda r: r['rank']) if other else None


def pick24(cands, half):
    """The 12-hour pick, or the best eligible row naming `half` when the pick names the other half."""
    r = pick12(cands)
    if r is None or half_of(r) in (None, half):
        return r, False
    match = sorted((c for c in cands if eligible(c) and half_of(c) == half),
                   key=lambda c: (0 if is_gutenberg_pd(c) else 1, c['rank']))
    return (match[0], True) if match else (r, False)


def parts(us):
    """Runs of [text, emph] with the spacing inside the text: time words with their opening marks, the rest as context."""
    runs = []

    def add(t, e):
        if not t:
            return
        if runs and runs[-1][1] == e:
            runs[-1][0] += t
        else:
            runs.append([t, e])

    def marks(ms, before):
        s = ''
        for p in ms:
            s += (' –' if before is False else '– ') if p == '-' else p
        return s

    for i, u in enumerate(us):
        if i:
            add(' ', 0)
        # an opening mark takes its word's size (a quote opening on a time word is as large as the word)
        add(marks(u['pre'], True), 1 if u['emph'] else 0)
        add(u['word'], 1 if u['emph'] else 0)
        add(marks(u['post'], False), 0)
    # a space between two time words stays in the time run ("one o'clock" is one run)
    merged = []
    for j, (t, e) in enumerate(runs):
        if (e == 0 and t == ' ' and 0 < j < len(runs) - 1 and runs[j - 1][1] == 1 and runs[j + 1][1] == 1):
            merged[-1][0] += ' '
            continue
        if merged and merged[-1][1] == e:
            merged[-1][0] += t
        else:
            merged.append([t, e])
    return merged


def poster(r, minute24, swapped):
    us = units(r['text'], r['words'])
    return {
        'time': f'{minute24 // 60:02d}:{minute24 % 60:02d}',
        'parts': parts(us),
        'title': fold(short_title(r['title'])),
        'author': fold(author_name(r['author'], r['source'])),
        'mode': r['mode'],
        'source': r['source'],
        'rights': r['rights'],
        'license': r['dataset_license'],
        'half_swap': swapped,
    }


def load_rows(path=ROWS_FILE):
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip().rstrip(',')
            if line.startswith('{'):
                rows.append(json.loads(line))
    return rows


def by_minute(rows):
    out = {}
    for r in rows:
        out.setdefault(minute_of(r['time']), []).append(r)
    return out


def build(rows):
    """{minute24: poster} for all 1440 minutes."""
    per = by_minute(rows)
    result = {}
    for m24 in range(1440):
        r, swapped = pick24(per.get(m24 % MINUTES, []), 0 if m24 < MINUTES else 1)
        if r is None:
            raise SystemExit(f'no passage for {m24 // 60:02d}:{m24 % 60:02d}')
        result[m24] = poster(r, m24, swapped)
    return result


def import_rows(src):
    """Keeps the rows the selection can reach: every Gutenberg public-domain row, and the sfw collection rows of
    the minutes Gutenberg leaves open or whose Gutenberg row names a half of the day. nsfw rows are left out."""
    rows = load_rows(src)
    per = by_minute(rows)
    keep = []
    for m in range(MINUTES):
        cands = per.get(m, [])
        gut = [r for r in cands if is_gutenberg_pd(r)]
        keep += gut
        if not gut or any(half_of(r) is not None for r in gut):
            keep += [r for r in cands if not is_gutenberg_pd(r) and r['sfw']]
    keep.sort(key=lambda r: (minute_of(r['time']), r['rank']))
    with open(ROWS_FILE, 'w', encoding='utf-8') as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f'{len(keep)} of {len(rows)} rows -> {ROWS_FILE.relative_to(ROOT)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--import', dest='src', help="tiny-paper's plugins/litclock/data/passages.json")
    args = ap.parse_args()
    if args.src:
        import_rows(args.src)
    result = build(load_rows())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob('*.json'):
        old.unlink()
    for m24, p in result.items():
        (OUT_DIR / f'{m24 // 60:02d}{m24 % 60:02d}.json').write_text(
            json.dumps(p, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    swaps = [p['time'] for p in result.values() if p['half_swap']]
    sources = {}
    for p in result.values():
        sources[p['source']] = sources.get(p['source'], 0) + 1
    print(f'1440 minutes -> {OUT_DIR.relative_to(ROOT)}; by source {sources}; half swaps {len(swaps)}: {" ".join(swaps)}')


if __name__ == '__main__':
    sys.exit(main())
