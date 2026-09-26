// Writes tests/fixtures/tinypaper_sample.json: tiny-paper's own poster selection (plugins/litclock/converter/src/text.ts,
// posters()) for a sample of 12-hour minutes, so tests/test_data.py can check that tools/build_data.py picks the same
// passage and marks the same time words. Needs Node 23.6+ (TypeScript type stripping) and a tiny-paper checkout.
//
// Usage: node tools/tinypaper_reference.mjs <tiny-paper>/plugins/litclock
// SPDX-License-Identifier: MIT

import { writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const litclock = process.argv[2];
if (!litclock) {
  console.error('usage: node tools/tinypaper_reference.mjs <tiny-paper>/plugins/litclock');
  process.exit(1);
}
const text = await import(pathToFileURL(join(litclock, 'converter/src/text.ts')).href);
const rows = text.loadRows(join(litclock, 'data/passages.json'));
const set = text.posters(rows);

// Every 5th minute (144), from every source.
const picked = set.posters.filter((p, i) => i % 5 === 0);
const out = picked.map((p) => ({
  minute: p.minute,
  time: text.timeOf(p.minute),
  source: p.source,
  title: p.title,
  author: p.author,
  units: p.units.map((u) => [u.pre.join(''), u.word, u.post.join(''), u.emph ? 1 : 0]),
}));

const here = dirname(fileURLToPath(import.meta.url));
const file = join(here, '../tests/fixtures/tinypaper_sample.json');
writeFileSync(file, JSON.stringify({ covered: set.covered, minutes: out }, null, 0).replace(/\},\{"minute"/g, '},\n{"minute"') + '\n');
console.log(`${out.length} minutes -> ${file}`);
