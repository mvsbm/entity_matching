// The character-level comparison functions as rapidfuzz 3 computes them, for BigQuery's JavaScript UDFs: each takes
// two strings (code points, not UTF-16 units) and returns what rapidfuzz.distance.<Name> gives.
function chars(s) { return Array.from(s); }

function jaro(a, b) {
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

function parts(x) {  // a double as an exact integer m and exponent e: x = m · 2^e
  if (x === 0) return [0n, 0];
  const v = new DataView(new ArrayBuffer(8));
  v.setFloat64(0, x);
  const hi = v.getUint32(0), lo = v.getUint32(4), biased = (hi >>> 20) & 0x7ff;
  let m = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  if (biased) m |= 1n << 52n;
  return [hi >>> 31 ? -m : m, (biased || 1) - 1075];
}

function rounded(m, e) {  // m · 2^e to the nearest double, ties to even (results here are normal numbers)
  if (m === 0n) return 0;
  const negative = m < 0n;
  if (negative) m = -m;
  const shift = m.toString(2).length - 53;
  if (shift > 0) {
    const rest = m & ((1n << BigInt(shift)) - 1n), half = 1n << BigInt(shift - 1);
    m >>= BigInt(shift);
    if (rest > half || (rest === half && (m & 1n))) m += 1n;
    e += shift;
  }
  const r = Number(m) * Math.pow(2, e);
  return negative ? -r : r;
}

function fma(a, b, c) {  // a · b + c, rounded once, as a fused multiply-add gives it
  const [ma, ea] = parts(a), [mb, eb] = parts(b), [mc, ec] = parts(c);
  const ep = ea + eb, e = Math.min(ep, ec);
  return rounded((ma * mb << BigInt(ep - e)) + (mc << BigInt(ec - e)), e);
}

function jaro_winkler(a, b) {  // the prefix boost as rapidfuzz computes it: one fused multiply-add
  const sim = jaro(a, b), x = chars(a), y = chars(b);
  if (sim <= 0.7) return sim;
  let prefix = 0;
  while (prefix < 4 && prefix < x.length && prefix < y.length && x[prefix] === y[prefix]) prefix++;
  return fma(prefix * 0.1, 1.0 - sim, sim);
}

function levenshtein(a, b) {
  const x = chars(a), y = chars(b);
  let prev = Array.from({length: y.length + 1}, (_, j) => j);
  for (let i = 1; i <= x.length; i++) {
    const cur = [i];
    for (let j = 1; j <= y.length; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x[i - 1] === y[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[y.length];
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

function jaccard(a, b) {  // character sets
  const x = new Set(chars(a)), y = new Set(chars(b));
  if (!x.size && !y.size) return 0.0;
  let both = 0;
  for (const c of x) if (y.has(c)) both++;
  return both / (x.size + y.size - both);
}

if (typeof module !== "undefined") module.exports = {jaro, jaro_winkler, levenshtein, damerau_levenshtein, hamming, jaccard};
