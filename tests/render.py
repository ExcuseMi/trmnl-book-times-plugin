#!/usr/bin/env python3
"""Render checks: every layout on the TRMNL OG (1-bit, 2-bit) and TRMNL X (4-bit, landscape and portrait) for a few
long and short passages. Needs trmnlp, google-chrome (or chromium) and ImageMagick (`magick`).

Each case is built with `trmnlp build` (the passage injected through .trmnlp.yml variables), the half and quadrant
views are composed into a real mashup (every slot the same view, so each slot fits itself), the page is measured
in Chrome (the poster box must hold its text, the context at least MIN_PX) and screenshotted, then quantized to the
panel's gray levels.

Usage: python3 tests/render.py [--screens] [case ...]
  --screens   also copy the previews in SCREEN_SET to docs/screens/
Out: tests/out/<case>-<device>-<view>.png
SPDX-License-Identifier: MIT
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / 'plugin'
OUT = ROOT / 'tests' / 'out'
SCREENS = ROOT / 'docs' / 'screens'
CHROME = shutil.which('google-chrome') or shutil.which('chromium') or 'chromium'
MIN_PX = 10  # smallest context size (CSS px) accepted anywhere

# (name, minute file, settings)
CASES = {
    'typical': ('1722', {}),
    'shortest': ('1621', {}),
    'longest': ('2029', {}),
    'long-gutenberg': ('1117', {}),
    'long-title': ('0841', {'hour_format': '12'}),
    'noon': ('1200', {'hour_format': '12'}),
    'bare': ('0703', {'show_time': False, 'show_attribution': False}),
}

# name: (screen classes, width, height, device scale, depth); the framework scales the TRMNL X itself (density-2x)
DEVICES = {
    'og1': ('screen--og_png screen--md screen--density-1x screen--1bit', 800, 480, 1, 1),
    'og2': ('screen--ogv2 screen--md screen--density-1x screen--2bit', 800, 480, 1, 2),
    'x4': ('screen--v2 screen--lg screen--density-2x screen--4bit', 1872, 1404, 1, 4),
    'x4p': ('screen--v2 screen--lg screen--density-2x screen--4bit screen--portrait', 1404, 1872, 1, 4),
}

# previews kept in docs/screens (--screens): case-device-view
SCREEN_SET = [
    'typical-og1-full', 'typical-og2-full', 'typical-x4-full', 'typical-x4p-full',
    'typical-og2-half_horizontal', 'typical-og2-half_vertical', 'typical-og2-quadrant',
    'longest-og1-full', 'longest-og2-quadrant', 'longest-x4p-half_vertical', 'shortest-og1-full',
    'long-gutenberg-og1-half_vertical', 'long-title-og2-quadrant', 'noon-og2-half_horizontal', 'bare-og1-full',
]

VIEWS = {
    'full': None,
    'half_horizontal': ('mashup--1Tx1B', 2),
    'half_vertical': ('mashup--1Lx1R', 2),
    'quadrant': ('mashup--2x2', 4),
}

PROBE = '''<script>
window.addEventListener('load', function () { setTimeout(function () {
  var out = [];
  document.querySelectorAll('.view').forEach(function (v) {
    var box = v.querySelector('.bt-box'), txt = v.querySelector('.bt-text'), foot = v.querySelector('.bt-foot');
    if (!box || !txt) { out.push({missing: true}); return; }
    var r = {
      fs: parseFloat(getComputedStyle(txt).fontSize),
      text_h: txt.scrollHeight, box_h: box.clientHeight, text_w: txt.scrollWidth, box_w: box.clientWidth,
      view_h: v.clientHeight, view_w: v.clientWidth
    };
    if (foot) {
      var fr = foot.getBoundingClientRect(), vr = v.getBoundingClientRect();
      r.foot_inside = fr.bottom <= vr.bottom + 1 && fr.right <= vr.right + 1;
      var au = v.querySelector('.bt-attr .shrink-0'), dg = v.querySelector('.bt-digits');
      r.author_inside = !au || (au.getBoundingClientRect().right <= (dg ? dg.getBoundingClientRect().left : vr.right) + 1);
    }
    out.push(r);
  });
  var d = document.createElement('pre'); d.id = '__probe'; d.textContent = JSON.stringify(out);
  document.body.appendChild(d);
}, 3000); });
</script>'''


def yml_value(v):
    return json.dumps(v)


def build(case, tmp):
    """trmnlp build with the case's passage and settings; returns {view: html}."""
    minute, settings = CASES[case]
    data = json.loads((ROOT / 'docs' / 'm' / f'{minute}.json').read_text(encoding='utf-8'))
    work = tmp / case
    work.mkdir()
    shutil.copytree(PLUGIN / 'src', work / 'src')
    fields = {'show_time': True, 'hour_format': '24', 'show_attribution': True, **settings}
    variables = {'trmnl': {'plugin_settings': {'instance_name': 'Book Times'}}, **data}
    cfg = {'time_zone': 'Europe/Brussels', 'custom_fields': fields, 'variables': variables}
    # JSON is YAML
    (work / '.trmnlp.yml').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
    subprocess.run(['trmnlp', 'build', '-q', '-d', str(work)], check=True)
    return {v: (work / '_build' / f'{v}.html').read_text(encoding='utf-8') for v in VIEWS}


def view_div(html, view):
    marker = f'<div class="view view--{view}">'
    i = html.index(marker)
    depth = 0
    for m in re.finditer(r'<div\b[^>]*>|</div>', html[i:]):
        depth += -1 if m.group(0) == '</div>' else 1
        if depth == 0:
            return i, i + m.end()
    raise ValueError('unbalanced view')


def page(html, view, classes):
    """The view (in a mashup for half/quadrant) on a screen with the device's classes, plus the probe."""
    html = html.replace('<div class="screen">', f'<div class="screen {classes}">', 1)
    if VIEWS[view]:
        mashup, n = VIEWS[view]
        a, b = view_div(html, view)
        html = html[:a] + f'<div class="mashup {mashup}">' + html[a:b] * n + '</div>' + html[b:]
    return html.replace('</body>', PROBE + '</body>')


def chrome(args, url):
    return subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
                           '--virtual-time-budget=8000', *args, url], capture_output=True, text=True, timeout=120)


def check(case, dev, view, probe):
    errors = []
    for i, r in enumerate(probe):
        where = f'{case} {dev} {view} slot {i}'
        if r.get('missing'):
            errors.append(f'{where}: no poster')
            continue
        if r['text_h'] > r['box_h'] + 1:
            errors.append(f'{where}: text {r["text_h"]}px in a {r["box_h"]}px box')
        if r['text_w'] > r['box_w'] + 1:
            errors.append(f'{where}: text {r["text_w"]}px wide in {r["box_w"]}px')
        if r['fs'] < MIN_PX:
            errors.append(f'{where}: context {r["fs"]}px < {MIN_PX}px')
        if 'foot_inside' in r and not r['foot_inside']:
            errors.append(f'{where}: bottom line outside the view')
        if r.get('author_inside') is False:
            errors.append(f'{where}: author cut or under the time')
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--screens', action='store_true')
    ap.add_argument('cases', nargs='*')
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []
    sizes = []
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for case in args.cases or CASES:
            built = build(case, tmp)
            for dev, (classes, w, h, scale, depth) in DEVICES.items():
                for view in VIEWS:
                    f = tmp / f'{case}-{dev}-{view}.html'
                    f.write_text(page(built[view], view, classes), encoding='utf-8')
                    flags = [f'--window-size={w},{h}', f'--force-device-scale-factor={scale}']
                    dom = chrome(flags + ['--dump-dom'], f.as_uri()).stdout
                    m = re.search(r'<pre id="__probe">(.*?)</pre>', dom, re.S)
                    probe = json.loads(m.group(1).replace('&quot;', '"')) if m else [{'missing': True}]
                    errors += check(case, dev, view, probe)
                    sizes.append((case, dev, view, min(r.get('fs', 0) for r in probe)))
                    png = OUT / f'{case}-{dev}-{view}.png'
                    chrome(flags + [f'--screenshot={png}'], f.as_uri())
                    levels = {1: 2, 2: 4, 4: 16}[depth]
                    subprocess.run(['magick', str(png), '-alpha', 'off', '-colorspace', 'gray', '-dither', 'None',
                                    '-colors', str(levels), '-depth', '8', str(png)], check=True)
    for s in sizes:
        print(f'{s[0]:15} {s[1]:4} {s[2]:16} context {s[3]:.1f}px')
    if args.screens:
        SCREENS.mkdir(parents=True, exist_ok=True)
        for name in SCREEN_SET:
            png = OUT / f'{name}.png'
            if png.exists():
                shutil.copy(png, SCREENS / png.name)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('render checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
