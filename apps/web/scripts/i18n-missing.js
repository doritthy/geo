// Lists tr('…') keys used in the UI that have no Kazakh translation in
// lib/i18n.kk.ts.  Usage: node scripts/i18n-missing.js  (exit 1 if any)
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const dict = fs.readFileSync(path.join(root, 'lib/i18n.kk.ts'), 'utf8');
const have = new Set([...dict.matchAll(/^\s*("(?:[^"\\]|\\.)*")\s*:/gm)].map((m) => JSON.parse(m[1])));

const missing = new Map();
function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (!['node_modules', '.next', 'public'].includes(e.name)) walk(p);
    } else if (/\.(tsx?|jsx?)$/.test(e.name) && !p.endsWith('i18n.kk.ts')) {
      const src = fs.readFileSync(p, 'utf8');
      for (const m of src.matchAll(/\btr\(\s*'((?:[^'\\]|\\.)*)'/g)) {
        const key = m[1].replace(/\\'/g, "'");
        if (/[А-Яа-яЁё]/.test(key) && !have.has(key)) missing.set(key, path.relative(root, p));
      }
    }
  }
}
['app', 'components', 'lib'].forEach((d) => walk(path.join(root, d)));
for (const [k, f] of missing) console.log(`${f}: ${k}`);
console.log(`${missing.size} missing`);
process.exit(missing.size ? 1 : 0);
