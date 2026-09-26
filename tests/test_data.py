"""Data build checks: the selection matches tiny-paper's, all 1440 minutes resolve, no nsfw rows, docs/m is current.

Run: python3 -m unittest discover -s tests
SPDX-License-Identifier: MIT
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))

import build_data as bd  # noqa: E402

ROWS = bd.load_rows()
PER = bd.by_minute(ROWS)
BUILT = bd.build(ROWS)
FIXTURE = json.loads((ROOT / 'tests' / 'fixtures' / 'tinypaper_sample.json').read_text(encoding='utf-8'))


def hhmm(m24):
    return f'{m24 // 60:02d}{m24 % 60:02d}'


class TinyPaperSelection(unittest.TestCase):
    """tests/fixtures/tinypaper_sample.json comes from tiny-paper's own posters() (tools/tinypaper_reference.mjs)."""

    def test_covers_all_minutes(self):
        self.assertEqual(FIXTURE['covered'], 720)
        self.assertGreater(len(FIXTURE['minutes']), 100)

    def test_same_passage_and_time_words(self):
        for ref in FIXTURE['minutes']:
            m = ref['minute']
            with self.subTest(time=ref['time']):
                row = bd.pick12(PER[m])
                self.assertEqual(row['source'], ref['source'])
                p = bd.poster(row, m, False)
                self.assertEqual(p['title'].upper(), ref['title'])
                self.assertEqual(p['author'].upper(), ref['author'])
                mine = [[''.join(u['pre']), u['word'].upper(), ''.join(u['post']), 1 if u['emph'] else 0]
                        for u in bd.units(row['text'], row['words'])]
                self.assertEqual(mine, ref['units'])

    def test_pick12_is_the_best_ranked(self):
        """tiny-paper's 12-hour pick is the best-ranked eligible row; the 24-hour day starts from the same table."""
        for ref in FIXTURE['minutes']:
            row = bd.pick12(PER[ref['minute']])
            self.assertEqual(row['rank'], min(r['rank'] for r in PER[ref['minute']] if bd.eligible(r)), ref['time'])


class Minutes(unittest.TestCase):
    def test_every_minute_resolves(self):
        self.assertEqual(sorted(BUILT), list(range(1440)))
        for m24, p in BUILT.items():
            with self.subTest(time=p['time']):
                self.assertEqual(p['time'].replace(':', ''), hhmm(m24))
                self.assertTrue(any(e for _, e in p['parts']), 'no time words')
                self.assertTrue(p['title'] and p['author'])
                self.assertIn(p['license'], {'public-domain', 'CC-BY-NC-SA-2.5', 'AGPL-3.0', 'unverified'})

    def test_no_nsfw_rows(self):
        self.assertTrue(all(r['sfw'] for r in ROWS), 'nsfw row in data/passages.jsonl')
        for m24 in range(1440):
            row, _ = bd.pick24(PER[m24 % 720], m24 // 720)
            self.assertTrue(row['sfw'])

    def test_the_right_half_first(self):
        """A minute shows a row naming its half when one exists; one naming the other half only when nothing else
        is left (half_swap)."""
        for m24, p in BUILT.items():
            half, ok = m24 // 720, [r for r in PER[m24 % 720] if bd.eligible(r)]
            row, swapped = bd.pick24(PER[m24 % 720], half)
            with self.subTest(time=p['time']):
                if any(bd.half_of(r) == half for r in ok):
                    self.assertEqual(bd.half_of(row), half)
                self.assertEqual(swapped, all(bd.half_of(r) not in (None, half) for r in ok))

    def test_time_phrase_first(self):
        """A minute shows a time phrase whenever one names its half or no half; hidden time only where the time
        phrases all name the other half (a wrong half would mislead more than hidden time)."""
        for m24, p in BUILT.items():
            half = m24 // 720
            if any(r['mode'] == 'classic' and bd.tier(r, half) < 2 for r in PER[m24 % 720] if bd.eligible(r)):
                self.assertEqual(p['mode'], 'classic', p['time'])

    def test_halves_differ_when_they_can(self):
        same = [m for m in range(720) if BUILT[m]['parts'] == BUILT[m + 720]['parts']]
        for m in same:  # only where no other row of the afternoon's tier exists
            am, _ = bd.pick24(PER[m], 0)
            pm, _ = bd.pick24(PER[m], 1)
            self.assertFalse(any(r['text'] != am['text'] and bd.tier(r, 1) == bd.tier(pm, 1) for r in PER[m] if bd.eligible(r)))

    def test_published_files_are_current(self):
        files = sorted((ROOT / 'docs' / 'm').glob('*.json'))
        self.assertEqual(len(files), 1440)
        for m24, p in BUILT.items():
            got = json.loads((ROOT / 'docs' / 'm' / f'{hhmm(m24)}.json').read_text(encoding='utf-8'))
            self.assertEqual(got, p, f'docs/m/{hhmm(m24)}.json is stale: run python3 tools/build_data.py')


class Units(unittest.TestCase):
    def test_author_and_brackets(self):
        self.assertEqual(bd.author_name('graf Leo Tolstoy', 'utrost'), 'Leo Tolstoy')
        self.assertEqual(bd.author_name('Baker, Nicholson', 'utrost'), 'Nicholson Baker')
        self.assertEqual([u['word'] for u in bd.units("remained [until ten o'clock].")], ['remained', 'until', 'ten', 'o’clock'])
        self.assertFalse(bd.drawable_row('for $5'))
        # a spaced-off stop after P.M (some scans)
        us = bd.units('in that bank. 5:22 P.M . Then', [4])
        self.assertIn('P.M.', [u['word'] + ''.join(u['post']) for u in us])

    def test_meridian_page_numbers_and_quotes(self):
        us = bd.units('He left at 5 p.m. Then "she" came. 26 Good night.', [3])
        words = [u['word'] for u in us]
        self.assertEqual(us[words.index('p.m')]['post'], ['.'])  # a sentence end before a capital
        self.assertNotIn('26', words)
        self.assertEqual(us[words.index('she')]['pre'], ['“'])

    def test_parts_keep_time_phrase_together(self):
        us = bd.units("It was one o'clock, sir.", [2, 3])
        self.assertEqual(bd.parts(us), [['It was ', 0], ['one o’clock', 1], [', sir.', 0]])


if __name__ == '__main__':
    unittest.main()
