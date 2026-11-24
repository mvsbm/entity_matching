// The character-level comparison functions as DuckDB's twins score them (nayose/engines.py: rapidfuzz 3), for
// BigQuery's JavaScript UDFs: each takes two strings (code points, not UTF-16 units). Jaro and Jaro–Winkler are float32s,
// as rapidfuzz's cpdist returns them, the rest as it does: so the last bit of the double, which rapidfuzz's builds round
// differently (arm64 fuses Jaro–Winkler's boost into one multiply-add), never reaches a comparison.
function chars(s) { return Array.from(s); }

function jaro(a, b) {  // as a float32, as rapidfuzz's cpdist gives every similarity (DuckDB's engine compares that)
  return Math.fround(jaro_double(a, b));
}

function jaro_double(a, b) {
  const x = chars(a), y = chars(b);
  if (!x.length && !y.length) return 1.0;
  if (!x.length || !y.length) return 0.0;
  const window = Math.max(0, Math.floor(Math.max(x.length, y.length) / 2) - 1);
  const xm = new Array(x.length).fill(false), ym = new Array(y.length).fill(false);
  let m = 0;
  for (let i = 0; i < x.length; i++) {
    const lo = Math.max(0, i - window), hi = Math.min(y.length - 1, i + window);
    for (let j = lo; j <= hi; j++) {
      if (!ym[j] && x[i] === y[j]) { xm[i] = ym[j] = true; m++; break; }
    }
  }
  if (!m) return 0.0;
  let t = 0, k = 0;
  for (let i = 0; i < x.length; i++) {
    if (!xm[i]) continue;
    while (!ym[k]) k++;
    if (x[i] !== y[k]) t++;
    k++;
  }
  t = Math.floor(t / 2);
  return (m / x.length + m / y.length + (m - t) / m) / 3.0;
}

function jaro_winkler(a, b) {  // the prefix boost on Jaro past 0.7, the first four characters at most
  const sim = jaro_double(a, b), x = chars(a), y = chars(b);
  if (sim <= 0.7) return Math.fround(sim);
  let prefix = 0;
  while (prefix < 4 && prefix < x.length && prefix < y.length && x[prefix] === y[prefix]) prefix++;
  return Math.fround(sim + prefix * 0.1 * (1.0 - sim));
}

function damerau_levenshtein(a, b) {  // unrestricted (rapidfuzz's DamerauLevenshtein): adjacent swaps, any edits between
  const x = chars(a), y = chars(b), last = new Map(), max = x.length + y.length;
  const d = Array.from({length: x.length + 2}, () => new Array(y.length + 2).fill(0));
  d[0][0] = max;
  for (let i = 0; i <= x.length; i++) { d[i + 1][0] = max; d[i + 1][1] = i; }
  for (let j = 0; j <= y.length; j++) { d[0][j + 1] = max; d[1][j + 1] = j; }
  for (let i = 1; i <= x.length; i++) {
    let db = 0;
    for (let j = 1; j <= y.length; j++) {
      const i1 = last.get(y[j - 1]) || 0, j1 = db, cost = x[i - 1] === y[j - 1] ? 0 : 1;
      if (!cost) db = j;
      d[i + 1][j + 1] = Math.min(d[i][j] + cost, d[i + 1][j] + 1, d[i][j + 1] + 1, d[i1][j1] + (i - i1 - 1) + 1 + (j - j1 - 1));
    }
    last.set(x[i - 1], i);
  }
  return d[x.length + 1][y.length + 1];
}

function hamming(a, b) {  // rapidfuzz pads the shorter at its end: each missing character one more
  const x = chars(a), y = chars(b), n = Math.max(x.length, y.length);
  let dist = 0;
  for (let i = 0; i < n; i++) if (i >= x.length || i >= y.length || x[i] !== y[i]) dist++;
  return dist;
}

if (typeof module !== "undefined") module.exports = {jaro, jaro_winkler, damerau_levenshtein, hamming};
