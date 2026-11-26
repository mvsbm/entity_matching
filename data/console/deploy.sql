CREATE OR REPLACE PROCEDURE `YOUR_PROJECT.nayose`.build()
BEGIN
SELECT ERROR('deploy: the last deploy did not finish; deploy again');
END;

CREATE OR REPLACE PROCEDURE `YOUR_PROJECT.nayose`.update()
BEGIN
SELECT ERROR('deploy: the last deploy did not finish; deploy again');
END;

CREATE OR REPLACE PROCEDURE `YOUR_PROJECT.nayose`.decide()
BEGIN
SELECT ERROR('deploy: the last deploy did not finish; deploy again');
END;

CREATE OR REPLACE PROCEDURE `YOUR_PROJECT.nayose`.match(v_threshold FLOAT64)
BEGIN
SELECT ERROR('deploy: the last deploy did not finish; deploy again');
END;

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cl_jaro_winkler(a STRING, b STRING) RETURNS FLOAT64 LANGUAGE js AS r"""// The character-level comparison functions as DuckDB's twins score them (nayose/engines.py: rapidfuzz 3), for
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

return a === null || b === null ? null : jaro_winkler(a, b);""";

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cl_jaro_winkler_cut(a STRING, b STRING, threshold FLOAT64) RETURNS FLOAT64 LANGUAGE js AS r"""// The character-level comparison functions as DuckDB's twins score them (nayose/engines.py: rapidfuzz 3), for
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

return a === null || b === null ? null : jaro_winkler(a, b);""";

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cl_levenshtein(a STRING, b STRING) AS (CAST(EDIT_DISTANCE(a, b) AS FLOAT64));

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cl_levenshtein_cut(a STRING, b STRING, threshold FLOAT64) AS (CAST(LEAST(EDIT_DISTANCE(a, b), FLOOR(threshold) + 1) AS FLOAT64));

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cl_damerau_levenshtein(a STRING, b STRING) RETURNS FLOAT64 LANGUAGE js AS r"""// The character-level comparison functions as DuckDB's twins score them (nayose/engines.py: rapidfuzz 3), for
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

return a === null || b === null ? null : damerau_levenshtein(a, b);""";

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cl_damerau_levenshtein_cut(a STRING, b STRING, threshold FLOAT64) RETURNS FLOAT64 LANGUAGE js AS r"""// The character-level comparison functions as DuckDB's twins score them (nayose/engines.py: rapidfuzz 3), for
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

return a === null || b === null ? null : damerau_levenshtein(a, b);""";

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cl_hamming(a STRING, b STRING) RETURNS FLOAT64 LANGUAGE js AS r"""// The character-level comparison functions as DuckDB's twins score them (nayose/engines.py: rapidfuzz 3), for
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

return a === null || b === null ? null : hamming(a, b);""";

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cl_hamming_cut(a STRING, b STRING, threshold FLOAT64) RETURNS FLOAT64 LANGUAGE js AS r"""// The character-level comparison functions as DuckDB's twins score them (nayose/engines.py: rapidfuzz 3), for
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

return a === null || b === null ? null : hamming(a, b);""";

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.er_hash(x ANY TYPE) AS (CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(COALESCE(CAST(x AS STRING), ''))), 1, 15)) AS INT64));

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.nfkc(x STRING) AS (NORMALIZE(x, NFKC));

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.one_byte_hash(x STRING) AS (CODE_POINTS_TO_STRING(ARRAY(SELECT 33 + MOD(c, 94) FROM UNNEST(TO_CODE_POINTS(x)) AS c WITH OFFSET AS i ORDER BY i)));

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.fit_model(counts STRING, settings STRING, given_fit STRING) RETURNS STRING LANGUAGE python OPTIONS (runtime_version = 'python-3.11', entry_point = 'fit') AS r'''"""Stage 2, fit: learn the Fellegi–Sunter model from the counts fit.sql leaves, to the same numbers Splink 5.0 gives.

The model has three sorts of number:

    λ   how likely two random records are one entity: the pairs the near-certain rules find (the prior), divided by
        the share of all matches those rules find (prior_recall), divided by every pair of the sample.
    u   how often two different entities fall into a level by chance: counted exactly where fit.sql counts it, else
        measured on sampled pairs, else, when no sampled pair reached the level, an upper bound.
    m   how often one entity's two records fall into a level: learned by EM sessions on the sample's pairs that
        share a field, each session starting from what the sessions before it learned. A level's m is the median.

After learning, u is measured again on the file to be scored: in a bigger file, a field whose values grow with it
agrees by chance less often. An update scores with the model as the build left it, as a saved model is reused;
building again measures u on the run as it has grown.

fit() is a pure function, JSON in and JSON out, using the standard library only. fit.sql calls it as fit_model, on
BigQuery as a Python UDF (nayose.procedures.functions) and on DuckDB alike. Cost:
O(iterations · patterns · K) for K comparisons.
"""
import copy
import json
import math
import statistics

START_M = 0.95  # Splink's first guess of m for a comparison's first level
UNSEEN_M = 1e-6  # the m Splink gives a level that no pair of the session reached
MAX_ITERATIONS = 25  # Splink's max_iterations
CONVERGED = 1e-4  # Splink's em_convergence: stop once no m and no λ moves by more than this
ELSE = "else"  # the label of each comparison's last level: none of the others
LAMBDA_CAP = 1 - 1e-9  # the most the rescaled λ can be, a hair under 1, so that its log-odds stay finite (score.sql's)
PRIOR_RULES = {  # fit_prior's columns, named as the report names the rules
    "cif_name": "customer_id + full_name",
    "cif_company": "customer_id + company_name",
    "name_code_phone": "full_name + address_code + phone",
}


def fit(counts: str, settings: str, given_fit: str | None = None) -> str:
    """Fit the model and return it as JSON.

    `counts` holds fit.sql's tables, each a list of rows; `settings` is config.toml's [fit]. Without `given_fit` (a
    build), the model is learned on the sample (learn) and its u measured on the file (assemble). With `given_fit`,
    what fit returned for another file (as scripts/benchmark.py fits one on a train split), that model is used and its
    u measured on this file whole.

    The result holds each level with m and u as fitted and as measured on the file (file_m, file_u, and bits: what a
    score adds), λ and its bits at the file's size (prior_bits), the sample's size, the notes the report reads, and the
    model as fitted.
    """
    tables, config = json.loads(counts), json.loads(settings)
    # by comparison, then the strongest level first
    levels = sorted(tables["levels"], key=lambda lv: (lv["position"], -lv["gamma"]))
    measures = measured(tables, config)
    model = (json.loads(given_fit)["model"] if given_fit is not None
             else learn(levels, measures["sample"], tables["prior"][0], tables["patterns"] or [], config))
    file = measures["file"]
    exact = exact_u(levels, file)
    sampled = sampled_u(levels, file, [x for x in comparisons(levels) if ELSE not in exact.get(x, {})])
    return fitted(model, assemble(model, file, sampled), file["n"])


def fitted(model: dict, scoring: dict, n: int) -> str:
    """Return what fit gives back, as JSON: the model as scored on a file of `n` records."""
    # λ is a per-pair rate, so it is rescaled to the file's size (score.sql's level_bits rescales it the same way)
    lam = min(model["probability"] * (model["fit_records"] - 1) / max(n - 1, 1), LAMBDA_CAP)
    levels = [dict(lv, file_m=f["m"], file_u=f["u"], bits=bits(f["m"], f["u"]))
              for lv, f in zip(model["levels"], scoring["levels"])]
    notes = dict(model["notes"], file_adjusted=scoring["notes"]["adjusted"])
    return json.dumps(dict(levels=levels, probability=model["probability"], fit_records=model["fit_records"], records=n,
                           prior_bits=math.log2(lam / (1 - lam)), notes=notes, model=model))


def bits(m: float, u: float) -> float:
    """Return a level's weight as Splink writes it: log2(m/u), each clamped at 1e-300."""
    return math.log2(max(m, 1e-300) / max(u, 1e-300))


# ---------- u: the counts made into shares ----------

def measured(tables: dict, config: dict) -> dict[str, dict]:
    """Return fit.sql's u counts by scope (sample, file), with each scope's max_pairs: what its sample drew from."""
    out = {}
    for scope, most in (("sample", float(config["fit_u_max_pairs"])), ("file", float(config["u_max_pairs"]))):
        def rows_of(table: str) -> list[dict]:
            return [r for r in tables.get(table) or [] if r["scope"] == scope]
        filled = next(iter(rows_of("filled")), {"records": 0})
        out[scope] = dict(n=filled["records"], max_pairs=most, filled=filled, plan=next(iter(rows_of("plan")), {}),
                          outside={r["comparison"]: r["pairs"] for r in rows_of("outside")},
                          counted={(r["comparison"], r["label"]): r["pairs"] for r in rows_of("counted")},
                          one_edit={(r["comparison"], r["label"]): r["pairs"] for r in rows_of("one_edit")},
                          sampled={(r["comparison"], r["gamma"]): r["pairs"] for r in rows_of("sampled")})
    return out


def exact_u(levels: list[dict], counts: dict) -> dict[str, dict[str, float]]:
    """Return the u of each comparison's levels that fit.sql counted exactly.

    Each u is a share of the pairs outside the comparison's missing level. When every level is counted, the else
    level's u is the rest. A comparison with no level counted is left out.
    """
    out: dict[str, dict[str, float]] = {}
    for name in comparisons(levels):
        counted_levels = [lv for lv in levels if lv["comparison"] == name and lv["agreement"] != ELSE]
        if u_of := counted_u(name, counted_levels, counts):
            out[name] = u_of
    return out


def counted_u(name: str, counted_levels: list[dict], counts: dict) -> dict[str, float]:
    """Return the u of `counted_levels`, one comparison's levels but its else level, that fit.sql counted, in order.

    A level counted with no pair has no u. When some level has a u and every one does, the else level's u is the rest.
    """
    outside = float(counts["outside"][name])
    u_of: dict[str, float] = {}
    for lv in counted_levels:
        pairs = counts["counted"].get((name, lv["label"]), counts["one_edit"].get((name, lv["label"])))
        if pairs is None:
            break  # a level not counted: neither is any after it
        u = float(pairs) / outside if outside else 0.0
        if u > 0:
            u_of[lv["label"]] = u
    if not u_of or any(lv["label"] not in u_of for lv in counted_levels):
        return u_of  # no rest unless some level has a u, and every one does: the else level is sampled
    counted = 0.0
    for u in u_of.values():  # added in turn: Python 3.12+'s sum() rounds otherwise, and BigQuery runs 3.11
        counted += u
    rest = 1 - counted
    if rest > 0:
        u_of[ELSE] = rest  # every level counted: nothing is left to sample
    return u_of


def sampled_u(levels: list[dict], counts: dict, names: list[str]) -> dict[str, dict[str, float]]:
    """Return the u of these comparisons' levels in the sampled pairs.

    A level's u is its pairs over the pairs with the comparison filled. A level no pair reached has none.
    """
    out = {}
    for name in names:
        its_levels = [lv for lv in levels if lv["comparison"] == name]
        if counts["plan"].get(name) is False:
            raise RuntimeError(f"fit.sql counted {name} to its else level and sampled none of its pairs, "
                               "where nayose.em samples it")
        sampled = counts["sampled"]
        filled = sum(sampled.get((name, lv["gamma"]), 0) for lv in its_levels)
        out[name] = {lv["label"]: sampled[name, lv["gamma"]] / filled
                     for lv in its_levels if sampled.get((name, lv["gamma"]))}
    return out


def u_bound(counts: dict, name: str) -> float:
    """Return a 95% upper bound on u for a level no sampled pair reached.

    The bound counts zero hits among the sampled pairs where the comparison is filled, of which there are at least the
    sample times its fill share squared.
    """
    n = counts["n"]
    filled_pairs = min(counts["max_pairs"], n * (n - 1) / 2) * (counts["filled"][name] / n if n else 0.0) ** 2
    return 1 - 0.05 ** (1 / max(1, int(filled_pairs)))


def comparisons(levels: list[dict]) -> list[str]:
    """Return the comparisons, in the model's order."""
    return list(dict.fromkeys(lv["comparison"] for lv in levels))


# ---------- the model learned on the sample ----------

def learn(levels: list[dict], counts: dict, prior_counts: dict, patterns: list[dict], settings: dict) -> dict:
    """Learn the model on the sample: u, then λ, then m by the EM sessions in order.

    Raises ValueError when no near-certain rule, or no session's field, finds a pair in the sample, or the rules find
    more pairs than their recall allows.
    """
    names = comparisons(levels)
    model, filled_u = sample_u(levels, counts, names)
    records, prior_pairs = prior_counts["records"], prior_counts["prior_pairs"]
    rules_found = [rule for rule in PRIOR_RULES if prior_counts[rule]]
    sessions = [s["field"] for s in settings["em_sessions"]]
    patterns_of = {s: [tuple(p[n] for n in names) + (p["pairs"],) for p in patterns if p["session"] == s]
                   for s in sessions}
    em_pairs = {s: sum(p[-1] for p in patterns_of[s]) for s in sessions if patterns_of[s]}
    lam = prior_rate(records, prior_pairs, rules_found, sessions, em_pairs, settings["prior_recall"])
    with_pairs = [s for s in settings["em_sessions"] if s["field"] in em_pairs]
    learned, filled_m = learn_m(model, with_pairs, patterns_of, names, lam)
    adjusted = sensible_m(model, {tuple(x) for x in filled_m})
    skipped = [PRIOR_RULES[r] for r in PRIOR_RULES if r not in rules_found] + [s for s in sessions if s not in em_pairs]
    by_session = {s: [[name, label, m] for (name, label), m in m_of.items()] for s, m_of in learned.items()}
    return dict(model, probability=lam, fit_records=records,
                notes=dict(fit_records=records, filled=dict(u=filled_u, m=filled_m), skipped=skipped, adjusted=adjusted,
                           em_pairs=em_pairs, em_sessions=by_session))


def sample_u(levels: list[dict], counts: dict, names: list[str]) -> tuple[dict, list[list[str]]]:
    """Return the model before EM, each level's u on the sample and its m unknown, and the levels whose u is a bound."""
    exact = exact_u(levels, counts)
    skip = {name for name, u in exact.items() if ELSE in u}
    u = {**{name: {} for name in skip}, **sampled_u(levels, counts, [x for x in names if x not in skip])}
    u = {name: {**u_of, **exact.get(name, {})} for name, u_of in u.items()}
    filled_u = [[lv["comparison"], lv["label"]] for lv in levels if lv["label"] not in u[lv["comparison"]]]
    model = dict(levels=[dict(lv, u=u[lv["comparison"]].get(lv["label"]) or u_bound(counts, lv["comparison"]), m=None)
                         for lv in levels])
    return model, filled_u


def prior_rate(records: int, prior_pairs: int, rules_found: list[str], sessions: list[str], em_pairs: dict,
               recall: float) -> float:
    """Return λ: the pairs the near-certain rules find, over their recall, over every pair of the sample.

    Raises ValueError when no near-certain rule, or no session's field, finds a pair in the sample, or the rules find
    more pairs than their recall allows.
    """
    if not rules_found:
        raise ValueError(f"no two records of the {records:,} the fit samples agree on any near-certain rule "
                         f"({'; '.join(PRIOR_RULES.values())}), so the chance that two records match can't be "
                         "estimated: map the fields those rules read")
    if not em_pairs:
        raise ValueError(f"no two records of the {records:,} the fit samples share {' or '.join(sessions)}, "
                         "the pairs it learns from: map those fields to filled columns")
    all_pairs = int(records * (records - 1) / 2)
    if prior_pairs > all_pairs * recall:
        raise ValueError(f"the near-certain rules find {prior_pairs:,} of the {all_pairs:,} pairs, more than a recall "
                         f"of {recall} allows (at least {prior_pairs / all_pairs:,.2f}): "
                         "raise [fit] prior_recall, or make the prior rules stricter")
    return prior_pairs / recall / all_pairs


def learn_m(model: dict, with_pairs: list[dict], patterns_of: dict[str, list[tuple]], names: list[str],
            lam: float) -> tuple[dict, list[list[str]]]:
    """Learn each level's m by the EM sessions `with_pairs`, in order: the median of what they learned, else its u.

    Returns what each session learned, and the levels whose m is their u.
    """
    trained: dict[tuple[str, str], list[float]] = {}  # each level's m, as each session so far learned it
    learned = {}
    for s in with_pairs:
        learned[s["field"]] = session(model, patterns_of[s["field"]], names, s, lam, trained)
        for key, value in learned[s["field"]].items():
            trained.setdefault(key, []).append(value)
    filled_m = []
    for lv in model["levels"]:
        if (lv["comparison"], lv["label"]) in trained:
            lv["m"] = statistics.median(trained[lv["comparison"], lv["label"]])
        else:
            lv["m"] = lv["u"]
            filled_m.append([lv["comparison"], lv["label"]])
    return learned, filled_m


def first_m(model: dict, name: str, gamma: int, trained: dict) -> float:
    """Return the m a session starts a level from: the median of what earlier sessions learned, else Splink's guess."""
    lv = next(x for x in model["levels"] if x["comparison"] == name and x["gamma"] == gamma)
    if earlier := trained.get((name, lv["label"])):
        return statistics.median(earlier)
    n = sum(1 for x in model["levels"] if x["comparison"] == name)
    return START_M if gamma == n - 1 else (1 - START_M) / (n - 1)


def probability(p: float) -> float:
    """Return the chance of a match for `p` points, written so that 2^p never overflows."""
    return 1.0 / (1.0 + 2.0 ** -p) if p >= 0 else 2.0 ** p / (1.0 + 2.0 ** p)


def odds(p: float) -> float:
    """Return the odds of a chance `p`."""
    return p / (1 - p) if p != 1 else math.inf


def session(model: dict, patterns: list[tuple], names: list[str], s: dict, lam: float,
            trained: dict) -> dict[tuple[str, str], float]:
    """Run one EM session on the pairs that share its field, and return each level's m after its last iteration.

    `patterns` holds each pattern of levels with its count, in order; a comparison the field fixed is None. λ among
    these pairs starts from λ with the evidence of the exact levels the field guarantees. Each iteration guesses each
    pattern's chance of a match from λ's bits and its levels' bits, added left to right (E), then counts m from those
    guesses (M). The session stops once nothing moves by CONVERGED, or after MAX_ITERATIONS. A level no pair reached is
    left out of the result.
    """
    learns = [i for i, name in enumerate(names) if all(p[i] is not None for p in patterns)]  # its field fixed the rest
    order = [names[i] for i in learns]
    # λ among the session's pairs, from their prior odds: λ's odds times the evidence m/u of each exact level the
    # field guarantees, prior_odds = λ/(1 − λ) · Π m/u, so λ_s = prior_odds / (1 + prior_odds)
    prior_odds = odds(lam)
    for name, label in s["start"]:
        lv = next(x for x in model["levels"] if x["comparison"] == name and x["label"] == label)
        evidence = first_m(model, name, lv["gamma"], trained) / lv["u"] if lv["u"] != 0 else math.inf
        prior_odds = evidence * prior_odds
    lam_s = prior_odds / (1 + prior_odds)
    u = {(lv["comparison"], lv["gamma"]): lv["u"] for lv in model["levels"] if lv["comparison"] in order}
    label_of = {(lv["comparison"], lv["gamma"]): lv["label"] for lv in model["levels"]}
    m: dict[tuple[str, int], float | None] = {key: first_m(model, key[0], key[1], trained) for key in u}
    # in order, as SQL's ORDER BY ALL sorts them
    rows = [(list(x[:-1]), x[-1]) for x in sorted(tuple(p[i] for i in learns) + (p[-1],) for p in patterns)]
    for _ in range(MAX_ITERATIONS):
        bits_at_level = {key: bits(seen(m[key]), u[key]) for key in m}
        bits_at_level |= {(n, -1): 0.0 for n in order}  # a missing comparison weighs nothing
        matches, pairs, expected = expect(rows, order, bits_at_level, math.log2(odds(lam_s)))
        new, new_lam = maximise(expected, m, order), matches / pairs
        moved = [abs(seen(new[k]) - seen(m[k])) for k in m] + [abs(new_lam - lam_s)]
        m, lam_s = new, new_lam
        if max((x for x in moved if not math.isnan(x)), default=0.0) < CONVERGED:
            break
    return {(key[0], label_of[key]): v for key, v in m.items() if v is not None}


def seen(m: float | None) -> float:
    """Return a level's m, or UNSEEN_M where no pair of the session reached it (None)."""
    return UNSEEN_M if m is None else m


def expect(rows: list[tuple], order: list[str], bits_at_level: dict, prior_bits: float) -> tuple[float, int, dict]:
    """E: guess each pattern's chance of a match from its points, λ's bits and its levels' bits added left to right.

    Returns the matches expected among the pairs, the pairs, and the matches expected at each level.
    """
    expected: dict[tuple[str, int], float] = {}
    matches, pairs = 0.0, 0
    for gammas, count in rows:  # loops, not sum(): Python 3.12+'s sum() rounds otherwise, and BigQuery runs 3.11
        total = prior_bits
        for name, gamma in zip(order, gammas):
            total = total + bits_at_level[name, gamma]
        p = probability(total)
        matches += p * count
        pairs += count
        for name, gamma in zip(order, gammas):
            expected[name, gamma] = expected.get((name, gamma), 0.0) + p * count
    return matches, pairs, expected


def maximise(expected: dict, m: dict, order: list[str]) -> dict[tuple[str, int], float | None]:
    """M: count each level's m from E's guesses (share); None where no pair reached it."""
    new: dict[tuple[str, int], float | None] = {}
    for name in order:
        filled = 0.0
        for key in sorted(k for k in expected if k[0] == name and k[1] >= 0):  # a loop, not sum(), as in expect
            filled += expected[key]
        for key in (k for k in m if k[0] == name):
            new[key] = share(expected, key, filled)
    return new


def share(expected: dict, key: tuple[str, int], filled: float) -> float | None:
    """Return a level's m: its expected matches over its comparison's `filled`; None where no pair reached it."""
    m = expected[key] / filled if key in expected and filled else math.nan
    return m if m >= 1e-300 else None  # no pair reached it, or its share is nothing (NaN too)


def sensible_m(model: dict, filled: set[tuple[str, str]]) -> list[list]:
    """Hold EM's m to two limits, each where the sample gave EM nothing to go by, and return what changed.

    - A fuzzy level stands for a typo in a value that matches share. Where no match agreed exactly in training (each
      exact level's m was filled as its u), a fuzzy agreement only means neighbouring values, such as IDs handed out
      in sequence: no evidence, so m = u and the level weighs 0 bits.
    - Partial agreement is never more evidence against a match than none: a level weighs at least its else level.
    """
    out = []
    for name in comparisons(model["levels"]):
        its_levels = [lv for lv in model["levels"] if lv["comparison"] == name]
        out += fuzzy_without_exact(name, its_levels, filled)
        out += at_least_else(name, its_levels)
    return out


def fuzzy_without_exact(name: str, its_levels: list[dict], filled: set[tuple[str, str]]) -> list[list]:
    """Give a comparison's fuzzy levels m = u where each of its exact levels' m was filled as u; return what changed."""
    exact = [lv for lv in its_levels if lv["agreement"] == "exact"]
    if not exact or not all((name, lv["label"]) in filled for lv in exact):
        return []
    out = []
    for lv in its_levels:
        if lv["agreement"] == "fuzzy" and lv["m"] != lv["u"]:
            was = round(math.log2(lv["m"] / lv["u"]), 2)
            out.append([name, lv["label"], "no exact agreement among matches: 0 bits", was])
            lv["m"] = lv["u"]
    return out


def at_least_else(name: str, its_levels: list[dict]) -> list[list]:
    """Raise each level of a comparison that weighs less than its else level to that weight; return what changed."""
    other = next((lv for lv in its_levels if lv["agreement"] == ELSE), None)
    if other is None:
        return []
    out = []
    floor = other["m"] / other["u"]
    for lv in its_levels:
        if lv is not other and lv["m"] / lv["u"] < floor:
            was = round(math.log2(lv["m"] / lv["u"]), 2)
            out.append([name, lv["label"], "less than no agreement: the else level's weight", was])
            lv["m"] = lv["u"] * floor
    return out


# ---------- u on the file to be scored ----------

def assemble(model: dict, counts: dict, sampled: dict) -> dict:
    """Return the model with each level's u measured on the file.

    A level's u is counted exactly, else taken from `sampled`, else the bound on the file. A level never seen in
    training keeps m = u, 0 bits. m and λ stay as fitted, within sensible_m's limits again.
    """
    exact = exact_u(model["levels"], counts)
    filled_m = {tuple(x) for x in model["notes"]["filled"]["m"]}
    out = copy.deepcopy(model)
    for lv in out["levels"]:
        name, label = lv["comparison"], lv["label"]
        lv["u"] = exact.get(name, {}).get(label) or sampled.get(name, {}).get(label) or u_bound(counts, name)
        if (name, label) in filled_m:
            lv["m"] = lv["u"]
    out["notes"] = {**out["notes"], "adjusted": sensible_m(out, filled_m)}
    return out
''';

CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.entities_of(pairs STRING) RETURNS STRING LANGUAGE python OPTIONS (runtime_version = 'python-3.11', entry_point = 'of') AS r'''"""decide's connected components (decide.sql): turn the pairs people said match into each record's entity.

An entity is named by its smallest ID, in a string's order, so A–B and B–C make one entity even if A–C was never
decided. of() is a pure function, JSON in and JSON out, using the standard library only. decide.sql calls it as
entities_of, on BigQuery as a Python UDF (nayose.procedures.functions) and on DuckDB alike. O(D log D) for D pairs.
"""
import json


def of(pairs: str) -> str:
    """Return each ID the pairs name, with its entity's smallest ID.

    `pairs` is {"pairs": [{"l": id, "r": id}, ...]}, or {"pairs": null} for none. The result is
    [{"id": id, "entity": id}, ...].
    """
    parent: dict[str, str] = {}  # union–find: each ID's parent; a root is its entity's smallest ID

    def root(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]  # path halving: the next walk is shorter
            x = parent[x]
        return x

    for p in json.loads(pairs)["pairs"] or []:
        a, b = root(p["l"]), root(p["r"])
        parent[max(a, b)] = min(a, b)  # of two roots, the smaller stays one
    return json.dumps([{"id": x, "entity": root(x)} for x in parent])
''';

-- The functions that nayose's SQL calls, each written once. Every job runs this file first. It has four sections.
--
-- 1. The intake. mapping.sql reads every input column through `YOUR_PROJECT.nayose`.read_value(value, numeric, @nulls), which fixes what
--    can be fixed without losing anything. O(bytes). It applies these fixes in order:
--    - Damaged values. A value that holds U+FFFD is missing. U+FFFD means that bytes were decoded wrongly upstream,
--      or weren't UTF-8.
--    - Lists. A value written as a list of plain items (["8700848"], ['大分市'], [0708612]) becomes its first filled
--      item, and the other items are dropped. If no item is filled, the value is missing.
--    - Controls. Control characters, zero-width characters and BOMs are removed. Each run of tabs and line breaks
--      becomes one space.
--    - Null tokens. A value written as a null token ([input] nulls), or made of spaces alone (any width), is missing.
--    - Numbers. These fixes apply only in a column of numbers (numeric is TRUE; the mapping says which). A whole
--      number that a spreadsheet wrote as a float (12345.0) becomes its digits. A number cut short in E notation
--      (1.23E+11) is missing, because its digits are gone.
--    In the comments below, SP stands for Python's whitespace (the characters str.strip removes). The regexes spell
--    it as [\t-\r\x{1c}-\x{1f}\x{85}\p{Z}], \p{Z} being Unicode's space, line and paragraph separators.
--
-- 2. The model's comparisons, which the fit (stage 2) and the scores call. Each compares two records on its fields,
--    and takes both records whole, as rows (x and y). Each returns a gamma, the level the pair lands in. The level is
--    -1 if either side is missing. The other levels count down from the highest to 0, the else level.
--    The cl_* functions compare by character (engines.py). In BigQuery they run as JavaScript, or as BigQuery's own
--    EDIT_DISTANCE for Levenshtein. In DuckDB they run as DuckDB's own functions if both strings take one byte a
--    character, and as rapidfuzz otherwise. A similarity passes at its threshold or above, and a distance passes at
--    its threshold or below. A cl_*_cut function returns the same score if the score passes its threshold. If the
--    score fails, it may return another failing score, so that it can stop early.
--    An edit distance is never less than the difference of the two lengths. Nor is it less than the distance between
--    the strings' one_byte_hash copies (records.sql). So the functions test those first, and skip the call if it
--    can't pass. The levels come out the same. A fuzzy level costs O(L²) a pair, for strings of L characters.
--
-- 3. The rules' fuzzy tests, which score.sql calls. Each says whether two names, companies, addresses or phones are
--    close enough.
--
-- 4. The steps that the stages share: pairs_of, which counts the pairs a block's records make, and the steps of the
--    address copy (records.sql).
--
-- Writes: no table. The table of the levels that section 2 numbers is fit.sql's (levels), its one reader.


-- ---------- 1. The intake ----------

-- `YOUR_PROJECT.nayose`.blank(v) is TRUE if v is empty or holds only spaces (SP, of any width).
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.blank(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*$'));


-- `YOUR_PROJECT.nayose`.trimmed(v) returns v without its leading and trailing spaces (SP), as Python's str.strip removes them.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.trimmed(v STRING) AS (REGEXP_REPLACE(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]+|[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]+$', ''));


-- The next four functions are read_value's steps after unlisted, in the order it applies them. Each reads its
-- argument once, because a function's argument is copied into every place its body reads it. Their parameters are
-- ANY TYPE because DuckDB binds a typed parameter's argument twice, so each step nested in the next would double the
-- time read_value takes to plan. A step that finds a value missing writes CHR(1) in its place, and read_value makes
-- CHR(1) missing at the end. No other value holds CHR(1) by then, because without_controls removes it.
-- without_controls removes control characters, zero-width characters and BOMs, and makes each run of tabs and line
-- breaks one space.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.without_controls(v ANY TYPE) AS (
  REGEXP_REPLACE(REGEXP_REPLACE(v, r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\x{200b}-\x{200d}\x{2060}\x{feff}]', ''),
                 r'[\t\r\n]+', ' ')
);


-- null_token_marked writes CHR(1) for a null token. null_regex is the regex that nayose.null_regex makes of
-- [input] nulls, and it also matches a value of spaces alone. The parameter isn't named nulls, a word BigQuery
-- reserves.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.null_token_marked(v ANY TYPE, null_regex ANY TYPE) AS (
  REGEXP_REPLACE(v, null_regex, CHR(1))
);


-- The two number steps change a value only if numeric is TRUE. cut_short_marked writes CHR(1) for a number cut short
-- in E notation (1.23E+11), whose digits are gone, and whole_number writes a whole number written as a float
-- (12345.0) as its digits. If numeric is FALSE, a step's regex is $^, which matches no value it is given (an empty
-- value is CHR(1) by then). whole_number's is ($^), which holds the group that its replacement \1 reads.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cut_short_marked(v ANY TYPE, numeric ANY TYPE) AS (
  REGEXP_REPLACE(v, IF(numeric, r'^[ \x{3000}]*-?\p{Nd}(\.\p{Nd}+)?[eE]\+\p{Nd}+[ \x{3000}]*$', r'$^'), CHR(1))
);


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.whole_number(v ANY TYPE, numeric ANY TYPE) AS (
  REGEXP_REPLACE(v, IF(numeric, r'^[ \x{3000}]*(-?\p{Nd}+)\.0+[ \x{3000}]*$', r'($^)'), r'\1')
);


-- The next six functions read a value written as a list. unlisted, which read_value calls, returns a plain list's
-- first filled item. It returns any other value as it is, except that an empty or damaged value is missing.
--   A list is plain if JSON reads it as a list of strings, numbers and nulls (["a", 1, null]), or if Python reads it
--   as a list of strings (['a', "b",]). An item is filled if it holds more than spaces, and an escape counts as
--   filled.
--   shortcut: a list that JSON can't read is left as written if a string in it holds a backslash, although Python
--   would decode the escapes. Decode them if a records file ever holds such a list.
--   The regexes are made of these pieces. A JSON string is "(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*". A JSON
--   number is -?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?. A Python string is '…' or "…" without a
--   backslash or a line break, and the regexes write ' as \x{27}. A blank item is "SP*", 'SP*' or null. ws is the
--   space, a tab or a line break, and in a Python list also a form feed. The three plain lists read:
--     code list     SP* [ SP* digits SP* ] SP*
--     JSON list     SP* [ ws (item (ws , ws item)*)? ws ] SP*, each item a JSON string, a JSON number or null
--     Python list   SP* [ ws (string (ws , ws string)* (ws ,)?)? ws ] SP*, each string a Python string
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.listed_item(v STRING) RETURNS STRING AS (
  -- It returns the first filled item as written, quotes and all, or NULL if no item is filled.
  REGEXP_EXTRACT(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\[[ \t\n\r\x{0c}]*(?:(?:"[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*"|\x{27}[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\x{27}|null)[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*)*("(?:[^"\\]|\\.)*(?:[^"\\\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]|\\.)(?:[^"\\]|\\.)*"|\x{27}[^\x{27}\\\r\n]*[^\x{27}\\\t-\r\x{1c}-\x{1f}\x{85}\p{Z}][^\x{27}\\\r\n]*\x{27}|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
);


-- item_read returns the value of an item that listed_item found. A string loses its quotes, and if it holds a
-- backslash, JSON_VALUE decodes its escapes (\u5927 becomes 大). A number goes through read_value's two number steps,
-- as in a column of numbers. So 12345.0 becomes 12345, a number cut short like 1.23E+11 is missing, and any other
-- stays as written.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.item_read(item STRING) RETURNS STRING AS (
  CASE
    WHEN item IS NULL THEN NULL
    WHEN NOT (STARTS_WITH(item, '"') OR STARTS_WITH(item, "'")) THEN  -- the item is a number
      NULLIF(`YOUR_PROJECT.nayose`.whole_number(`YOUR_PROJECT.nayose`.cut_short_marked(item, TRUE), TRUE), CHR(1))
    WHEN STRPOS(item, '\\') > 0 THEN JSON_VALUE(item)  -- JSON_VALUE decodes the escapes
    ELSE SUBSTR(item, 2, LENGTH(item) - 2)
  END
);


-- is_code_list, is_json_list and is_python_list are TRUE if v is written as a code list, a JSON list or a Python
-- list, as the comment above listed_item spells them. A code with leading zeros, such as [0708612], isn't JSON.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.is_code_list(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\[[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\p{Nd}+[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\][\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*$'));


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.is_json_list(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\[[ \t\n\r]*(?:(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null)(?:[ \t\n\r]*,[ \t\n\r]*(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null))*)?[ \t\n\r]*\][\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*$'));


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.is_python_list(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\[[ \t\n\r\x{0c}]*(?:(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*")(?:[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*"))*(?:[ \t\n\r\x{0c}]*,)?)?[ \t\n\r\x{0c}]*\][\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*$'));


-- unlisted returns v, or its first filled item if v is a plain list. A code list keeps its digits as written.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.unlisted(v STRING) RETURNS STRING AS (
  CASE
    WHEN v IS NULL OR v = '' OR REGEXP_CONTAINS(v, r'\x{fffd}') THEN NULL  -- an empty or damaged value is missing
    WHEN NOT REGEXP_CONTAINS(v, r'\[') THEN v                              -- most values hold no list
    WHEN `YOUR_PROJECT.nayose`.is_code_list(v) THEN REGEXP_EXTRACT(v, r'(\p{Nd}+)')
    WHEN `YOUR_PROJECT.nayose`.is_json_list(v) OR `YOUR_PROJECT.nayose`.is_python_list(v) THEN `YOUR_PROJECT.nayose`.item_read(`YOUR_PROJECT.nayose`.listed_item(v))
    ELSE v
  END
);


-- read_value returns a value as read, with section 1's fixes in order: unlisted, then the four steps above. Last,
-- NULLIF makes CHR(1) missing.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.read_value(v STRING, numeric BOOL, null_regex STRING) RETURNS STRING AS (
  NULLIF(`YOUR_PROJECT.nayose`.whole_number(`YOUR_PROJECT.nayose`.cut_short_marked(`YOUR_PROJECT.nayose`.null_token_marked(`YOUR_PROJECT.nayose`.without_controls(`YOUR_PROJECT.nayose`.unlisted(v)), null_regex), numeric), numeric),
         CHR(1))
);



-- ---------- 2. The comparisons ----------

-- `YOUR_PROJECT.nayose`.cut_from(t) is a hair under a similarity's threshold t, where a cl_*_cut keeps a score (engines.py's cut twin): a
-- bound tested against it keeps every score that passes t, as rapidfuzz's scores are float32.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.cut_from(t FLOAT64) AS (t - CAST(0.000001 AS FLOAT64));


-- jaro_winkler_of returns the Jaro–Winkler score of a and b, exact at the threshold or above: below it, the score may
-- be returned as 0 instead. It scores their one-byte copies (records.sql) if both have one. The score is the same,
-- because Jaro–Winkler tests characters only for equality, and a copy keeps different characters different. On the
-- copies, DuckDB computes the score with its own function.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.jaro_winkler_of(a STRING, b STRING, one_byte_a STRING, one_byte_b STRING,
                                                threshold FLOAT64) RETURNS FLOAT64 AS (
  IF(one_byte_a IS NOT NULL AND one_byte_b IS NOT NULL, `YOUR_PROJECT.nayose`.cl_jaro_winkler_cut(one_byte_a, one_byte_b, threshold),
     `YOUR_PROJECT.nayose`.cl_jaro_winkler_cut(a, b, threshold))
);


-- The next eight functions bound a Jaro–Winkler score from above: if a bound is below a threshold, so is the score.
-- winkler's and jaro_most's parameters are ANY TYPE, as read_value's steps' are, because their arguments nest.
-- common_start returns the number of leading characters that two strings share, up to 4.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.common_start(a STRING, b STRING) AS (
  IF(LEFT(a, 1) = LEFT(b, 1),
     IF(LEFT(a, 2) = LEFT(b, 2), IF(LEFT(a, 3) = LEFT(b, 3), IF(LEFT(a, 4) = LEFT(b, 4), 4, 3), 2), 1),
     0)
);


-- winkler raises a Jaro score by a common start of up to 4 characters, as 1 - (1 - jaro)(1 - 0.1 · start).
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.winkler(jaro ANY TYPE, start ANY TYPE) AS (
  1 - (1 - jaro) * (1 - CAST(0.1 AS FLOAT64) * start)
);


-- jaro_most returns the Jaro score of two strings of lengths a and b if `matches` of their characters match and none
-- is transposed: (matches/a + matches/b + 1)/3.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.jaro_most(matches ANY TYPE, a ANY TYPE, b ANY TYPE) AS (
  (matches * (1 / a + 1 / b) + 1) / 3
);


-- jaro_winkler_most returns an upper bound of two strings' Jaro–Winkler score, from their lengths and common start
-- alone. Jaro is at most (2 + r)/3, with r the shorter length divided by the longer. Jaro reaches that bound if every
-- character of the shorter string matches, in order.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.jaro_winkler_most(a STRING, b STRING) AS (
  `YOUR_PROJECT.nayose`.winkler((2 + LEAST(LENGTH(a), LENGTH(b)) / GREATEST(LENGTH(a), LENGTH(b), 1)) / 3, `YOUR_PROJECT.nayose`.common_start(a, b))
);


-- letter_count returns how many distinct katakana a name holds: the 1s in its letters columns' masks (records.sql).
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.letter_count(x ANY TYPE) AS (
  BIT_COUNT(x.person_name__kana_fold_letters_lo) + BIT_COUNT(x.person_name__kana_fold_letters_hi)
);


-- letters_shared returns how many distinct katakana both names hold: the 1s both names' letters masks share.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.letters_shared(x ANY TYPE, y ANY TYPE) AS (
  BIT_COUNT(x.person_name__kana_fold_letters_lo & y.person_name__kana_fold_letters_lo)
  + BIT_COUNT(x.person_name__kana_fold_letters_hi & y.person_name__kana_fold_letters_hi)
);


-- matches_most returns the most matches Jaro can find between two katakana names. Jaro's matches pair equal letters,
-- so a pair has no more matches than the letters both names hold, each counted as often as the name that holds it
-- fewer times. So the bound is the distinct letters both names hold, plus the smaller of the two names' repeats, and
-- no more than the shorter name's length. A name's repeats are its length less its distinct letters.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.matches_most(x ANY TYPE, y ANY TYPE) AS (
  LEAST(`YOUR_PROJECT.nayose`.letters_shared(x, y) + LEAST(LENGTH(x.person_name__kana_fold_one_byte) - `YOUR_PROJECT.nayose`.letter_count(x),
                                     LENGTH(y.person_name__kana_fold_one_byte) - `YOUR_PROJECT.nayose`.letter_count(y)),
        LENGTH(x.person_name__kana_fold_one_byte), LENGTH(y.person_name__kana_fold_one_byte))
);


-- name_jw_most returns an upper bound of two names' Jaro–Winkler score. If both names are katakana (both have one-byte
-- copies), the bound is the Jaro of matches_most's matches, which is tighter than jaro_winkler_most's, raised by the
-- common start. If either name isn't katakana, the bound is jaro_winkler_most's, from the lengths alone.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.name_jw_most(x ANY TYPE, y ANY TYPE) AS (
  IF(x.person_name__kana_fold_one_byte IS NULL OR y.person_name__kana_fold_one_byte IS NULL,
     `YOUR_PROJECT.nayose`.jaro_winkler_most(x.person_name__kana_fold, y.person_name__kana_fold),
     `YOUR_PROJECT.nayose`.winkler(`YOUR_PROJECT.nayose`.jaro_most(`YOUR_PROJECT.nayose`.matches_most(x, y), LENGTH(x.person_name__kana_fold_one_byte),
                       LENGTH(y.person_name__kana_fold_one_byte)),
             `YOUR_PROJECT.nayose`.common_start(x.person_name__kana_fold, y.person_name__kana_fold)))
);


-- The comparison name tests the person's names as written, then folded (kana_fold), then as read (long_vowel), and last
-- by the folded names' Jaro–Winkler score. It takes two functions, so that Jaro–Winkler is called once a pair.
-- name_score returns the folded names' score, exact from 0.75 up. Below 0.75 it may return 0 instead. It returns NULL
-- if an equality settles the level. The caller computes it once, as the column s_name, and name_level then reads the
-- level from it. name_jw_most's bound is tested against `YOUR_PROJECT.nayose`.cut_from(0.75), as the cl_* cut tests a score.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.name_score(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.person_name IS NULL OR y.person_name IS NULL OR x.person_name = y.person_name
      OR x.person_name__kana_fold = y.person_name__kana_fold
      OR x.person_name__kana_fold_long_vowel = y.person_name__kana_fold_long_vowel THEN NULL
    WHEN `YOUR_PROJECT.nayose`.name_jw_most(x, y) < `YOUR_PROJECT.nayose`.cut_from(CAST(0.75 AS FLOAT64)) THEN CAST(0 AS FLOAT64)  -- the bound rules out 0.75
    ELSE `YOUR_PROJECT.nayose`.jaro_winkler_of(x.person_name__kana_fold, y.person_name__kana_fold, x.person_name__kana_fold_one_byte,
                         y.person_name__kana_fold_one_byte, CAST(0.75 AS FLOAT64))
  END
);


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.name_level(x ANY TYPE, y ANY TYPE, s FLOAT64) AS (
  CASE
    WHEN x.person_name IS NULL OR y.person_name IS NULL THEN -1
    WHEN x.person_name = y.person_name THEN 6                                                -- exact
    WHEN x.person_name__kana_fold = y.person_name__kana_fold THEN 5                          -- fold exact
    WHEN x.person_name__kana_fold_long_vowel = y.person_name__kana_fold_long_vowel THEN 4    -- same reading
    WHEN s >= CAST(0.95 AS FLOAT64) THEN 3                                                   -- fold JW high
    WHEN x.given_name__kana_fold = y.given_name__kana_fold THEN 2                            -- given name
    WHEN s >= CAST(0.75 AS FLOAT64) THEN 1                                                   -- fold JW low
    ELSE 0
  END
);


-- The comparison company tests the companies' names in NFKC form, with their legal forms removed, and folded (the
-- column company_name__nfkc_strip_legal_form_kana_fold). A name that is a legal form alone is missing.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.gamma_company(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.company_name__nfkc_strip_legal_form_kana_fold IS NULL
      OR y.company_name__nfkc_strip_legal_form_kana_fold IS NULL THEN -1  -- missing
    WHEN x.company_name__nfkc_strip_legal_form_kana_fold = y.company_name__nfkc_strip_legal_form_kana_fold
      THEN 2  -- exact
    WHEN `YOUR_PROJECT.nayose`.jaro_winkler_of(x.company_name__nfkc_strip_legal_form_kana_fold,
                         y.company_name__nfkc_strip_legal_form_kana_fold,
                         x.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                         y.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                         CAST(0.8 AS FLOAT64)) >= CAST(0.8 AS FLOAT64) THEN 1  -- JW low
    ELSE 0
  END
);


-- address_close is TRUE if two addresses are two edits apart at most (Levenshtein). The costliest test runs last.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.address_close(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.address__address IS NULL OR y.address__address IS NULL
      OR ABS(LENGTH(x.address__address) - LENGTH(y.address__address)) > 2 THEN FALSE
    WHEN x.address__address_one_byte_hash IS NULL OR y.address__address_one_byte_hash IS NULL
      THEN `YOUR_PROJECT.nayose`.cl_levenshtein_cut(x.address__address, y.address__address, 2) <= 2
    WHEN `YOUR_PROJECT.nayose`.cl_levenshtein_cut(x.address__address_one_byte_hash, y.address__address_one_byte_hash, 2) > 2 THEN FALSE
    ELSE `YOUR_PROJECT.nayose`.cl_levenshtein_cut(x.address__address, y.address__address, 2) <= 2
  END
);


-- The comparison address is missing only if the address code, the address and the postal code are each missing on
-- one side or both. The address is the one compared (address__address), so a prefecture alone is missing.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.gamma_address(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN (x.address_code IS NULL OR y.address_code IS NULL)
      AND (x.address__address IS NULL OR y.address__address IS NULL)
      AND (x.postal_code IS NULL OR y.postal_code IS NULL) THEN -1
    WHEN x.address_code = y.address_code OR x.address__address = y.address__address THEN 3          -- same address
    WHEN `YOUR_PROJECT.nayose`.address_close(x, y) THEN 2                                                                  -- address close
    WHEN x.postal_code = y.postal_code THEN 1                                                        -- same postal
    ELSE 0
  END
);


-- padded writes each one-digit part of a value with a leading zero, where a separator or the end follows it:
-- 1990/1/2 becomes 1990/01/02. Twice, as one pass leaves a part whose separator before it the last match took.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.padded(x STRING) AS (
  REGEXP_REPLACE(REGEXP_REPLACE(x, r'([^0-9])([0-9])([^0-9]|$)', r'\10\2\3'), r'([^0-9])([0-9])([^0-9]|$)', r'\10\2\3')
);


-- may_be_one_edit is TRUE if a and b may be one edit apart. One edit (a character changed, added or dropped, or two
-- neighbours swapped) changes the length by one at most, and leaves whole either the first h characters or the last h,
-- with h = ⌊(the shorter length − 1)/2⌋. So two values one edit apart differ in length by one at most, and share
-- their first h characters or their last h. The test uses lengths and string equalities alone, so an edit distance
-- is computed only for a pair that passes it. Two random 13-digit IDs rarely pass.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.may_be_one_edit(a STRING, b STRING) AS (
  ABS(LENGTH(a) - LENGTH(b)) <= 1
  AND (LEFT(a, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)) = LEFT(b, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2))
       OR RIGHT(a, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)) = RIGHT(b, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)))
);


-- The comparisons phone, cif and birth are exact, or one digit off. phone measures that by Hamming distance, which
-- pads the shorter value at its end. cif and birth use Damerau–Levenshtein, which also counts two swapped neighbours
-- as one edit. Each test has its own CASE branch, because both engines try a CASE's branches in order. So the
-- distance is computed only if the cheaper tests don't settle the level.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.gamma_phone(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.phone IS NULL OR y.phone IS NULL THEN -1
    WHEN x.phone = y.phone THEN 2                                                                      -- exact
    WHEN NOT `YOUR_PROJECT.nayose`.may_be_one_edit(x.phone, y.phone) THEN 0
    WHEN `YOUR_PROJECT.nayose`.cl_hamming_cut(x.phone, y.phone, 1) <= 1 THEN 1                                               -- one digit off
    ELSE 0
  END
);


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.gamma_cif(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.customer_id IS NULL OR y.customer_id IS NULL THEN -1
    WHEN x.customer_id = y.customer_id THEN 2                                                          -- exact
    WHEN NOT `YOUR_PROJECT.nayose`.may_be_one_edit(x.customer_id, y.customer_id) THEN 0
    WHEN `YOUR_PROJECT.nayose`.cl_damerau_levenshtein_cut(x.customer_id, y.customer_id, 1) <= 1 THEN 1                      -- one digit off
    ELSE 0
  END
);


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.gamma_birth(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.birth_date IS NULL OR y.birth_date IS NULL THEN -1
    WHEN x.birth_date = y.birth_date THEN 2                                                            -- exact
    WHEN NOT `YOUR_PROJECT.nayose`.may_be_one_edit(x.birth_date, y.birth_date) THEN 0
    WHEN `YOUR_PROJECT.nayose`.cl_damerau_levenshtein_cut(x.birth_date, y.birth_date, 1) <= 1 THEN 1                        -- one digit off
    ELSE 0
  END
);



-- ---------- 3. The rules' fuzzy tests (score.sql) ----------

-- near_name is TRUE if two persons' folded names are at most two edits apart (Damerau–Levenshtein). near_company is
-- TRUE if two companies' names are at most one edit apart (Levenshtein). near_address is TRUE if two addresses score
-- 0.9 or more by Jaro–Winkler, and near_phone if two phones are one digit off (Hamming). Each tests equality first,
-- then the lengths (near_address skips them), and calls the distance last. near_name and near_company compare the
-- one-byte copies if both values have one. Each test has its own CASE branch, so the distance is computed only if the
-- cheaper tests don't settle the answer.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.near_name(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.person_name__kana_fold IS NULL OR y.person_name__kana_fold IS NULL THEN FALSE
    WHEN x.person_name__kana_fold = y.person_name__kana_fold THEN TRUE
    WHEN ABS(LENGTH(x.person_name__kana_fold) - LENGTH(y.person_name__kana_fold)) > 2 THEN FALSE
    ELSE IF(x.person_name__kana_fold_one_byte IS NOT NULL AND y.person_name__kana_fold_one_byte IS NOT NULL,
            `YOUR_PROJECT.nayose`.cl_damerau_levenshtein_cut(x.person_name__kana_fold_one_byte, y.person_name__kana_fold_one_byte, 2),
            `YOUR_PROJECT.nayose`.cl_damerau_levenshtein_cut(x.person_name__kana_fold, y.person_name__kana_fold, 2)) <= 2
  END
);


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.near_company(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.company_name__nfkc_strip_legal_form_kana_fold IS NULL
      OR y.company_name__nfkc_strip_legal_form_kana_fold IS NULL THEN FALSE
    WHEN x.company_name__nfkc_strip_legal_form_kana_fold = y.company_name__nfkc_strip_legal_form_kana_fold THEN TRUE
    WHEN ABS(LENGTH(x.company_name__nfkc_strip_legal_form_kana_fold)
             - LENGTH(y.company_name__nfkc_strip_legal_form_kana_fold)) > 1 THEN FALSE
    ELSE IF(x.company_name__nfkc_strip_legal_form_kana_fold_one_byte IS NOT NULL
              AND y.company_name__nfkc_strip_legal_form_kana_fold_one_byte IS NOT NULL,
            `YOUR_PROJECT.nayose`.cl_levenshtein_cut(x.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                               y.company_name__nfkc_strip_legal_form_kana_fold_one_byte, 1),
            `YOUR_PROJECT.nayose`.cl_levenshtein_cut(x.company_name__nfkc_strip_legal_form_kana_fold,
                               y.company_name__nfkc_strip_legal_form_kana_fold, 1)) <= 1
  END
);


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.near_address(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.address__address IS NULL OR y.address__address IS NULL THEN FALSE
    WHEN x.address__address = y.address__address THEN TRUE
    ELSE `YOUR_PROJECT.nayose`.cl_jaro_winkler_cut(x.address__address, y.address__address, CAST(0.9 AS FLOAT64)) >= CAST(0.9 AS FLOAT64)
  END
);


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.near_phone(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.phone IS NULL OR y.phone IS NULL THEN FALSE
    WHEN x.phone = y.phone THEN TRUE
    WHEN NOT `YOUR_PROJECT.nayose`.may_be_one_edit(x.phone, y.phone) THEN FALSE
    ELSE `YOUR_PROJECT.nayose`.cl_hamming_cut(x.phone, y.phone, 1) <= 1
  END
);



-- ---------- 4. The steps that the stages share ----------

-- `YOUR_PROJECT.nayose`.pairs_of(n) returns the number of pairs that n records make, n(n − 1)/2.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.pairs_of(n INT64) AS (DIV(n * (n - 1), 2));


-- The address copy's steps (records.sql), on an address in NFKC form. numbers_dashed writes 丁目, 番 or 番地 after a
-- number as a dash, and drops 号 after a number. up_to_street_number keeps the address up to the first space after
-- the street number, which drops the building and room.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.numbers_dashed(a STRING) AS (
  REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(a, r'(\d+)丁目', r'\1-'), r'(\d+)番地?', r'\1-'), r'(\d+)号', r'\1')
);


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.up_to_street_number(a STRING) AS (REGEXP_REPLACE(a, r'^(.*?[0-9][^ ]*) .*$', r'\1'));


-- records_for_pairs returns how many records make about max_pairs pairs. k records make k(k−1)/2 pairs, so about
-- max_pairs pairs take k = (√(8·max_pairs + 1) + 1) / 2 records.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.records_for_pairs(max_pairs FLOAT64) AS (
  CAST(0.5 AS FLOAT64) * (SQRT(8 * max_pairs + 1) + 1)
);



-- 3. The model's bits, as a score reads them. level_bits holds the prior and, for each comparison, an array of
--    its levels' bits. Level γ's bits are at OFFSET(γ + 1), so the missing level, -1, is at OFFSET(0) and weighs 0.
--    points_of gives a pair's points, the prior plus its levels' bits, added in the model's order. bound_of gives an
--    upper bound of a pair's points from cheap tests alone.
--    Each array lists the model's levels in order of gamma, so OFFSET(γ + 1) is level γ only if model holds every
--    gamma of the comparison from 0 up, without a gap. It does: fit.sql writes a row for each of functions.sql's
--    levels.
-- lambda_cap is the most the rescaled λ can be, a hair under 1, so that its log-odds stay finite (em.py's LAMBDA_CAP).
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.lambda_cap() AS (1 - CAST(0.000000001 AS FLOAT64));


-- bits_at returns level gamma's bits from one of level_bits' arrays, as functions.sql numbers the levels. A missing
-- side (level -1) is at OFFSET(0) and weighs 0. gamma is ANY TYPE, as is could_reach's bound, because DuckDB binds a
-- typed parameter's argument twice, and these arguments are whole comparisons.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.bits_at(levels ANY TYPE, gamma ANY TYPE) AS (levels[OFFSET(gamma + 1)]);


-- points_of's level parameters are gamma_name, gamma_company and so on, not the names of w's fields (name,
-- company…), because DuckDB would substitute a parameter into a field of the same name too.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.points_of(gamma_name INT64, gamma_company INT64, gamma_address INT64, gamma_phone INT64,
                                          gamma_cif INT64, gamma_birth INT64, w ANY TYPE) AS (
  w.prior_bits + `YOUR_PROJECT.nayose`.bits_at(w.name, gamma_name) + `YOUR_PROJECT.nayose`.bits_at(w.company, gamma_company) + `YOUR_PROJECT.nayose`.bits_at(w.address, gamma_address)
  + `YOUR_PROJECT.nayose`.bits_at(w.phone, gamma_phone) + `YOUR_PROJECT.nayose`.bits_at(w.cif, gamma_cif) + `YOUR_PROJECT.nayose`.bits_at(w.birth, gamma_birth)
);


-- probability_of turns a pair's points (its log2 odds) into its match probability, 1 / (1 + 2^-points). It takes two
-- forms so that POWER never gets a large argument, which BigQuery refuses as an overflow.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.probability_of(points FLOAT64) AS (
  CASE WHEN points >= 0 THEN CAST(1 AS FLOAT64) / (CAST(1 AS FLOAT64) + POWER(CAST(2 AS FLOAT64), -points))
       ELSE POWER(CAST(2 AS FLOAT64), points) / (CAST(1 AS FLOAT64) + POWER(CAST(2 AS FLOAT64), points))
  END
);


-- The next four functions give an upper bound of a pair's points from cheap tests alone: equalities, lengths, the
-- names' letters and the cheap comparisons' own levels. If a leading equality settles a fuzzy comparison's level, the
-- bound takes that level. Otherwise it takes the best level the comparison can still reach. A Jaro–Winkler level
-- counts only if name_jw_most or jaro_winkler_most, the most the score can be, reaches cut_from of its threshold,
-- as a cl_* cut does. No pair that the bound rules out could reach the floor it is tested against, so the costly
-- comparisons run only on the pairs it keeps.
-- name_bound takes the given name's level if the given names are equal (else the else level), or the best
-- Jaro–Winkler level that the names' letters still allow, whichever is higher.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.name_bound(x ANY TYPE, y ANY TYPE, w ANY TYPE) AS (
  CASE WHEN x.person_name IS NULL OR y.person_name IS NULL THEN `YOUR_PROJECT.nayose`.bits_at(w.name, -1)
       WHEN x.person_name = y.person_name THEN `YOUR_PROJECT.nayose`.bits_at(w.name, 6)                                     -- exact
       WHEN x.person_name__kana_fold = y.person_name__kana_fold THEN `YOUR_PROJECT.nayose`.bits_at(w.name, 5)               -- fold exact
       WHEN x.person_name__kana_fold_long_vowel = y.person_name__kana_fold_long_vowel
         THEN `YOUR_PROJECT.nayose`.bits_at(w.name, 4)                                                                      -- same reading
       WHEN x.person_name__kana_fold IS NULL OR y.person_name__kana_fold IS NULL THEN w.name_after
       ELSE GREATEST(IF(x.given_name__kana_fold = y.given_name__kana_fold, `YOUR_PROJECT.nayose`.bits_at(w.name, 2), `YOUR_PROJECT.nayose`.bits_at(w.name, 0)),
                     CASE WHEN `YOUR_PROJECT.nayose`.name_jw_most(x, y) < `YOUR_PROJECT.nayose`.cut_from(CAST(0.75 AS FLOAT64))
                            THEN `YOUR_PROJECT.nayose`.bits_at(w.name, 0)  -- most pairs stop here, so name_jw_most runs once for them
                          WHEN `YOUR_PROJECT.nayose`.name_jw_most(x, y) < `YOUR_PROJECT.nayose`.cut_from(CAST(0.95 AS FLOAT64))
                            THEN GREATEST(`YOUR_PROJECT.nayose`.bits_at(w.name, 0), `YOUR_PROJECT.nayose`.bits_at(w.name, 1))  -- else, fold JW low
                          ELSE GREATEST(`YOUR_PROJECT.nayose`.bits_at(w.name, 0), `YOUR_PROJECT.nayose`.bits_at(w.name, 1), `YOUR_PROJECT.nayose`.bits_at(w.name, 3))  -- and JW high
                     END)
  END
);


-- company_bound takes the company's JW low level only if jaro_winkler_most allows it.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.company_bound(x ANY TYPE, y ANY TYPE, w ANY TYPE) AS (
  CASE WHEN x.company_name__nfkc_strip_legal_form_kana_fold IS NULL
            OR y.company_name__nfkc_strip_legal_form_kana_fold IS NULL
         THEN `YOUR_PROJECT.nayose`.bits_at(w.company, -1)                                                                  -- missing
       WHEN x.company_name__nfkc_strip_legal_form_kana_fold = y.company_name__nfkc_strip_legal_form_kana_fold
         THEN `YOUR_PROJECT.nayose`.bits_at(w.company, 2)                                                                   -- exact
       WHEN `YOUR_PROJECT.nayose`.jaro_winkler_most(x.company_name__nfkc_strip_legal_form_kana_fold,
                              y.company_name__nfkc_strip_legal_form_kana_fold)
            >= `YOUR_PROJECT.nayose`.cut_from(CAST(0.8 AS FLOAT64)) THEN w.company_after
       ELSE `YOUR_PROJECT.nayose`.bits_at(w.company, 0)                                                                     -- else
  END
);


-- address_bound takes "address close" only if the two addresses' lengths differ by two characters or less, and "same
-- postal" only if the postal codes are equal.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.address_bound(x ANY TYPE, y ANY TYPE, w ANY TYPE) AS (
  CASE WHEN (x.address_code IS NULL OR y.address_code IS NULL)
            AND (x.address__address IS NULL OR y.address__address IS NULL)
            AND (x.postal_code IS NULL OR y.postal_code IS NULL) THEN `YOUR_PROJECT.nayose`.bits_at(w.address, -1)
       WHEN x.address_code = y.address_code OR x.address__address = y.address__address
         THEN `YOUR_PROJECT.nayose`.bits_at(w.address, 3)                                                                   -- same address
       ELSE GREATEST(`YOUR_PROJECT.nayose`.bits_at(w.address, 0),                                                           -- else
                     IF(x.address__address IS NOT NULL AND y.address__address IS NOT NULL
                        AND ABS(LENGTH(x.address__address) - LENGTH(y.address__address)) <= 2,
                        `YOUR_PROJECT.nayose`.bits_at(w.address, 2), `YOUR_PROJECT.nayose`.bits_at(w.address, 0)),                                -- address close
                     IF(x.postal_code = y.postal_code, `YOUR_PROJECT.nayose`.bits_at(w.address, 1), `YOUR_PROJECT.nayose`.bits_at(w.address, 0)))  -- same postal
  END
);


-- bound_of adds the prior and each comparison's bound in the model's order, as points_of adds a pair's points. The
-- cheap comparisons (phone, cif and birth) take their own level.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.bound_of(x ANY TYPE, y ANY TYPE, w ANY TYPE) AS (
  w.prior_bits + `YOUR_PROJECT.nayose`.name_bound(x, y, w) + `YOUR_PROJECT.nayose`.company_bound(x, y, w) + `YOUR_PROJECT.nayose`.address_bound(x, y, w)
  + `YOUR_PROJECT.nayose`.bits_at(w.phone, `YOUR_PROJECT.nayose`.gamma_phone(x, y)) + `YOUR_PROJECT.nayose`.bits_at(w.cif, `YOUR_PROJECT.nayose`.gamma_cif(x, y)) + `YOUR_PROJECT.nayose`.bits_at(w.birth, `YOUR_PROJECT.nayose`.gamma_birth(x, y))
);


-- could_reach is TRUE if a pair whose points are at most bound could reach floor. bound_of adds its bits in
-- points_of's order, each at least the pair's own level's, so rounding never leaves a pair's bound under its points.
-- rounding_margin, under the floor, keeps the test safe should the two orders ever part.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.rounding_margin() AS (CAST(0.000000001 AS FLOAT64));


CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.could_reach(bound ANY TYPE, floor ANY TYPE) AS (
  bound >= floor - `YOUR_PROJECT.nayose`.rounding_margin()
);

-- The match job. It makes one table of pairs for people to decide on, with the highest points first. The table holds
-- every pair the run scored at @threshold points or more, except the pairs whose latest decision is no_match.
-- Each row holds:
--   an empty decision, for people to fill in with match or no_match, and an empty why, for a reason if they like;
--   the pair, its points and its probability;
--   the rule that also joins the pair, if one does, and the generators whose keys listed it;
--   whether a name was compared (named), and whether the pair may be two people of one household;
--   both records' fields side by side, and each comparison's level with the bits it earned.
-- People give the filled table back to the decide job (decide.sql).
-- O(C) to scan scored, plus O(P·F) to join the P pairs kept to their records' F fields.
--
-- Reads: scored (score.sql), records, model (each level's label and bits), decisions (decide.sql).
-- Values: @threshold, in points. The job refuses a threshold below [score] keep_from, because the run keeps no pair
-- below that.
-- Writes: matched.


-- household marks a pair that may be two people of one household. Its records share an address code, an address or
-- a phone, and they differ in their given name (two edits or more), in the last three characters of their name's
-- reading (three edits or more) or in their birth date (two edits or more). A difference counts only if both sides
-- are filled. household is a label only, and it changes no score.
CREATE OR REPLACE FUNCTION `YOUR_PROJECT.nayose`.household(x ANY TYPE, y ANY TYPE) AS (
  COALESCE(x.address_code = y.address_code OR x.address__address = y.address__address OR x.phone = y.phone, FALSE)
  AND ((x.given_name__kana_fold IS NOT NULL AND y.given_name__kana_fold IS NOT NULL
        AND `YOUR_PROJECT.nayose`.cl_damerau_levenshtein_cut(x.given_name__kana_fold, y.given_name__kana_fold, 1) > 1)
    OR (x.person_name__kana_fold_long_vowel_last3 IS NOT NULL AND y.person_name__kana_fold_long_vowel_last3 IS NOT NULL
        AND `YOUR_PROJECT.nayose`.cl_damerau_levenshtein_cut(x.person_name__kana_fold_long_vowel_last3,
                                       y.person_name__kana_fold_long_vowel_last3, 2) > 2)
    OR (x.birth_date IS NOT NULL AND y.birth_date IS NOT NULL
        AND `YOUR_PROJECT.nayose`.cl_damerau_levenshtein_cut(x.birth_date, y.birth_date, 1) > 1))
);

CREATE OR REPLACE PROCEDURE `YOUR_PROJECT.nayose`.build() OPTIONS (strict_mode = FALSE)
BEGIN
DECLARE v_nulls STRING DEFAULT '^[ \\x{3000}]*(?:NULL|null|Null|\\\\N|NaN|nan|None|none|N/A|n/a|\\#N/A|\\-|－)[ \\x{3000}]*$|^[\\t-\\r\\x{1c}-\\x{20}\\x{85}\\x{a0}\\x{1680}\\x{2000}-\\x{200a}\\x{2028}\\x{2029}\\x{202f}\\x{205f}\\x{3000}]*$';
DECLARE v_hiragana STRING DEFAULT 'ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖ';
DECLARE v_katakana STRING DEFAULT 'ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶ';
DECLARE v_katakana_block STRING DEFAULT '゠ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶヷヸヹヺ・ーヽヾヿ';
DECLARE v_one_byte STRING DEFAULT '\U00000001\U00000002\U00000003\U00000004\U00000005\U00000006\U00000007\U00000008\U00000009\U0000000a\U0000000b\U0000000c\U0000000d\U0000000e\U0000000f\U00000010\U00000011\U00000012\U00000013\U00000014\U00000015\U00000016\U00000017\U00000018\U00000019\U0000001a\U0000001b\U0000001c\U0000001d\U0000001e\U0000001f !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`';
DECLARE v_kana_fold_from STRING DEFAULT 'ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポヴァィゥェォッャュョヮヵヶヲー';
DECLARE v_kana_fold_to STRING DEFAULT 'カキクケコサシスセソタチツテトハヒフヘホハヒフヘホフアイウエオツヤユヨワカケオウ';
DECLARE v_legal_regex STRING DEFAULT 'コクリツケンキュウカイハツホウジン|コクリツケンキユウカイハツホウジン|ユウゲンセキニンチュウカンホウジン|ユウゲンセキニンチユウカンホウジン|トクテイヒエイリカツドウホウジン|ムゲンセキニンチュウカンホウジン|ムゲンセキニンチユウカンホウジン|シャカイホケンロウムシホウジン|シヤカイホケンロウムシホウジン|ドクリツギョウセイホウジン|ドクリツギヨウセイホウジン|イッパンザイダンホウジン|イッパンシャダンホウジン|イツパンザイダンホウジン|イツパンシヤダンホウジン|イリョウホウジンザイダン|イリョウホウジンシャダン|イリヨウホウジンザイダン|イリヨウホウジンシヤダン|ギョウセイショシホウジン|ギヨウセイシヨシホウジン|コウエキザイダンホウジン|コウエキシャダンホウジン|コウエキシヤダンホウジン|コウリツダイガクホウジン|コクリツダイガクホウジン|カンリクミアイホウジン|シャカイフクシホウジン|シヤカイフクシホウジン|ノウジクミアイホウジン|コウセイホゴホウジン|シホウショシホウジン|シホウシヨシホウジン|シュウキョウホウジン|シユウキヨウホウジン|特定非営利活動法人|イリョウホウジン|イリヨウホウジン|カブシキガイシャ|カブシキガイシヤ|ガッコウホウジン|ガツコウホウジン|ゴウドウガイシャ|ゴウドウガイシヤ|ゴウメイガイシャ|ゴウメイガイシヤ|ゼイリシホウジン|ベンゴシホウジン|ユウゲンガイシャ|ユウゲンガイシヤ|ゴウシガイシャ|ゴウシガイシヤ|ソウゴガイシャ|ソウゴガイシヤ|一般社団法人|一般財団法人|公益社団法人|公益財団法人|医療法人社団|医療法人財団|社会福祉法人|\\(シホウ\\)|\\(ギヨ\\)|\\(ケン\\)|\\(ゼイ\\)|\\(ダイ\\)|\\(ノウ\\)|\\(ホゴ\\)|医療法人|合同会社|合名会社|合資会社|学校法人|宗教法人|有限会社|株式会社|相互会社|\\(カ\\)|\\(シ\\)|\\(ソ\\)|\\(ド\\)|\\(メ\\)|\\(ユ\\)|\\(同\\)|\\(名\\)|\\(有\\)|\\(株\\)|\\(資\\)|カ\\)|ユ\\)|^(?:シユウ|トクヒ|シホウ|チユウ|ザイ|シヤ|ガク|フク|ホゴ|ドク|ベン|ギヨ|ゼイ|ダイ|ノウ|ケン|カ|ユ|メ|シ|ド|ソ|イ)\\)|\\((?:シホウ|カンリ|ロウム|ギヨ|ゼイ|ダイ|ノウ|カ|ユ|メ|シ|ド|ソ|イ)$';
DECLARE v_prefecture_regex STRING DEFAULT '^(?:北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|埼玉県|千葉県|東京都|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)';
DECLARE v_flag_company ARRAY<STRING> DEFAULT ARRAY<STRING>['2'];
DECLARE v_name_line FLOAT64 DEFAULT CAST(0.99 AS FLOAT64);
DECLARE v_trust_flag BOOL DEFAULT FALSE;
DECLARE v_shared_name_column BOOL DEFAULT FALSE;
DECLARE v_ngram INT64 DEFAULT 3;
DECLARE v_intercept FLOAT64 DEFAULT CAST(3.2521136779937376 AS FLOAT64);
DECLARE v_placeholder_min INT64 DEFAULT 64;
DECLARE v_spread INT64 DEFAULT 10;
DECLARE v_crowd INT64 DEFAULT 64;
DECLARE v_lookup BOOL DEFAULT FALSE;
DECLARE v_fit_records INT64 DEFAULT 100000;
DECLARE v_seed STRING DEFAULT '0';
DECLARE v_fit_u_max_pairs FLOAT64 DEFAULT CAST(1000000.0 AS FLOAT64);
DECLARE v_u_max_pairs FLOAT64 DEFAULT CAST(10000000.0 AS FLOAT64);
DECLARE v_settings STRING DEFAULT '{"fit_records": 100000, "prior_recall": 0.0217, "fit_u_max_pairs": 1000000, "u_max_pairs": 10000000, "rebuild_after": 0.1, "seed": 0, "em_sessions": [{"field": "phone", "start": [["phone", "exact"]]}, {"field": "address", "start": []}]}';
DECLARE v_refit BOOL DEFAULT TRUE;
DECLARE v_generators ARRAY<STRING> DEFAULT ARRAY<STRING>['customer_id', 'phone_prefecture', 'phone_postal_area', 'phone_name_initial', 'person_name', 'company_name', 'company_name_deletions', 'person_name_deletions_postal_area', 'given_name_postal', 'address_phone', 'address_code_phone', 'address_name_initial', 'address_code_name_initial', 'given_name_address_code', 'customer_id_deletions', 'birth_date', 'given_name_phone', 'birth_date_deletions_prefecture', 'name_reading', 'phone_name_tail', 'postal_name_tail', 'postal_area_name_tail'];
DECLARE v_rules ARRAY<STRING> DEFAULT ARRAY<STRING>['X1_CIF_FULL_NAME', 'X2_CIF_COMPANY_NAME', 'X3_CIF_PHONE', 'X4_FULL_NAME_ADDRCD_PHONE', 'X5_COMPANY_NAME_ADDRCD_PHONE', 'F1_NAME~_ADDRCD_PHONE', 'F2_NAME~_ADDRESS~_PHONE', 'F3_NAME~_CIF', 'F4_NAME_ADDRCD_PHONE~', 'F5_COMPANY~_PHONE_POSTAL', 'F6_COMPANY~_ADDRCD_PHONE', 'X6_GIVEN_ADDRCD_PHONE'];
DECLARE v_keep_from FLOAT64 DEFAULT CAST(0.0 AS FLOAT64);
DECLARE v_search_floor FLOAT64 DEFAULT CAST(0.0 AS FLOAT64);
DECLARE v_oversized INT64 DEFAULT 64;
DECLARE v_outside INT64 DEFAULT 0;
DECLARE v_given BOOL DEFAULT FALSE;
DECLARE v_looks STRING DEFAULT '{"full_name": "^[ァ-ヴー・ｦ-ﾟ\\\\s\U00003000]+$", "person_name": "^[ァ-ヴー・ｦ-ﾟ\\\\s\U00003000]+$", "given_name": "^[ァ-ヴーｦ-ﾟ]{1,12}$", "any_name": "^[ァ-ヴー・ｦ-ﾟ\\\\s\U00003000()（）]+$", "address": "[都道府県市区町村].*[0-9０-９]", "address_code": "^[0-9]{5,}$", "postal_code": "^〒?[0-9０-９]{3}[-－]?[0-9０-９]{4}$", "prefecture": "^(北海道|東京都|京都府|大阪府|.{2,3}県)$", "town_code": "^[0-9]{11}$", "city": "[市区町村郡]$", "phone": "^[0-9]{4}$", "customer_id": "^[0-9]{8,}$", "birth_date": "^((19|20)?[0-9]{2})[-/.]?[01][0-9][-/.]?[0-3][0-9]$", "company_name": "コクリツケンキュウカイハツホウジン|コクリツケンキユウカイハツホウジン|ユウゲンセキニンチュウカンホウジン|ユウゲンセキニンチユウカンホウジン|トクテイヒエイリカツドウホウジン|ムゲンセキニンチュウカンホウジン|ムゲンセキニンチユウカンホウジン|シャカイホケンロウムシホウジン|シヤカイホケンロウムシホウジン|ドクリツギョウセイホウジン|ドクリツギヨウセイホウジン|イッパンザイダンホウジン|イッパンシャダンホウジン|イツパンザイダンホウジン|イツパンシヤダンホウジン|イリョウホウジンザイダン|イリョウホウジンシャダン|イリヨウホウジンザイダン|イリヨウホウジンシヤダン|ギョウセイショシホウジン|ギヨウセイシヨシホウジン|コウエキザイダンホウジン|コウエキシャダンホウジン|コウエキシヤダンホウジン|コウリツダイガクホウジン|コクリツダイガクホウジン|カンリクミアイホウジン|シャカイフクシホウジン|シヤカイフクシホウジン|ノウジクミアイホウジン|コウセイホゴホウジン|シホウショシホウジン|シホウシヨシホウジン|シュウキョウホウジン|シユウキヨウホウジン|特定非営利活動法人|イリョウホウジン|イリヨウホウジン|カブシキガイシャ|カブシキガイシヤ|ガッコウホウジン|ガツコウホウジン|ゴウドウガイシャ|ゴウドウガイシヤ|ゴウメイガイシャ|ゴウメイガイシヤ|ゼイリシホウジン|ベンゴシホウジン|ユウゲンガイシャ|ユウゲンガイシヤ|ゴウシガイシャ|ゴウシガイシヤ|ソウゴガイシャ|ソウゴガイシヤ|一般社団法人|一般財団法人|公益社団法人|公益財団法人|医療法人社団|医療法人財団|社会福祉法人|\\\\(シホウ\\\\)|\\\\(ギヨ\\\\)|\\\\(ケン\\\\)|\\\\(ゼイ\\\\)|\\\\(ダイ\\\\)|\\\\(ノウ\\\\)|\\\\(ホゴ\\\\)|医療法人|合同会社|合名会社|合資会社|学校法人|宗教法人|有限会社|株式会社|相互会社|\\\\(カ\\\\)|\\\\(シ\\\\)|\\\\(ソ\\\\)|\\\\(ド\\\\)|\\\\(メ\\\\)|\\\\(ユ\\\\)|\\\\(同\\\\)|\\\\(名\\\\)|\\\\(有\\\\)|\\\\(株\\\\)|\\\\(資\\\\)|カ\\\\)|ユ\\\\)|^(?:シユウ|トクヒ|シホウ|チユウ|ザイ|シヤ|ガク|フク|ホゴ|ドク|ベン|ギヨ|ゼイ|ダイ|ノウ|ケン|カ|ユ|メ|シ|ド|ソ|イ)\\\\)|\\\\((?:シホウ|カンリ|ロウム|ギヨ|ゼイ|ダイ|ノウ|カ|ユ|メ|シ|ド|ソ|イ)$"}';
DECLARE v_edges ARRAY<FLOAT64> DEFAULT ARRAY<FLOAT64>[CAST(-20.0 AS FLOAT64), CAST(-10.0 AS FLOAT64), CAST(0.0 AS FLOAT64), CAST(4.0 AS FLOAT64), CAST(6.0 AS FLOAT64), CAST(8.0 AS FLOAT64), CAST(10.0 AS FLOAT64), CAST(14.0 AS FLOAT64), CAST(18.0 AS FLOAT64)];
DECLARE v_floor FLOAT64 DEFAULT CAST(4.0 AS FLOAT64);
DECLARE v_sample_records INT64 DEFAULT 10000;
DECLARE v_patterns_shown INT64 DEFAULT 12;
DECLARE v_condition_1 BOOL DEFAULT FALSE;
DECLARE v_condition_2 BOOL DEFAULT FALSE;
DECLARE v_condition_3 BOOL DEFAULT FALSE;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.records;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.placeholders;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.set_aside;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.fit;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.model;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.rule_keys;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.every_key;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.cands;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.scored;
DROP TABLE IF EXISTS `YOUR_PROJECT.nayose`.gold;
-- This file maps the input's columns to the fields that records.sql reads. It is the mapping of the generated data,
-- whose columns design/generate.py writes. A deployment keeps its own mapping, in the same form, outside the
-- repository (in Secret Manager).
--
-- Every column is read through `YOUR_PROJECT.nayose`.read_value(functions.sql). It reads damaged values and null tokens (v_nulls, from
-- config.toml's [input] nulls) as missing, takes a list's first filled item and removes control characters. If its
-- second argument is TRUE, for a column of numbers, it also reads 12345.0 as 12345 and a number cut short in E
-- notation as missing.
-- A column that isn't text is cast to text first. A float column of codes, for example, is cast as
-- CAST(CAST(x AS INT64) AS STRING).
-- Each field takes the first of its sources, in order, whose columns are all filled. A source of two columns joins
-- them, as LAST_NAME_KANA || GIVEN_NAME_KANA does.
-- config.toml's [input] columns lists every column read here. A column that the file lacks is read as missing.

-- input_rows holds each distinct input row as the file gave it, with its ID read as mapped reads it (nayose_id).
-- records.sql sets aside rows from it as they were given, and counts its rows per ID to find an ID given with
-- different content.
CREATE OR REPLACE TEMP TABLE input_rows AS
SELECT DISTINCT `YOUR_PROJECT.nayose`.read_value(CONT_ID, TRUE, v_nulls) AS nayose_id, * FROM `YOUR_PROJECT.nayose.synthetic_records`;

CREATE OR REPLACE TEMP TABLE mapped AS
WITH source AS (
  SELECT
    `YOUR_PROJECT.nayose`.read_value(CONT_ID, TRUE, v_nulls)              AS id,
    `YOUR_PROJECT.nayose`.read_value(FULL_NAME_KANA, FALSE, v_nulls)      AS FULL_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(O_PERSON_NAME_KANA, FALSE, v_nulls)  AS O_PERSON_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(LAST_NAME_KANA, FALSE, v_nulls)      AS LAST_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(GIVEN_NAME_KANA, FALSE, v_nulls)     AS GIVEN_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(NYS_CNV_P_NAME_KANA, FALSE, v_nulls) AS NYS_CNV_P_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(STD_ADDRESS, FALSE, v_nulls)         AS STD_ADDRESS,
    `YOUR_PROJECT.nayose`.read_value(ORIGINAL_ADDRESS, FALSE, v_nulls)    AS ORIGINAL_ADDRESS,
    `YOUR_PROJECT.nayose`.read_value(SOURCE_ADDR_CD, TRUE, v_nulls)       AS SOURCE_ADDR_CD,
    `YOUR_PROJECT.nayose`.read_value(POST_CD, TRUE, v_nulls)              AS POST_CD,
    `YOUR_PROJECT.nayose`.read_value(POST_CD_KANA, TRUE, v_nulls)         AS POST_CD_KANA,
    `YOUR_PROJECT.nayose`.read_value(ADDRESS_ONE, FALSE, v_nulls)         AS ADDRESS_ONE,
    `YOUR_PROJECT.nayose`.read_value(ADDR_CD, TRUE, v_nulls)              AS ADDR_CD,
    `YOUR_PROJECT.nayose`.read_value(ADDRESS_TWO, FALSE, v_nulls)         AS ADDRESS_TWO,
    `YOUR_PROJECT.nayose`.read_value(PHONE_NUM_4, TRUE, v_nulls)          AS PHONE_NUM_4,
    `YOUR_PROJECT.nayose`.read_value(CIF_ID, TRUE, v_nulls)               AS CIF_ID,
    `YOUR_PROJECT.nayose`.read_value(BIRTH_DATE, TRUE, v_nulls)           AS BIRTH_DATE,
    `YOUR_PROJECT.nayose`.read_value(PERSON_ORG_CODE, TRUE, v_nulls)      AS PERSON_ORG_CODE
  FROM `YOUR_PROJECT.nayose.synthetic_records`
)
SELECT
  id,
  FULL_NAME_KANA AS full_name,
  COALESCE(FULL_NAME_KANA, O_PERSON_NAME_KANA, LAST_NAME_KANA || GIVEN_NAME_KANA) AS person_name,
  GIVEN_NAME_KANA AS given_name,
  NYS_CNV_P_NAME_KANA AS company_name,
  COALESCE(FULL_NAME_KANA, O_PERSON_NAME_KANA, LAST_NAME_KANA || GIVEN_NAME_KANA, NYS_CNV_P_NAME_KANA) AS any_name,
  COALESCE(STD_ADDRESS, ORIGINAL_ADDRESS) AS address,
  SOURCE_ADDR_CD AS address_code,
  COALESCE(POST_CD, POST_CD_KANA) AS postal_code,
  ADDRESS_ONE AS prefecture,
  ADDR_CD AS town_code,
  ADDRESS_TWO AS city,
  PHONE_NUM_4 AS phone,
  CIF_ID AS customer_id,
  BIRTH_DATE AS birth_date,
  PERSON_ORG_CODE AS kind_flag
FROM source;
-- This is stage 1, records. It adds a batch of input records to the run's records. It sets aside the rows it can't
-- resolve, standardizes each field, decides each record's kind (person or company) and reads placeholders as
-- missing. Then it writes each record with the copies of its fields that the keys and comparisons read. A build is
-- a run's first batch.
-- It costs O(Δ·L) for a batch of Δ records whose values are L characters long, plus O(N) to count placeholders over
-- all N of the run's records.
-- Sections 3 and 4 are one statement, sided: section 3's CTEs decide each record's kind, and section 4's then keep
-- each name in the fields of the record's side.
--
-- A statement that follows a `-- when: <condition>` line runs only if the condition holds: run_file checks it locally,
-- and the deployed procedure wraps the statement in IF … END IF.
--
-- Reads:
--   input_rows and mapped, the batch as mapping.sql maps it;
--   name_weights, the name model (config/kind_names.npz);
--   the run's records and placeholders, which are empty before the run's first batch.
-- Values: config.toml's [records], and the regexes that nayose builds from its lists (legal_regex,
--   prefecture_regex). With v_lookup, the batch holds the records asked about (nayose.lookup). They are prepared
--   as the run's own records are, but none of their values becomes a placeholder, and every table is written as a
--   temporary table.
-- Writes:
--   set_aside, the batch's rows that are set aside, each with its reason;
--   placeholders, the run's placeholders and the new ones this batch brings;
--   records, one row per record with its fields, its kind, its copies and its batch.


-- 0. The run's records and placeholders start empty. This batch's number is one more than the last batch's, or 0 for
--    the run's first.
CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.records (
  id STRING, given_name STRING, any_name STRING, address STRING, address_code STRING, postal_code STRING,
  prefecture STRING, town_code STRING, city STRING, phone STRING, customer_id STRING, birth_date STRING,
  kind INT64, kind_p FLOAT64, kind_by STRING, kind_flagged BOOL, full_name STRING, person_name STRING,
  company_name STRING, person_name__kana_fold STRING, company_name__nfkc_strip_legal_form_kana_fold STRING,
  address__address STRING, postal_code__first3 STRING, any_name__initial STRING, given_name__kana_fold STRING,
  address__address_first3 STRING,
  person_name__kana_fold_long_vowel STRING, person_name__kana_fold_one_byte STRING,
  company_name__nfkc_strip_legal_form_kana_fold_one_byte STRING, address__address_one_byte_hash STRING,
  person_name__kana_fold_long_vowel_last3 STRING, person_name__kana_fold_letters_lo INT64,
  person_name__kana_fold_letters_hi INT64, customer STRING, batch INT64
) CLUSTER BY id;  -- On BigQuery, a lookup by ID then reads only the blocks that hold those IDs.;

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.placeholders (field STRING, value STRING, n INT64);

CREATE OR REPLACE TEMP TABLE this_batch AS SELECT COALESCE(MAX(batch) + 1, 0) AS batch FROM `YOUR_PROJECT.nayose`.records;


-- 1. This section sets aside the rows that can't be resolved. Rows identical in every column count once (mapping.sql's
--    input_rows). A row is set aside if it has no ID, if its ID is already in the run, or if another row gives
--    its ID with different content. An ID that is empty or whitespace alone, as Python counts whitespace, is no ID.
--    Since an ID already in the run is set aside, a batch given twice adds no record the second time. Every row of
--    an ID with different content is set aside, because the run can't tell which row is right.
--    The list of IDs held twice leaves out a missing ID, because a NULL in a NOT IN list fails the test for every row.

CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.set_aside AS
SELECT * EXCEPT (nayose_id),
  CASE WHEN nayose_id IS NULL OR `YOUR_PROJECT.nayose`.blank(nayose_id) THEN 'no ID'
       WHEN nayose_id IN (SELECT id FROM `YOUR_PROJECT.nayose`.records) THEN 'already in the run'
       ELSE 'the same ID with different content' END AS reason
FROM input_rows
WHERE nayose_id IS NULL
   OR `YOUR_PROJECT.nayose`.blank(nayose_id)
   OR nayose_id IN (SELECT id FROM `YOUR_PROJECT.nayose`.records)
   OR nayose_id IN (SELECT nayose_id FROM input_rows WHERE nayose_id IS NOT NULL
                    GROUP BY nayose_id HAVING COUNT(*) > 1);


-- 2. Each field is standardized by its chain of steps, in order. A value that its chain leaves empty is missing.
--    nfkc applies Unicode NFKC normalization.
--    katakana writes hiragana as katakana (v_hiragana to v_katakana).
--    strip_spaces removes every space, of any width.
--    strip_separators removes what people write between digits, as in 03-1234-5678 or (03) 1234-5678. These are
--    spaces, hyphens, dashes, minus signs, the long-vowel mark ー, slashes, dots, parentheses and 〒.
--    padded writes a one-digit part between separators with a leading zero, so 1990/1/2 reads as 1990/01/02, and
--    1990/1/12 and 1990/11/2 stay apart once the separators go (birth_date).
--    strip_legal_form removes a legal form (v_legal_regex).
--    kana_fold writes voiced kana as unvoiced, small kana as large, and ー as ウ (v_kana_fold_from to v_kana_fold_to).

CREATE OR REPLACE TEMP TABLE standardized AS
WITH admitted AS (  -- Each record that isn't set aside is admitted once.
  SELECT DISTINCT m.*
  FROM mapped AS m
  WHERE m.id IS NOT NULL
    AND NOT `YOUR_PROJECT.nayose`.blank(m.id)
    AND m.id NOT IN (SELECT id FROM `YOUR_PROJECT.nayose`.records)
    AND m.id NOT IN (SELECT nayose_id FROM input_rows WHERE nayose_id IS NOT NULL
                     GROUP BY nayose_id HAVING COUNT(*) > 1)
)
SELECT
  id,
  NULLIF(REGEXP_REPLACE(TRANSLATE(`YOUR_PROJECT.nayose`.nfkc(full_name), v_hiragana, v_katakana), r'[\s\x{3000}]+', ''), '') AS full_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(`YOUR_PROJECT.nayose`.nfkc(person_name), v_hiragana, v_katakana), r'[\s\x{3000}]+', ''), '') AS person_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(`YOUR_PROJECT.nayose`.nfkc(given_name), v_hiragana, v_katakana), r'[\s\x{3000}]+', ''), '') AS given_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(`YOUR_PROJECT.nayose`.nfkc(company_name), v_hiragana, v_katakana), r'[\s\x{3000}]+', ''), '') AS company_name,
  NULLIF(TRANSLATE(REGEXP_REPLACE(TRANSLATE(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(any_name), r'[\s\x{3000}]+', ''), v_hiragana, v_katakana),
                                  v_legal_regex, ''), v_kana_fold_from, v_kana_fold_to), '') AS any_name,
  NULLIF(address, '') AS address,
  NULLIF(address_code, '') AS address_code,
  NULLIF(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(postal_code), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '') AS postal_code,
  NULLIF(prefecture, '') AS prefecture,
  NULLIF(town_code, '') AS town_code,
  NULLIF(city, '') AS city,
  NULLIF(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(phone), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '') AS phone,
  NULLIF(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(customer_id), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '') AS customer_id,
  NULLIF(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.padded(`YOUR_PROJECT.nayose`.nfkc(birth_date)), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '')
    AS birth_date,
  NULLIF(kind_flag, '') AS kind_flag,
  any_name AS kind_name  -- Section 3 looks for a legal form in this name as written.
FROM admitted;


-- sided holds each record once, with its kind (section 3) and its names in the fields of its side (section 4).
CREATE OR REPLACE TEMP TABLE sided AS
-- 3. Each record's kind is 2 for a company, 1 for a person, or 0 if neither the engine nor the file's flag decides.
--    A legal form written in the name makes the record a company.
--    Otherwise the name model decides if it is at least name_line sure either way. The model is a logistic regression
--    on the character n-grams of the name as any_name holds it, in lower case. A name that reads as a person's never
--    overrides a flag that says company.
--    Otherwise the file's flag (kind_flag) decides. A flag in flag_company says company, and any other says person.
--    With trust_flag, the flag decides every record.
--    So, with p the name model's chance that the name is a company's (name_p) and line v_name_line:
--      the name                                    the flag           kind                kind_by
--      a written legal form, or p ≥ line           any                2                   engine
--      p ≤ 1 − line                                company            2                   flag
--      p ≤ 1 − line                                person, or none    1                   engine
--      between, or no name to read                 company or person  the flag's, 2 or 1  flag
--      between, or no name to read                 none               0                   engine
--      any, with trust_flag                        company or person  the flag's, 2 or 1  flag
--      any, with trust_flag                        none               0                   engine
--    A record's side is its kind, or, if its kind is 0, the kind it leans to (kind_p).
-- name_sums scores each distinct name once, since many records share a name: one row per distinct name that holds an
-- n-gram the model knows. As in the model's training, each n-gram counts once however often the name holds it, and an
-- n-gram the model doesn't know adds nothing, so a name with none has no row here, and judged reads its sum as 0.
WITH name_sums AS (
  SELECT grams.t, SUM(nw.coef) AS s
  FROM (
    SELECT DISTINCT t, SUBSTR(t, i, n) AS term
    FROM (SELECT DISTINCT LOWER(any_name) AS t FROM standardized WHERE any_name IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, v_ngram)) AS n,
      UNNEST(GENERATE_ARRAY(1, LENGTH(t) - n + 1)) AS i
  ) AS grams
  JOIN `YOUR_PROJECT.nayose`.name_weights AS nw ON nw.term = grams.term
  GROUP BY grams.t
),
-- judged and each CTE after it hold one row per record. written is TRUE if the name as written holds a legal form.
-- logit is the name model's log-odds that the name is a company's. flag is the file's flag as a kind: 2 company,
-- 1 person, or NULL if the file gives none.
judged AS (
  SELECT
    s.*,
    COALESCE(REGEXP_CONTAINS(NULLIF(TRANSLATE(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(kind_name), r'[\s\x{3000}]+', ''), v_hiragana, v_katakana), ''),
                             v_legal_regex), FALSE) AS written,
    IF(s.any_name IS NULL, NULL, v_intercept + COALESCE(sums.s, CAST(0 AS FLOAT64))) AS logit,
    CASE WHEN s.kind_flag IS NULL THEN NULL
         WHEN `YOUR_PROJECT.nayose`.trimmed(`YOUR_PROJECT.nayose`.nfkc(s.kind_flag))
              IN UNNEST(v_flag_company) THEN 2
         ELSE 1 END AS flag
  FROM standardized AS s
  LEFT JOIN name_sums AS sums ON sums.t = LOWER(s.any_name)
),
name_chance AS (  -- name_p is the chance that the name is a company's, or NULL if the model can read no name.
  -- The logistic is 1 / (1 + EXP(-logit)). EXP overflows past about 709.78, which BigQuery refuses, so for a logit
  -- under -700 it takes the form EXP(logit) / (1 + EXP(logit)), equal but for rounding. Every other logit keeps the
  -- first form, to the bit.
  SELECT *, IF(written, CAST(1 AS FLOAT64),
               IF(logit >= -700, 1 / (1 + EXP(-logit)), EXP(logit) / (1 + EXP(logit)))) AS name_p
  FROM judged
),
sure AS (  -- sure_kind is the engine's kind if the engine is sure (2 company, 1 person), and 0 if it isn't.
  SELECT *,
    -- With v_trust_flag the engine is never sure, so the file's flag decides every record.
    CASE WHEN kind_name IS NULL OR v_trust_flag THEN 0
         WHEN (written OR name_p >= v_name_line) THEN 2
         WHEN name_p <= 1 - v_name_line AND flag = 2 THEN 0  -- A person's name never overrides a company flag.
         WHEN name_p <= 1 - v_name_line THEN 1
         ELSE 0 END AS sure_kind
  FROM name_chance
),
-- The kind is the engine's if the engine is sure, and the file's flag if it isn't. kind_p is how far the record
-- leans to company, from 0 to 1: name_p, or with v_trust_flag the flag's 1 or 0. It is NULL if the record has no name
-- to judge, or, with v_trust_flag, no flag.
decided AS (
  SELECT *,
    CAST(IF(sure_kind <> 0, sure_kind, COALESCE(flag, 0)) AS INT64) AS kind,
    IF(kind_name IS NULL, NULL, IF(v_trust_flag, CAST(flag - 1 AS FLOAT64), name_p)) AS kind_p
  FROM sure
),
told AS (  -- each record with its kind, kind_p, kind_by and kind_flagged, and its side
  SELECT
    * EXCEPT (kind_flag, kind_name, written, logit, flag, name_p, sure_kind),
    IF(sure_kind = 0 AND flag IS NOT NULL, 'flag', 'engine') AS kind_by,
    (sure_kind <> 0 AND flag IS NOT NULL AND sure_kind <> flag) AS kind_flagged,
    -- The side tells section 4 which fields keep a name.
    CASE WHEN kind = 2 THEN 'company'
         WHEN kind = 1 THEN 'person'
         WHEN kind_p >= CAST(0.5 AS FLOAT64) THEN 'company'
         ELSE 'person' END AS side
  FROM decided
),
-- 4. A name counts once, even if it is in two fields. If a person field and the company field hold the same name
--    once kana_fold is applied, as they do when one column is mapped to both, the name is one piece of evidence. It is
--    kept only in the field on the record's side.
--    With shared_name_column, one column holds every name, a person's or a company's. Then a person field keeps its
--    name only if the record's side is person, and the company field only if the side is company.
routed AS (
  SELECT
    * EXCEPT (full_name, person_name, company_name),
    IF(v_shared_name_column AND side <> 'person', NULL, full_name) AS full_name,
    IF(v_shared_name_column AND side <> 'person', NULL, person_name) AS person_name,
    IF(v_shared_name_column AND side <> 'company', NULL, company_name) AS company_name
  FROM told
),
same AS (
  SELECT *,
    COALESCE(NULLIF(TRANSLATE(full_name, v_kana_fold_from, v_kana_fold_to), '')
             = NULLIF(TRANSLATE(company_name, v_kana_fold_from, v_kana_fold_to), ''), FALSE) AS same_full,
    COALESCE(NULLIF(TRANSLATE(person_name, v_kana_fold_from, v_kana_fold_to), '')
             = NULLIF(TRANSLATE(company_name, v_kana_fold_from, v_kana_fold_to), ''), FALSE) AS same_person
  FROM routed
)
SELECT
  * EXCEPT (full_name, person_name, company_name, same_full, same_person),
  IF(same_full AND side = 'company', NULL, full_name) AS full_name,
  IF(same_person AND side = 'company', NULL, person_name) AS person_name,
  IF((same_full OR same_person) AND side = 'person', NULL, company_name) AS company_name
FROM same;


-- 5. A placeholder is a value held by so many records that it can't be one entity's, so it is no evidence. Every
--    placeholder is read as missing.
--    For person_name, company_name, address_code, address, phone and birth_date, a value is crowded if it reaches
--    the field's bar and at least v_crowd customers hold it. The bar is v_placeholder_min records, or v_spread times the
--    field's records per value if that is more. A crowded value is a placeholder if its own pairs outnumber the pairs
--    that all the field's uncrowded values make together. With n a value's records, C(n, 2) = n(n − 1)/2 its pairs,
--    and records / values the field's filled records over its distinct values:
--      placeholder ⇔ n ≥ max(v_placeholder_min, ⌈v_spread · records / values⌉) ∧ customers ≥ v_crowd
--                    ∧ C(n, 2) > Σ C(m, 2) over the field's uncrowded values, m each one's records
--    A customer ID is a placeholder if it reaches its field's bar, n ≥ max(…) alone. Its customers and pairs aren't
--    tested.
--    Blanking one field's placeholder changes no other field's record counts. A person_name placeholder also blanks
--    full_name, given_name and any_name, but those fields aren't counted. A record's customer is its customer ID as
--    read, or its own ID if it has none, and records keeps it (customer), so a customer ID blanked later counts as it
--    did. Every field's placeholders are then found at once, and section 6 blanks them as it writes the records.
--    The run's placeholders stay, and each keeps n, the records that hold it, the batch's added. An update counts as a
--    build of the same records would: the run's records are stored with its placeholders blanked, so each run
--    placeholder counts by its n, in its field's records per value and pairs, and as crowded if it reaches the bar.
--    (Its customers only grow, so it holds as many as it did when found.) So a batch given twice changes nothing.
--    A run placeholder stays one even where a build of the run's records would no longer find it. With v_lookup, no
--    placeholder is found and no count changes.
-- known keeps the run's placeholders from before this batch, since placeholders is replaced below.
CREATE OR REPLACE TEMP TABLE known AS SELECT * FROM `YOUR_PROJECT.nayose`.placeholders;

CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.placeholders AS
-- counted holds the run's records and the batch's, each with its customer ('c' and 'r' keep a customer ID and a
-- record ID apart). The run's records were written with the run's placeholders already blanked; the batch's are as
-- read. Each step below names the one before it once or twice, as BigQuery computes a WITH again where it is named.
WITH counted AS (
  SELECT id, person_name, company_name, address_code, address, phone, birth_date, customer_id, customer
  FROM `YOUR_PROJECT.nayose`.records WHERE NOT v_lookup
  UNION ALL
  SELECT id, person_name, company_name, address_code, address, phone, birth_date, customer_id,
         COALESCE('c' || customer_id, 'r' || id)
  FROM sided
),
field_values AS (  -- each record's value of each field, with its customer
  SELECT 'person_name' AS field, person_name AS value, customer FROM counted
  UNION ALL SELECT 'company_name', company_name, customer FROM counted
  UNION ALL SELECT 'address_code', address_code, customer FROM counted
  UNION ALL SELECT 'address', address, customer FROM counted
  UNION ALL SELECT 'phone', phone, customer FROM counted
  UNION ALL SELECT 'birth_date', birth_date, customer FROM counted
  UNION ALL SELECT 'customer_id', customer_id, NULL FROM counted
),
value_counts AS (  -- Each value's records (n) and customers are counted.
  SELECT field, value, COUNT(*) AS n, COUNT(DISTINCT customer) AS customers
  FROM field_values WHERE value IS NOT NULL GROUP BY field, value
),
-- valued holds every value and every run placeholder (held), n its records now: a run placeholder's before this
-- batch, and the batch's.
valued AS (
  SELECT COALESCE(v.field, k.field) AS field, COALESCE(v.value, k.value) AS value,
         IF(k.field IS NULL, v.n, k.n + IF(v_lookup, 0, COALESCE(v.n, 0))) AS n, v.customers, k.field IS NOT NULL AS held
  FROM value_counts AS v FULL JOIN known AS k ON k.field = v.field AND k.value = v.value
),
-- Each field gets its bar (at_least), from its records per value, and the number of pairs that all its values make
-- together (all_pairs). A value held by n records makes n(n-1)/2 pairs.
field_bars AS (
  SELECT field, GREATEST(v_placeholder_min, CAST(CEIL(v_spread * SUM(n) / GREATEST(COUNT(*), 1)) AS INT64)) AS at_least,
         SUM(`YOUR_PROJECT.nayose`.pairs_of(n)) AS all_pairs
  FROM valued GROUP BY field
),
-- A value is crowded if it reaches the bar and enough customers hold it; a customer ID, or a run placeholder, needs
-- only the bar.
flagged AS (
  SELECT v.field, v.value, v.n, v.held, b.all_pairs,
         v.n >= b.at_least AND (v.field = 'customer_id' OR v.held OR v.customers >= v_crowd) AS crowded
  FROM valued AS v JOIN field_bars AS b USING (field)
),
crowded_pairs AS (SELECT field, SUM(`YOUR_PROJECT.nayose`.pairs_of(n)) AS pairs FROM flagged WHERE crowded GROUP BY field)
-- Every run placeholder stays. A crowded value is a new placeholder if its own pairs outnumber those of all the
-- field's values that aren't crowded.
SELECT f.field, f.value, f.n FROM flagged AS f LEFT JOIN crowded_pairs AS p USING (field)
WHERE f.held
   OR (NOT v_lookup AND f.crowded AND (f.field = 'customer_id' OR `YOUR_PROJECT.nayose`.pairs_of(f.n) > f.all_pairs - p.pairs));

-- new_placeholders holds the placeholders this batch found.
CREATE OR REPLACE TEMP TABLE new_placeholders AS
SELECT p.field, p.value, p.n FROM `YOUR_PROJECT.nayose`.placeholders AS p LEFT JOIN known AS k ON k.field = p.field AND k.value = p.value
WHERE k.field IS NULL;
SET v_condition_1 = (EXISTS(SELECT 1 FROM new_placeholders));
IF v_condition_1 THEN

-- 6. The records are written with the copies of their fields that the keys and comparisons read. Each copy is a chain
--    of steps from a field, and is named field__steps, as person_name__kana_fold is. The batch's records are
--    written, and so is every run's record that holds a placeholder this batch found. That record is made again with
--    the placeholder read as missing, and so are its copies.
--    These are the steps section 2 doesn't list:
--    address applies NFKC, writes 丁目, 番 or 番地 after a number as a dash, and drops 号 after a number
--    (numbers_dashed, functions.sql). It then keeps the address up to the first space after the street number
--    (up_to_street_number), which drops the building and room. Last, it removes every space and cuts the address's
--    own prefecture off its start. So 東京都千代田区丸の内1丁目2番3号
--    ABCビル5F becomes 千代田区丸の内1-2-3.
--    first3 and last3 keep a value's first or last three characters, and initial keeps its first character.
--    long_vowel writes a long vowel one way, so サトウ, サトオ and サトー read alike (kana_fold has made ー into ウ).

-- redone holds the run's records that hold a placeholder this batch found: their fields, without their copies. The
-- INSERT below makes their copies again, with the batch's.
CREATE OR REPLACE TEMP TABLE redone AS
SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
       birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
       company_name, customer, batch
FROM `YOUR_PROJECT.nayose`.records
WHERE person_name IN (SELECT value FROM new_placeholders WHERE field = 'person_name')
   OR company_name IN (SELECT value FROM new_placeholders WHERE field = 'company_name')
   OR address_code IN (SELECT value FROM new_placeholders WHERE field = 'address_code')
   OR address IN (SELECT value FROM new_placeholders WHERE field = 'address')
   OR phone IN (SELECT value FROM new_placeholders WHERE field = 'phone')
   OR birth_date IN (SELECT value FROM new_placeholders WHERE field = 'birth_date')
   OR customer_id IN (SELECT value FROM new_placeholders WHERE field = 'customer_id');
END IF;
IF NOT v_condition_1 THEN

-- If the batch found no placeholder, redone is empty, with the same columns, and no record is made again.
CREATE OR REPLACE TEMP TABLE redone AS
SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
       birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
       company_name, customer, batch
FROM `YOUR_PROJECT.nayose`.records WHERE FALSE;
END IF;
IF EXISTS (SELECT 1 FROM redone) THEN

-- The records made again leave the table here, and the INSERT below writes them anew.
DELETE FROM `YOUR_PROJECT.nayose`.records WHERE id IN (SELECT id FROM redone);
END IF;

INSERT INTO `YOUR_PROJECT.nayose`.records
-- made holds the batch's records and the run's records made again, with their fields but not yet their copies.
WITH made AS (
  SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
         birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
         company_name, COALESCE('c' || customer_id, 'r' || id) AS customer, (SELECT batch FROM this_batch) AS batch
  FROM sided
  UNION ALL
  SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
         birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
         company_name, customer, batch
  FROM redone
),
-- marked holds the records of made, person_placeholder TRUE if a record's person_name is a placeholder and
-- company_placeholder TRUE if its company_name is.
marked AS (
  SELECT *,
    person_name IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'person_name') AS person_placeholder,
    company_name IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'company_name') AS company_placeholder
  FROM made
),
-- Every placeholder is read as missing. A person_name placeholder also blanks full_name, given_name and any_name,
-- since those fields come from the same columns. A company_name placeholder blanks any_name only where the record
-- has no person_name, as any_name is the person's name where there is one (mapping.sql).
blanked AS (
  SELECT * EXCEPT (person_placeholder, company_placeholder) REPLACE (
    IF(person_placeholder, NULL, full_name) AS full_name,
    IF(person_placeholder, NULL, given_name) AS given_name,
    IF(person_placeholder OR (company_placeholder AND person_name IS NULL), NULL, any_name) AS any_name,
    IF(person_placeholder, NULL, person_name) AS person_name,
    IF(company_placeholder, NULL, company_name) AS company_name,
    IF(address_code IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'address_code'), NULL, address_code) AS address_code,
    IF(address IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'address'), NULL, address) AS address,
    IF(phone IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'phone'), NULL, phone) AS phone,
    IF(birth_date IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'birth_date'), NULL, birth_date) AS birth_date,
    IF(customer_id IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'customer_id'), NULL, customer_id) AS customer_id)
  FROM marked
),
copies AS (
  SELECT
    *,
    NULLIF(TRANSLATE(person_name, v_kana_fold_from, v_kana_fold_to), '') AS person_name__kana_fold,
    NULLIF(TRANSLATE(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(company_name), v_legal_regex, ''), v_kana_fold_from, v_kana_fold_to), '')
      AS company_name__nfkc_strip_legal_form_kana_fold,
    NULLIF(REGEXP_REPLACE(REPLACE(`YOUR_PROJECT.nayose`.up_to_street_number(`YOUR_PROJECT.nayose`.trimmed(`YOUR_PROJECT.nayose`.numbers_dashed(`YOUR_PROJECT.nayose`.nfkc(address)))), ' ', ''),
                          v_prefecture_regex, ''), '') AS address__address,
    NULLIF(SUBSTR(postal_code, 1, 3), '') AS postal_code__first3,
    NULLIF(SUBSTR(any_name, 1, 1), '') AS any_name__initial,
    NULLIF(TRANSLATE(given_name, v_kana_fold_from, v_kana_fold_to), '') AS given_name__kana_fold
  FROM blanked
),
readings AS (
  SELECT
    *,
    NULLIF(SUBSTR(address__address, 1, 3), '') AS address__address_first3,
    NULLIF(REGEXP_REPLACE(REGEXP_REPLACE(person_name__kana_fold, r'([オコソトノホモヨロ])[ウオ]', r'\1ウ'),
                          r'([エケセテネヘメレ])[イエ]', r'\1イ'), '') AS person_name__kana_fold_long_vowel,
    -- one_byte is the copy that a similarity reads. It is NULL unless the value is katakana alone. Each katakana
    -- becomes a one-byte character of its own (v_one_byte), so DuckDB's own similarity functions, which count bytes,
    -- compare it character by character. BigQuery's JavaScript functions give the copy the same scores.
    IF(REGEXP_CONTAINS(person_name__kana_fold, r'^[\x{30a0}-\x{30ff}]+$'), TRANSLATE(person_name__kana_fold, v_katakana_block, v_one_byte), NULL)
      AS person_name__kana_fold_one_byte,
    IF(REGEXP_CONTAINS(company_name__nfkc_strip_legal_form_kana_fold, r'^[\x{30a0}-\x{30ff}]+$'),
       TRANSLATE(company_name__nfkc_strip_legal_form_kana_fold, v_katakana_block, v_one_byte), NULL)
      AS company_name__nfkc_strip_legal_form_kana_fold_one_byte,
    -- one_byte_hash is the copy that an edit distance reads. It is NULL if the value is ASCII alone, which needs no
    -- copy. Each character becomes one byte, chosen by its code point, and two characters may share a byte. So the
    -- copies are never farther apart than the values, and their distance, which DuckDB computes natively, is a cheap
    -- lower bound on the values' distance (functions.sql).
    IF(REGEXP_CONTAINS(address__address, r'[^\x00-\x7f]'), `YOUR_PROJECT.nayose`.one_byte_hash(address__address), NULL) AS address__address_one_byte_hash
  FROM copies
),
lettered AS (
  -- letters is the set of katakana a name holds, as two bit masks over its one-byte copy's codes. lo covers codes
  -- 1–63, and hi covers codes 64–96. One pass over the name makes both. `YOUR_PROJECT.nayose`.name_jw_most(functions.sql) bounds the
  -- Jaro–Winkler of two names with them.
  SELECT *, (SELECT STRUCT(COALESCE(BIT_OR(IF(UNICODE(c) < 64, CAST(1 AS INT64) << (UNICODE(c) - 1), 0)), 0) AS lo,
                           COALESCE(BIT_OR(IF(UNICODE(c) >= 64, CAST(1 AS INT64) << (UNICODE(c) - 64), 0)), 0) AS hi)
             FROM UNNEST(SPLIT(person_name__kana_fold_one_byte, '')) AS c) AS letters
  FROM readings
)
SELECT
  id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
  birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name, company_name,
  person_name__kana_fold, company_name__nfkc_strip_legal_form_kana_fold, address__address, postal_code__first3,
  any_name__initial, given_name__kana_fold, address__address_first3, person_name__kana_fold_long_vowel,
  person_name__kana_fold_one_byte, company_name__nfkc_strip_legal_form_kana_fold_one_byte,
  address__address_one_byte_hash,
  NULLIF(SUBSTR(person_name__kana_fold_long_vowel, -3), '') AS person_name__kana_fold_long_vowel_last3,
  IF(person_name__kana_fold_one_byte IS NULL, NULL, letters.lo) AS person_name__kana_fold_letters_lo,
  IF(person_name__kana_fold_one_byte IS NULL, NULL, letters.hi) AS person_name__kana_fold_letters_hi,
  customer, batch
FROM lettered;
-- Stage 2 (fit) learns the model that weighs a pair, Fellegi–Sunter as Splink 5.0 fits it. It learns from counts made
-- on a sample of a fixed size, so its cost doesn't grow with the file. λ comes from the pairs the near-certain rules
-- find, m from EM's pairs, and u from pairs counted exactly or sampled. u is counted again on the file to be scored,
-- because the scores use the file's u. The sample and the file are the two scopes. `YOUR_PROJECT.nayose`.fit_model(nayose/em.py, a Python
-- function on both engines) learns the model from the counts. Every count is an exact integer. The comparisons are
-- functions.sql's. O(n + P_prior + P_em·K) on the sample of n records, and O(N + max_pairs·K) for u on each scope.
--
-- A build runs this stage; an update doesn't, and scores with the model the build left. A build given a model
-- (v_refit false: scripts/benchmark.py's, fitted on another file) draws no sample and runs no EM, and measures that
-- model's u on its records.
--
-- v_refit acts on the data, not by skipping a statement (no statement here has a `-- when:` line). With v_refit false,
-- fit_sample is empty, so the sample's counts and EM's pairs are empty too, and learned's one IF hands fit's model to
-- fit_model, which keeps it.
--
-- Reads: records, and with v_refit false the model given (fit).
-- Values: v_fit_records, v_seed, v_fit_u_max_pairs, v_u_max_pairs and v_settings come from config.toml [fit]. v_fit_records
-- is the sample's size, in records. v_seed seeds the hash that draws u's sampled pairs. v_fit_u_max_pairs and
-- v_u_max_pairs are about how many pairs u samples on the sample and on the file. v_settings is all of [fit] as JSON,
-- for fit_model.
-- v_refit is false for a build given a model, which learns none.
-- Writes:
--   compared     a view of the columns that the fit and the scores read of a record
--   model        each level's m and u as fitted on the sample, its file_m and file_u on the file, and its bits,
--                log2(file_m / file_u), which a score adds
--   fit          λ (probability), the sample's size, the file's size, prior_bits (the prior in bits at the file's
--                size), the notes the report reads, and fitted (fit_model's whole answer)
-- Every other result is the stage's own, read by no later stage. Each is a temporary table where it costs more to
-- make than to read and is read more than once (u_patterns, six times by u_sampled), as BigQuery makes a WITH again
-- each time it is named. Any other is a WITH: one read once, or one that costs no more than its reads (u_records,
-- two tables' rows).

-- fit is made first, empty where a build dropped it, as section 3 reads its fitted where a build is given a model.
CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.fit (probability FLOAT64, fit_records INT64, records INT64, prior_bits FLOAT64, notes STRING,
                                fitted STRING);


-- 1. compared holds the columns that the comparisons, the near-certain rules and EM's keys read. Only these columns
--    are read, so only these are billed. The sample takes postal areas whole, in the order of their hash, until it
--    holds v_fit_records records, and cuts the last area by its records' hash. So a household's records stay together,
--    but in that last area, and a smaller sample is part of a bigger one.
CREATE OR REPLACE VIEW `YOUR_PROJECT.nayose`.compared AS
SELECT
  id, person_name, full_name, given_name__kana_fold, person_name__kana_fold, person_name__kana_fold_long_vowel,
  person_name__kana_fold_one_byte, person_name__kana_fold_letters_lo, person_name__kana_fold_letters_hi,
  company_name, company_name__nfkc_strip_legal_form_kana_fold,
  company_name__nfkc_strip_legal_form_kana_fold_one_byte, address_code, address__address,
  address__address_one_byte_hash, postal_code, phone, customer_id, birth_date
FROM `YOUR_PROJECT.nayose`.records;

-- A build given a model (v_refit false) learns none, so its sample is empty.
CREATE OR REPLACE TEMP TABLE fit_sample AS
SELECT compared.* FROM `YOUR_PROJECT.nayose`.compared
JOIN (SELECT id FROM `YOUR_PROJECT.nayose`.records WHERE v_refit ORDER BY `YOUR_PROJECT.nayose`.er_hash(postal_code__first3), `YOUR_PROJECT.nayose`.er_hash(id) LIMIT 100000)
  USING (id);


-- 2. u is how often two different entities land in a level. It is counted on the sample, which the model is
--    learned with, and on the file, which the scores use. The two differ because in a bigger file, a field whose
--    values grow with the file agrees by chance less often. A comparison's equality levels before its first fuzzy
--    level are counted exactly, from how many records hold each value, never pair by pair. So is the one-edit level
--    that follows equality for phone, cif and birth. A sample of pairs would miss an agreement rarer than one pair
--    in a billion. The other levels' u comes from a random sample of about max_pairs pairs, drawn as Splink draws it.
--    Each count reads u_records, the two scopes' records, as a WITH of its own: it costs what a view would, and a
--    view can't read the temporary fit_sample.

-- 2a. u_outside counts each comparison's pairs outside its missing level, and each u is a share of these pairs. A
--     pair is missing if each of the comparison's columns is empty on at least one side. A record's mask has a bit
--     for each of the comparison's columns it fills, so two records make a missing pair if their masks share no bit.
--     u_outside is every pair less the missing ones.
CREATE OR REPLACE TEMP TABLE u_masks AS
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM `YOUR_PROJECT.nayose`.compared)
SELECT scope, 'name' AS comparison, IF(person_name IS NOT NULL, 1, 0) AS mask, COUNT(*) AS n
FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'company', IF(company_name__nfkc_strip_legal_form_kana_fold IS NOT NULL, 1, 0) AS mask, COUNT(*)
          FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'address',
                 IF(address_code IS NOT NULL, 1, 0) + IF(address__address IS NOT NULL, 2, 0)
                 + IF(postal_code IS NOT NULL, 4, 0)
                   AS mask,
                 COUNT(*)
          FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'phone', IF(phone IS NOT NULL, 1, 0) AS mask, COUNT(*) FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'cif', IF(customer_id IS NOT NULL, 1, 0) AS mask, COUNT(*) FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'birth', IF(birth_date IS NOT NULL, 1, 0) AS mask, COUNT(*) FROM u_records GROUP BY scope, mask;

CREATE OR REPLACE TEMP TABLE u_outside AS
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM `YOUR_PROJECT.nayose`.compared),
all_pairs AS (SELECT scope, `YOUR_PROJECT.nayose`.pairs_of(COUNT(*)) AS pairs FROM u_records GROUP BY scope),
missing AS (
  SELECT a.scope, a.comparison, SUM(IF(a.mask = b.mask, `YOUR_PROJECT.nayose`.pairs_of(a.n), a.n * b.n)) AS pairs
  FROM u_masks AS a JOIN u_masks AS b
    ON a.scope = b.scope AND a.comparison = b.comparison AND a.mask <= b.mask AND (a.mask & b.mask) = 0
  GROUP BY a.scope, a.comparison
)
SELECT c.scope, c.comparison, all_pairs.pairs - COALESCE(missing.pairs, 0) AS pairs
FROM (SELECT DISTINCT scope, comparison FROM u_masks) AS c
JOIN all_pairs USING (scope) LEFT JOIN missing USING (scope, comparison);

-- 2b. u_counted counts each comparison's equality levels, up to its first fuzzy level. The pairs equal on a set of
--     columns, all filled, number Σ n(n−1)/2, with n the number of records holding each combination of values. A
--     level that follows others counts only the pairs equal on it and on no level before it. Address's 'same address'
--     level counts the pairs equal on the address code or on the address. Both come by inclusion–exclusion, and sign
--     adds or takes away each term.
CREATE OR REPLACE TEMP TABLE u_counted AS
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM `YOUR_PROJECT.nayose`.compared)
SELECT scope, comparison, label, SUM(sign * `YOUR_PROJECT.nayose`.pairs_of(n)) AS pairs
FROM (
  SELECT scope, 'name' AS comparison, 'exact' AS label, 1 AS sign, COUNT(*) AS n
  FROM u_records WHERE person_name IS NOT NULL GROUP BY scope, person_name
  UNION ALL SELECT scope, 'name', 'fold exact', 1, COUNT(*)
  FROM u_records WHERE person_name__kana_fold IS NOT NULL GROUP BY scope, person_name__kana_fold
  UNION ALL SELECT scope, 'name', 'fold exact', -1, COUNT(*)
  FROM u_records WHERE person_name IS NOT NULL AND person_name__kana_fold IS NOT NULL
  GROUP BY scope, person_name, person_name__kana_fold
  UNION ALL SELECT scope, 'name', 'same reading', 1, COUNT(*)
  FROM u_records WHERE person_name__kana_fold_long_vowel IS NOT NULL GROUP BY scope, person_name__kana_fold_long_vowel
  UNION ALL SELECT scope, 'name', 'same reading', -1, COUNT(*)
  FROM u_records WHERE person_name IS NOT NULL AND person_name__kana_fold_long_vowel IS NOT NULL
  GROUP BY scope, person_name, person_name__kana_fold_long_vowel
  UNION ALL SELECT scope, 'name', 'same reading', -1, COUNT(*)
  FROM u_records WHERE person_name__kana_fold IS NOT NULL AND person_name__kana_fold_long_vowel IS NOT NULL
  GROUP BY scope, person_name__kana_fold, person_name__kana_fold_long_vowel
  UNION ALL SELECT scope, 'name', 'same reading', 1, COUNT(*)
  FROM u_records
  WHERE person_name IS NOT NULL AND person_name__kana_fold IS NOT NULL AND person_name__kana_fold_long_vowel IS NOT NULL
  GROUP BY scope, person_name, person_name__kana_fold, person_name__kana_fold_long_vowel
  UNION ALL SELECT scope, 'company', 'exact', 1, COUNT(*)
  FROM u_records WHERE company_name__nfkc_strip_legal_form_kana_fold IS NOT NULL
  GROUP BY scope, company_name__nfkc_strip_legal_form_kana_fold
  UNION ALL SELECT scope, 'address', 'same address', 1, COUNT(*)
  FROM u_records WHERE address_code IS NOT NULL GROUP BY scope, address_code
  UNION ALL SELECT scope, 'address', 'same address', 1, COUNT(*)
  FROM u_records WHERE address__address IS NOT NULL GROUP BY scope, address__address
  UNION ALL SELECT scope, 'address', 'same address', -1, COUNT(*)
  FROM u_records WHERE address_code IS NOT NULL AND address__address IS NOT NULL
  GROUP BY scope, address_code, address__address
  UNION ALL SELECT scope, 'phone', 'exact', 1, COUNT(*) FROM u_records WHERE phone IS NOT NULL GROUP BY scope, phone
  UNION ALL SELECT scope, 'cif', 'exact', 1, COUNT(*)
  FROM u_records WHERE customer_id IS NOT NULL GROUP BY scope, customer_id
  UNION ALL SELECT scope, 'birth', 'exact', 1, COUNT(*)
  FROM u_records WHERE birth_date IS NOT NULL GROUP BY scope, birth_date
)
GROUP BY scope, comparison, label;

-- 2c. u_one_edit counts the one-edit level ('one digit off') that follows equality for phone, cif and birth. It counts
--     by keys, never pair by pair. Two values of one length that differ by one substitution share exactly one key,
--     the value without its i-th character, together with i. For cif and birth, Damerau–Levenshtein also counts two
--     swapped neighbours as one edit. Two such values share exactly one swap key, the value with its i-th and
--     (i+1)-th characters put in order, together with i. If a key's values are held by n records each, the key
--     makes ((Σn)² − Σn²) / 2 pairs of records whose values differ. A value one character longer than another is
--     one deletion away from it, so each longer value's deletions are joined to the shorter values.
CREATE OR REPLACE TEMP TABLE u_values AS
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM `YOUR_PROJECT.nayose`.compared)
SELECT scope, 'phone' AS comparison, phone AS x, COUNT(*) AS n, LENGTH(phone) AS len
FROM u_records WHERE phone IS NOT NULL GROUP BY scope, phone
UNION ALL SELECT scope, 'cif', customer_id, COUNT(*), LENGTH(customer_id)
          FROM u_records WHERE customer_id IS NOT NULL GROUP BY scope, customer_id
UNION ALL SELECT scope, 'birth', birth_date, COUNT(*), LENGTH(birth_date)
          FROM u_records WHERE birth_date IS NOT NULL GROUP BY scope, birth_date;

CREATE OR REPLACE TEMP TABLE u_one_edit AS
WITH substituted AS (
  SELECT scope, comparison, SUM(DIV(s * s - ss, 2)) AS pairs
  FROM (SELECT scope, comparison, SUM(n) AS s, SUM(n * n) AS ss FROM u_values, UNNEST(GENERATE_ARRAY(1, len)) AS i
        GROUP BY scope, comparison, len, i, SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1))
  GROUP BY scope, comparison
),
swapped AS (
  SELECT scope, comparison, SUM(DIV(s * s - ss, 2)) AS pairs
  FROM (SELECT scope, comparison, SUM(n) AS s, SUM(n * n) AS ss FROM u_values, UNNEST(GENERATE_ARRAY(1, len)) AS i
        WHERE comparison IN ('cif', 'birth') AND i < len AND SUBSTR(x, i, 1) <> SUBSTR(x, i + 1, 1)
        GROUP BY scope, comparison, len, i,
                 SUBSTR(x, 1, i - 1) || LEAST(SUBSTR(x, i, 1), SUBSTR(x, i + 1, 1))
                 || GREATEST(SUBSTR(x, i, 1), SUBSTR(x, i + 1, 1)) || SUBSTR(x, i + 2))
  GROUP BY scope, comparison
),
-- shorter holds each value with one character deleted. Phone's Hamming distance pads the shorter value at its end,
-- so a phone loses only its last character. Deleting any character of a run of equal characters gives the same
-- value, so a run is deleted from once.
shorter AS (
  SELECT scope, comparison, x, n, len, SUBSTR(x, 1, len - 1) AS d FROM u_values WHERE comparison = 'phone'
  UNION ALL
  SELECT scope, comparison, x, n, len, SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1)
  FROM u_values, UNNEST(GENERATE_ARRAY(1, len + 1)) AS i
  WHERE comparison <> 'phone' AND (i = 1 OR i > len OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1))
),
longer AS (
  SELECT scope, comparison, SUM(nn) AS pairs
  FROM (SELECT DISTINCT a.scope, a.comparison, a.x AS ax, b.x AS bx, a.n * b.n AS nn
        FROM shorter AS a JOIN u_values AS b
          ON b.scope = a.scope AND b.comparison = a.comparison AND b.x = a.d AND b.len = a.len - 1)
  GROUP BY scope, comparison
)
SELECT c.scope, c.comparison, 'one digit off' AS label,
       COALESCE(s.pairs, 0) + COALESCE(sw.pairs, 0) + COALESCE(lg.pairs, 0) AS pairs
FROM (SELECT DISTINCT scope, comparison FROM u_outside WHERE comparison IN ('phone', 'cif', 'birth')) AS c
LEFT JOIN substituted AS s USING (scope, comparison)
LEFT JOIN swapped AS sw USING (scope, comparison)
LEFT JOIN longer AS lg USING (scope, comparison);

-- 2d. The other levels' u is sampled as Splink samples it. A scope's records are drawn if the hash of their ID and
--     v_seed falls under the scope's cut. Every pair of a scope's drawn records gets its level in each comparison,
--     and the levels are counted. A comparison isn't sampled if all its levels are counted exactly. That happens if
--     its exact and one-edit levels both hold pairs, and some pairs are left for its else level. u_plan tells, for
--     each scope, whether phone, cif and birth are sampled. The other comparisons have fuzzy levels, so they are
--     always sampled.
--     A comparison that no record of a scope fills has no exact count (u_counted), so it is sampled, and its u is
--     the bound, as em.py gives a level that no pair reached. The joins are LEFT, so a scope that fills none of
--     phone, cif and birth keeps its row, and its other comparisons' pairs are still sampled.
CREATE OR REPLACE TEMP TABLE u_plan AS
SELECT
  scope,
  NOT LOGICAL_OR(comparison = 'phone' AND counted_whole) AS phone,
  NOT LOGICAL_OR(comparison = 'cif' AND counted_whole) AS cif,
  NOT LOGICAL_OR(comparison = 'birth' AND counted_whole) AS birth
FROM (  -- one row per scope and comparison. counted_whole is TRUE if all its levels are counted exactly.
  SELECT o.scope, o.comparison,
         COALESCE(c.pairs > 0 AND one_edit.pairs > 0 AND c.pairs + one_edit.pairs < o.pairs, FALSE) AS counted_whole
  FROM u_outside AS o
  LEFT JOIN u_counted AS c ON c.scope = o.scope AND c.comparison = o.comparison AND c.label = 'exact'
  LEFT JOIN u_one_edit AS one_edit ON one_edit.scope = o.scope AND one_edit.comparison = o.comparison
)
GROUP BY scope;

-- Each scope draws the share k / n of its n records, as Splink does, and all its records if the share is 1 or more.
-- A record is drawn if its hash, read in billionths (MOD 1,000,000,000), falls under the share, so a share is drawn
-- to the nearest billionth, and at least one billionth.
CREATE OR REPLACE TEMP TABLE u_drawn AS
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM `YOUR_PROJECT.nayose`.compared),
shares AS (
  SELECT 'sample' AS scope, `YOUR_PROJECT.nayose`.records_for_pairs(v_fit_u_max_pairs) / GREATEST((SELECT COUNT(*) FROM fit_sample), 1) AS share
  UNION ALL
  SELECT 'file', `YOUR_PROJECT.nayose`.records_for_pairs(v_u_max_pairs) / GREATEST((SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.records), 1)
)
SELECT u_records.* FROM u_records JOIN shares USING (scope)
WHERE share >= 1 OR MOD(`YOUR_PROJECT.nayose`.er_hash(id || '_' || v_seed), 1000000000) < GREATEST(1, ROUND(share * 1000000000));

-- Each pattern of levels that the drawn pairs make is counted as the pairs are made, so no pair is stored. A
-- comparison that u_plan doesn't sample is NULL.
CREATE OR REPLACE TEMP TABLE u_patterns AS
WITH paired AS (  -- a pair keeps its two records whole, and name_score runs once a pair for name_level
  SELECT x.scope, x, y, `YOUR_PROJECT.nayose`.name_score(x, y) AS s_name
  FROM u_drawn AS x JOIN u_drawn AS y ON x.scope = y.scope AND x.id < y.id
)
SELECT scope, name, company, address, phone, cif, birth, COUNT(*) AS pairs
FROM (  -- a subquery, so that the GROUP BY's phone, cif and birth name the levels, not u_plan's columns of those names
  SELECT
    p.scope, `YOUR_PROJECT.nayose`.name_level(p.x, p.y, p.s_name) AS name, `YOUR_PROJECT.nayose`.gamma_company(p.x, p.y) AS company,
    `YOUR_PROJECT.nayose`.gamma_address(p.x, p.y) AS address, IF(plan.phone, `YOUR_PROJECT.nayose`.gamma_phone(p.x, p.y), NULL) AS phone,
    IF(plan.cif, `YOUR_PROJECT.nayose`.gamma_cif(p.x, p.y), NULL) AS cif, IF(plan.birth, `YOUR_PROJECT.nayose`.gamma_birth(p.x, p.y), NULL) AS birth
  FROM paired AS p JOIN u_plan AS plan ON plan.scope = p.scope
)
GROUP BY scope, name, company, address, phone, cif, birth;

-- 3. fit_model learns the model. It takes counts, settings (v_settings) and given_fit (a build given a model passes
--    it, from fit, and fit_model keeps it), and returns the model as one JSON text. counts is one JSON text of:
--      levels    the levels (a WITH below)            outside   u_outside (section 2a)
--      prior     λ's counts (fit_prior, below)        counted   u_counted (2b)
--      patterns  EM's patterns (em_patterns, below)   one_edit  u_one_edit (2c)
--      filled    u_filled (below)                     sampled   u_sampled (below), from u_patterns (2d)
--      plan      u_plan (2d)
--    What only fit_model reads is a WITH of this statement, each read once. The answer holds each level's m and u
--    as fitted on the sample, its file_m and file_u on the file, and its bits from those, which the scores add.
CREATE OR REPLACE TEMP TABLE learned AS
WITH
-- levels lists each comparison's levels, numbered as functions.sql's section 2 numbers them, with what the fit
-- reads of a level. agreement is exact (an equality alone), fuzzy (a distance or a similarity) or else.
-- position is the comparison's place in the model.
levels AS (
  SELECT * FROM UNNEST([
    STRUCT(1 AS position, 'name' AS comparison, 6 AS gamma, 'exact' AS label, 'exact' AS agreement),
    STRUCT(1, 'name', 5, 'fold exact', 'exact'),
    STRUCT(1, 'name', 4, 'same reading', 'exact'),
    STRUCT(1, 'name', 3, 'fold JW high', 'fuzzy'),
    STRUCT(1, 'name', 2, 'given name', 'exact'),
    STRUCT(1, 'name', 1, 'fold JW low', 'fuzzy'),
    STRUCT(1, 'name', 0, 'else', 'else'),
    STRUCT(2, 'company', 2, 'exact', 'exact'),
    STRUCT(2, 'company', 1, 'JW low', 'fuzzy'),
    STRUCT(2, 'company', 0, 'else', 'else'),
    STRUCT(3, 'address', 3, 'same address', 'exact'),
    STRUCT(3, 'address', 2, 'address close', 'fuzzy'),
    STRUCT(3, 'address', 1, 'same postal', 'exact'),
    STRUCT(3, 'address', 0, 'else', 'else'),
    STRUCT(4, 'phone', 2, 'exact', 'exact'),
    STRUCT(4, 'phone', 1, 'one digit off', 'fuzzy'),
    STRUCT(4, 'phone', 0, 'else', 'else'),
    STRUCT(5, 'cif', 2, 'exact', 'exact'),
    STRUCT(5, 'cif', 1, 'one digit off', 'fuzzy'),
    STRUCT(5, 'cif', 0, 'else', 'else'),
    STRUCT(6, 'birth', 2, 'exact', 'exact'),
    STRUCT(6, 'birth', 1, 'one digit off', 'fuzzy'),
    STRUCT(6, 'birth', 0, 'else', 'else')
  ])
),
-- λ is how likely two random records are one entity. fit_model estimates it from prior_pairs, the pairs that
-- any of the near-certain rules find in the sample, each pair counted once. Each rule's own count is kept too,
-- because a rule that finds no pair in the sample is skipped, and the report names it.
-- The near-certain rules are score.sql's X1, X2 and X4. X3 (customer ID and phone) and X5 (company name, address
-- code and phone) are left out, because [fit] prior_recall is the share of all matches that X1, X2 and X4 find,
-- as measured on labelled data, and λ divides prior_pairs by it.
fit_prior AS (
  SELECT
    (SELECT COUNT(*) FROM fit_sample) AS records,
    (SELECT COUNT(*) FROM (
       SELECT x.id AS l, y.id AS r FROM fit_sample AS x JOIN fit_sample AS y  -- X1, customer ID and full name
         ON x.customer_id = y.customer_id AND x.full_name = y.full_name AND x.id < y.id
       UNION DISTINCT
       SELECT x.id, y.id FROM fit_sample AS x JOIN fit_sample AS y  -- X2, customer ID and company name
         ON x.customer_id = y.customer_id AND x.company_name = y.company_name AND x.id < y.id
       UNION DISTINCT
       SELECT x.id, y.id FROM fit_sample AS x JOIN fit_sample AS y  -- X4, full name, address code and phone
         ON x.full_name = y.full_name AND x.address_code = y.address_code AND x.phone = y.phone AND x.id < y.id
    )) AS prior_pairs,
    (SELECT COALESCE(SUM(`YOUR_PROJECT.nayose`.pairs_of(n)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample  -- X1's pairs
       WHERE customer_id IS NOT NULL AND full_name IS NOT NULL GROUP BY customer_id, full_name)) AS cif_name,
    (SELECT COALESCE(SUM(`YOUR_PROJECT.nayose`.pairs_of(n)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample  -- X2's pairs
       WHERE customer_id IS NOT NULL AND company_name IS NOT NULL GROUP BY customer_id, company_name)) AS cif_company,
    (SELECT COALESCE(SUM(`YOUR_PROJECT.nayose`.pairs_of(n)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample  -- X4's pairs
       WHERE full_name IS NOT NULL AND address_code IS NOT NULL AND phone IS NOT NULL
       GROUP BY full_name, address_code, phone)) AS name_code_phone
),
-- EM learns in sessions, one for each field it pairs records by ([fit] em_sessions). The phone session's pairs are
-- the sample's pairs that share a phone, and the address session's share an address. Each pattern of levels is
-- stored once, with its count of pairs. A session can't learn the comparison its field chose the pairs by, as
-- every pair agrees on it, so that comparison is NULL in its session.
em_pairs AS (  -- a pair keeps its two records whole, and name_score runs once a pair for name_level
  SELECT 'phone' AS session, x, y, `YOUR_PROJECT.nayose`.name_score(x, y) AS s_name
  FROM fit_sample AS x JOIN fit_sample AS y ON x.phone = y.phone AND x.id < y.id
  UNION ALL
  SELECT 'address', x, y, `YOUR_PROJECT.nayose`.name_score(x, y)
  FROM fit_sample AS x JOIN fit_sample AS y ON x.address__address = y.address__address AND x.id < y.id
),
em_patterns AS (
  SELECT session, name, company, address, phone, cif, birth, COUNT(*) AS pairs
  FROM (
    SELECT session, `YOUR_PROJECT.nayose`.name_level(x, y, s_name) AS name, `YOUR_PROJECT.nayose`.gamma_company(x, y) AS company,
           IF(session = 'address', CAST(NULL AS INT64), `YOUR_PROJECT.nayose`.gamma_address(x, y)) AS address,
           IF(session = 'phone', CAST(NULL AS INT64), `YOUR_PROJECT.nayose`.gamma_phone(x, y)) AS phone, `YOUR_PROJECT.nayose`.gamma_cif(x, y) AS cif,
           `YOUR_PROJECT.nayose`.gamma_birth(x, y) AS birth
    FROM em_pairs
  )
  GROUP BY session, name, company, address, phone, cif, birth
),
-- u_filled counts each scope's records, and for each comparison the records that fill its column. For address it
-- takes the most filled of its three columns. From these, fit_model estimates how many sampled pairs fill each
-- comparison, and that number bounds the u of a level that no sampled pair reached.
u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM `YOUR_PROJECT.nayose`.compared),
u_filled AS (
  SELECT
    scope, COUNT(*) AS records, COUNT(person_name) AS name,
    COUNT(company_name__nfkc_strip_legal_form_kana_fold) AS company,
    GREATEST(COUNT(address_code), COUNT(address__address), COUNT(postal_code)) AS address,
    COUNT(phone) AS phone, COUNT(customer_id) AS cif, COUNT(birth_date) AS birth
  FROM u_records GROUP BY scope
),
-- u_sampled counts the pairs the sampled levels hold, a comparison at a time, from u_patterns.
u_sampled AS (
  SELECT scope, 'name' AS comparison, name AS gamma, SUM(pairs) AS pairs FROM u_patterns GROUP BY scope, name
  UNION ALL SELECT scope, 'company', company, SUM(pairs) FROM u_patterns GROUP BY scope, company
  UNION ALL SELECT scope, 'address', address, SUM(pairs) FROM u_patterns GROUP BY scope, address
  UNION ALL SELECT scope, 'phone', phone, SUM(pairs) FROM u_patterns WHERE phone IS NOT NULL GROUP BY scope, phone
  UNION ALL SELECT scope, 'cif', cif, SUM(pairs) FROM u_patterns WHERE cif IS NOT NULL GROUP BY scope, cif
  UNION ALL SELECT scope, 'birth', birth, SUM(pairs) FROM u_patterns WHERE birth IS NOT NULL GROUP BY scope, birth
)
SELECT `YOUR_PROJECT.nayose`.fit_model(TO_JSON_STRING(STRUCT(
  (SELECT ARRAY_AGG(t) FROM levels AS t) AS levels, (SELECT ARRAY_AGG(t) FROM fit_prior AS t) AS prior,
  (SELECT ARRAY_AGG(t) FROM em_patterns AS t) AS patterns, (SELECT ARRAY_AGG(t) FROM u_outside AS t) AS outside,
  (SELECT ARRAY_AGG(t) FROM u_counted AS t) AS counted, (SELECT ARRAY_AGG(t) FROM u_one_edit AS t) AS one_edit,
  (SELECT ARRAY_AGG(t) FROM u_sampled AS t) AS sampled, (SELECT ARRAY_AGG(t) FROM u_filled AS t) AS filled,
  (SELECT ARRAY_AGG(t) FROM u_plan AS t) AS plan
)), v_settings, IF(v_refit, NULL, (SELECT fitted FROM `YOUR_PROJECT.nayose`.fit))) AS out;

CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.model AS
SELECT
  CAST(JSON_VALUE(lv, '$.position') AS INT64) AS position, JSON_VALUE(lv, '$.comparison') AS comparison,
  CAST(JSON_VALUE(lv, '$.gamma') AS INT64) AS gamma, JSON_VALUE(lv, '$.label') AS label,
  JSON_VALUE(lv, '$.agreement') AS agreement,
  CAST(JSON_VALUE(lv, '$.m') AS FLOAT64) AS m, CAST(JSON_VALUE(lv, '$.u') AS FLOAT64) AS u,
  CAST(JSON_VALUE(lv, '$.file_m') AS FLOAT64) AS file_m, CAST(JSON_VALUE(lv, '$.file_u') AS FLOAT64) AS file_u,
  CAST(JSON_VALUE(lv, '$.bits') AS FLOAT64) AS bits
FROM learned, UNNEST(JSON_QUERY_ARRAY(out, '$.levels')) AS lv;

CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.fit AS
SELECT CAST(JSON_VALUE(out, '$.probability') AS FLOAT64) AS probability,
       CAST(JSON_VALUE(out, '$.fit_records') AS INT64) AS fit_records,
       CAST(JSON_VALUE(out, '$.records') AS INT64) AS records,
       CAST(JSON_VALUE(out, '$.prior_bits') AS FLOAT64) AS prior_bits, JSON_QUERY(out, '$.notes') AS notes, out AS fitted
FROM learned;
-- Stage 3, score. This stage finds the pairs worth scoring and scores them. It pairs the records of the run's latest
-- batch, and the run's records that records.sql made again, with all the run's records. In a build, every record is
-- the batch's.
-- The pairs come from the rules and from the keys. Every pair that a key lists is a candidate. If a key's block holds
-- v_oversized records or more, the stage first scores a sample of the block's pairs, and lists the block's pairs only if
-- the sample holds a pair at v_search_floor points or more. Each pair gets its level of each comparison (functions.sql)
-- and its points from the model. The points are the prior plus each level's bits, added in the model's order, so
-- that the sum is Splink's to the last bit. The stage keeps every pair with v_keep_from points or more, and every
-- rule pair. These are the pairs a match run can offer people. Nothing merges here.
-- A pair's two records are x and y. l and r are the pair's IDs, and they can't name its records too, because a
-- WHERE clause reads a name l differently on the two engines: DuckDB as the SELECT's column l, BigQuery as the table l.
-- It costs O(Δ·b) for the batch's pairs, with Δ the batch's records and b the pairs one record's keys list, plus
-- O(Δ·L) to make the changed records' keys, L a value's length (Δ counts the records made again too), and a scan of
-- the index for the blocks the batch's keys name. The scores cost O(C·K·L²) for C candidates and K comparisons (6).
-- An update that makes records again also deletes their keys and their pairs, and on BigQuery a DELETE bills its
-- table whole: the index and scored.
--
-- A statement that follows a `-- when: <condition>` line runs only if the condition holds: run_file checks it locally,
-- and the deployed procedure wraps the statement in IF … END IF.
--
-- Reads: records, this_batch and redone (records.sql), compared (fit.sql), model (each level's bits) and fit (the
-- prior's bits at the file's size); block_size, a lookup's blocks read in part (nayose.lookup).
-- Values:
--   v_generators, v_rules   the names of the generators and the rules this run uses (config.toml [score])
--   v_keep_from            a scored pair with this many points or more is kept
--   v_search_floor         a sampled pair with this many points or more keeps its block
--   v_oversized            a block of this many records or more is checked first on a sample of as many of its records
--   v_lookup               true if the batch is a record asked about. Each of its keys is then kept, even in a block
--                         of one, so that lookup.sql can report it.
--   v_outside              how many of the run's records the records table doesn't hold. A lookup's records table
--                         holds only its record's blocks (nayose.lookup). In any other job, it is 0.
-- Writes:
--   rule_keys and every_key   each record's keys, which are the index a lookup reads by key
--   cands                     the pairs the batch's keys list, each with the generators that listed it
--   scored                    every pair kept
-- scored holds every batch's pairs. Each batch adds the pairs that touch its records, a rule's pair with its rule.
-- The pairs of a record made again leave it, and are scored again with the record's values as they are now.

-- 0. The records this job pairs, the generators and the rules.
-- changed holds the records whose keys this job makes: the batch's, and the run's records that records.sql made again
-- (redone), with redone TRUE. Every other record's keys are as the last job left them, since a record's keys change
-- only when the record does.
CREATE OR REPLACE TEMP TABLE changed AS
SELECT id, FALSE AS redone FROM `YOUR_PROJECT.nayose`.records WHERE batch = (SELECT batch FROM this_batch)
UNION ALL SELECT id, TRUE FROM redone;

-- batch_records holds the records this job pairs with all the run's records, which the statements below call the
-- batch's (in_batch). They are the batch's own records and the records made again, whose pairs are scored again
-- with their values as they are now: in an update or a build, changed whole.
CREATE OR REPLACE TEMP TABLE batch_records AS SELECT id FROM changed;

-- The generators and the rules are listed by name, in order. The statements below name each one, and read its
-- position from these lists. A generator's position (g) is its bit in a pair's mask, which cands turns into its
-- generators' names. A rule's position (i) is its rank: if several rules find a pair, the first one names it.
-- config.toml says which ones this run uses, and a name it gives that isn't listed here is refused.
-- The rules, in rank order. An X rule is exact: its key alone finds its pairs. An F rule is fuzzy: its key finds the
-- pairs, and its test then keeps those whose ~ fields are close. In a rule's name, ~ marks a field tested fuzzily,
-- outside the key (section 6's tests, functions.sql's near_*).
--   rule                           its key's fields                          its test
--   X1_CIF_FULL_NAME               customer_id, full_name                    none
--   X2_CIF_COMPANY_NAME            customer_id, company_name                 none
--   X3_CIF_PHONE                   customer_id, phone                        none
--   X4_FULL_NAME_ADDRCD_PHONE      full_name, address_code, phone            none
--   X5_COMPANY_NAME_ADDRCD_PHONE   company_name, address_code, phone         none
--   F1_NAME~_ADDRCD_PHONE          address_code, phone                       near_name
--   F2_NAME~_ADDRESS~_PHONE        phone, address__address_first3            near_name and near_address
--   F3_NAME~_CIF                   customer_id                               near_name
--   F4_NAME_ADDRCD_PHONE~          person_name, address_code                 near_phone
--   F5_COMPANY~_PHONE_POSTAL       phone, postal_code                        near_company
--   F6_COMPANY~_ADDRCD_PHONE       address_code, phone                       near_company
--   X6_GIVEN_ADDRCD_PHONE          given_name, address_code, phone           none
CREATE OR REPLACE TEMP TABLE generators AS
SELECT g, name, name IN UNNEST(v_generators) AS used FROM UNNEST([
  'customer_id', 'phone_prefecture', 'phone_postal_area', 'phone_name_initial', 'person_name', 'company_name', 'company_name_deletions',
  'person_name_deletions_postal_area', 'given_name_postal', 'address_phone', 'address_code_phone', 'address_name_initial',
  'address_code_name_initial', 'given_name_address_code', 'customer_id_deletions', 'birth_date', 'given_name_phone',
  'birth_date_deletions_prefecture', 'name_reading', 'phone_name_tail', 'postal_name_tail', 'postal_area_name_tail'
]) AS name WITH OFFSET AS g;

CREATE OR REPLACE TEMP TABLE rules AS
SELECT i, rule, rule IN UNNEST(v_rules) AS used FROM UNNEST([
  'X1_CIF_FULL_NAME', 'X2_CIF_COMPANY_NAME', 'X3_CIF_PHONE', 'X4_FULL_NAME_ADDRCD_PHONE',
  'X5_COMPANY_NAME_ADDRCD_PHONE', 'F1_NAME~_ADDRCD_PHONE', 'F2_NAME~_ADDRESS~_PHONE', 'F3_NAME~_CIF',
  'F4_NAME_ADDRCD_PHONE~', 'F5_COMPANY~_PHONE_POSTAL', 'F6_COMPANY~_ADDRCD_PHONE', 'X6_GIVEN_ADDRCD_PHONE'
]) AS rule WITH OFFSET AS i;

SELECT IF(COUNT(*) > 0, ERROR(CONCAT('config.toml [score]: no generator or rule is named ', STRING_AGG(x, ', '),
                                     '; name those score.sql lists')), 0)
FROM (SELECT x FROM UNNEST(v_generators) AS x WHERE x NOT IN (SELECT name FROM generators)
      UNION ALL SELECT x FROM UNNEST(v_rules) AS x WHERE x NOT IN (SELECT rule FROM rules));


-- 1. The rules. Each rule joins the records on its key, then applies its fuzzy tests to the pairs that join. If a key
--    value is held by v_oversized records or more, it can't be one entity's, so the rule leaves it out. The model
--    can still match those records. The batch's records are paired with all the run's records, each pair once, with
--    the lower ID first.
--    A key of several fields joins them with CHR(31), the unit separator. read_value removes every control character
--    (functions.sql), so no field holds it, and two different lists of values never make the same key.
CREATE OR REPLACE TEMP TABLE made_rule_keys AS  -- the rule keys of the records in changed
WITH changed_records AS (SELECT * FROM `YOUR_PROJECT.nayose`.records WHERE id IN (SELECT id FROM changed))
SELECT rules.i, key, id FROM (
  SELECT 'X1_CIF_FULL_NAME' AS rule, customer_id || CHR(31) || full_name AS key, id FROM changed_records
  UNION ALL SELECT 'X2_CIF_COMPANY_NAME', customer_id || CHR(31) || company_name, id FROM changed_records
  UNION ALL SELECT 'X3_CIF_PHONE', customer_id || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'X4_FULL_NAME_ADDRCD_PHONE', full_name || CHR(31) || address_code || CHR(31) || phone, id
    FROM changed_records
  UNION ALL SELECT 'X5_COMPANY_NAME_ADDRCD_PHONE', company_name || CHR(31) || address_code || CHR(31) || phone, id
    FROM changed_records
  UNION ALL SELECT 'F1_NAME~_ADDRCD_PHONE', address_code || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'F2_NAME~_ADDRESS~_PHONE', phone || CHR(31) || address__address_first3, id FROM changed_records
  UNION ALL SELECT 'F3_NAME~_CIF', customer_id, id FROM changed_records
  UNION ALL SELECT 'F4_NAME_ADDRCD_PHONE~', person_name || CHR(31) || address_code, id FROM changed_records
  UNION ALL SELECT 'F5_COMPANY~_PHONE_POSTAL', phone || CHR(31) || postal_code, id FROM changed_records
  UNION ALL SELECT 'F6_COMPANY~_ADDRCD_PHONE', address_code || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'X6_GIVEN_ADDRCD_PHONE', given_name || CHR(31) || address_code || CHR(31) || phone, id FROM changed_records
) JOIN rules USING (rule)
WHERE key IS NOT NULL AND rules.used;

-- rule_keys holds every record's rule keys. The records made again leave it, and the changed records' keys join it.
CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.rule_keys CLUSTER BY key AS SELECT i, key, id FROM made_rule_keys WHERE FALSE;
SET v_condition_2 = (EXISTS(SELECT 1 FROM changed WHERE redone));
IF v_condition_2 THEN

DELETE FROM `YOUR_PROJECT.nayose`.rule_keys WHERE id IN (SELECT id FROM changed WHERE redone);
END IF;

INSERT INTO `YOUR_PROJECT.nayose`.rule_keys SELECT i, key, id FROM made_rule_keys;
SET v_condition_3 = (EXISTS(SELECT 1 FROM this_batch WHERE batch = 0));
IF v_condition_3 THEN

-- rule_blocks holds every record of each rule key the batch holds. in_batch is TRUE for the batch's records, and n is
-- the number of records that hold the key.
-- In the run's first batch (batch 0) every record is the batch's, so every rule key is. A lookup takes the second
-- form whatever its batch, so that only the record it looks up is in_batch.
CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, key, id, TRUE AS in_batch, COUNT(*) OVER (PARTITION BY i, key) AS n FROM `YOUR_PROJECT.nayose`.rule_keys;
END IF;
IF NOT v_condition_3 THEN

CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, key, id, id IN (SELECT id FROM batch_records) AS in_batch, COUNT(*) OVER (PARTITION BY i, key) AS n
FROM `YOUR_PROJECT.nayose`.rule_keys
JOIN (SELECT DISTINCT i, key FROM made_rule_keys WHERE id IN (SELECT id FROM batch_records)) USING (i, key);
END IF;


-- 2. The keys. Each generator makes a key for each record from one or more of its fields, joined by CHR(31) as a
--    rule's are. The records with the same key form a block. A deletion generator makes several keys for a record.
--    They are its value with each character deleted in turn, and the value whole, each joined to the generator's other
--    fields. Deleting any character of a run of equal characters gives the same value, so a run gives its key once.
CREATE OR REPLACE TEMP TABLE made_keys AS  -- the keys of the records in changed
WITH changed_records AS (SELECT * FROM `YOUR_PROJECT.nayose`.records WHERE id IN (SELECT id FROM changed))
SELECT generators.g, key, id FROM (
  SELECT 'customer_id' AS name, customer_id AS key, id FROM changed_records
  UNION ALL SELECT 'phone_prefecture', phone || CHR(31) || prefecture, id FROM changed_records
  UNION ALL SELECT 'phone_postal_area', phone || CHR(31) || postal_code__first3, id FROM changed_records
  UNION ALL SELECT 'phone_name_initial', phone || CHR(31) || any_name__initial, id FROM changed_records
  UNION ALL SELECT 'person_name', person_name__kana_fold, id FROM changed_records
  UNION ALL SELECT 'company_name', company_name__nfkc_strip_legal_form_kana_fold, id FROM changed_records
  UNION ALL SELECT 'company_name_deletions', SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT company_name__nfkc_strip_legal_form_kana_fold AS x, id FROM changed_records
          WHERE company_name__nfkc_strip_legal_form_kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'person_name_deletions_postal_area', rest || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT person_name__kana_fold AS x, postal_code__first3 AS rest, id FROM changed_records
          WHERE person_name__kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'given_name_postal', given_name__kana_fold || CHR(31) || postal_code, id FROM changed_records
  UNION ALL SELECT 'address_phone', address__address || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'address_code_phone', address_code || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'address_name_initial', address__address || CHR(31) || any_name__initial, id FROM changed_records
  UNION ALL SELECT 'address_code_name_initial', address_code || CHR(31) || any_name__initial, id FROM changed_records
  UNION ALL SELECT 'given_name_address_code', given_name__kana_fold || CHR(31) || address_code, id FROM changed_records
  UNION ALL SELECT 'customer_id_deletions', SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT customer_id AS x, id FROM changed_records WHERE customer_id IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'birth_date', birth_date, id FROM changed_records
  UNION ALL SELECT 'given_name_phone', given_name__kana_fold || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'birth_date_deletions_prefecture', rest || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT birth_date AS x, prefecture AS rest, id FROM changed_records WHERE birth_date IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'name_reading', person_name__kana_fold_long_vowel, id FROM changed_records
  UNION ALL SELECT 'phone_name_tail', phone || CHR(31) || person_name__kana_fold_long_vowel_last3, id FROM changed_records
  UNION ALL SELECT 'postal_name_tail', postal_code || CHR(31) || person_name__kana_fold_long_vowel_last3, id FROM changed_records
  UNION ALL SELECT 'postal_area_name_tail', postal_code__first3 || CHR(31) || person_name__kana_fold_long_vowel_last3, id
    FROM changed_records
) JOIN generators USING (name)
WHERE key IS NOT NULL AND generators.used;

-- every_key holds every record's keys, which are the index a lookup reads by key. The records made again leave it,
-- and the changed records' keys join it.
CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.every_key CLUSTER BY key AS SELECT g, key, id FROM made_keys WHERE FALSE;
IF v_condition_2 THEN

DELETE FROM `YOUR_PROJECT.nayose`.every_key WHERE id IN (SELECT id FROM changed WHERE redone);
END IF;

INSERT INTO `YOUR_PROJECT.nayose`.every_key SELECT g, key, id FROM made_keys;

-- block_size gives a block's whole size if records holds only part of it. A lookup makes the table first, with the
-- blocks it read in part. In any other job, this statement makes it empty.
CREATE TEMP TABLE IF NOT EXISTS block_size (g INT64, key STRING, n INT64);
IF v_condition_3 THEN

-- key_blocks gives each key its block's size n among all the run's records. It keeps only the blocks that touch the
-- batch and hold two records or more, since only those can make a pair. A lookup also keeps its record's blocks of
-- one, so that lookup.sql can report every key.
-- In the run's first batch every record is the batch's, so every block is.
CREATE OR REPLACE TEMP TABLE key_blocks AS
SELECT g, key, id, TRUE AS in_batch, n FROM (SELECT g, key, id, COUNT(*) OVER (PARTITION BY g, key) AS n FROM `YOUR_PROJECT.nayose`.every_key)
WHERE n > 1;
END IF;
IF NOT v_condition_3 THEN

CREATE OR REPLACE TEMP TABLE key_blocks AS
-- touched holds every record of each block that a key of the batch names. held is the number of records the run
-- holds in the block.
WITH touched AS (
  SELECT e.g, e.key, e.id, COUNT(*) OVER (PARTITION BY e.g, e.key) AS held
  FROM `YOUR_PROJECT.nayose`.every_key AS e
  JOIN (SELECT DISTINCT g, key FROM made_keys WHERE id IN (SELECT id FROM batch_records)) USING (g, key)
)
SELECT t.g, t.key, t.id, t.id IN (SELECT id FROM batch_records) AS in_batch, COALESCE(u.n, t.held) AS n
FROM touched AS t LEFT JOIN block_size AS u USING (g, key)
WHERE (t.held > 1 OR v_lookup)  -- records holds two of the block's records or more, or the job is a lookup
  -- and the block at its whole size (block_size) holds two records or more, or the record is the batch's. So a lookup
  -- keeps a block of one only for the record it looks up.
  AND (COALESCE(u.n, t.held) > 1 OR t.id IN (SELECT id FROM batch_records));
END IF;

-- listed holds every pair that touches the batch and shares a block of fewer than v_oversized records. mask has one
-- bit set for each generator whose keys list the pair.
CREATE OR REPLACE TEMP TABLE listed AS
SELECT LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r, BIT_OR(1 << a.g) AS mask
FROM key_blocks AS a
JOIN key_blocks AS b ON a.g = b.g AND a.key = b.key AND a.id <> b.id AND (NOT b.in_batch OR a.id < b.id)
WHERE a.in_batch AND a.n < v_oversized
GROUP BY l, r;

CREATE OR REPLACE TEMP TABLE level_bits AS
-- run_records counts the run's records. v_outside counts those a lookup didn't read.
WITH size AS (SELECT COUNT(*) + v_outside AS run_records FROM `YOUR_PROJECT.nayose`.records),
rate AS (  -- λ is a per-pair rate, so it is rescaled to the run's size, as em.fitted rescales it
  SELECT LEAST(f.probability * (f.fit_records - 1) / GREATEST(size.run_records - 1, 1), `YOUR_PROJECT.nayose`.lambda_cap()) AS rate
  FROM `YOUR_PROJECT.nayose`.fit AS f, size
),
prior AS (  -- the prior is fit's own if the run has as many records as when fit ran, else the rescaled λ's bits
  SELECT IF(f.records = size.run_records, f.prior_bits, LOG(rate.rate / (1 - rate.rate), 2)) AS prior_bits
  FROM `YOUR_PROJECT.nayose`.fit AS f, size, rate
)
SELECT
  (SELECT prior_bits FROM prior) AS prior_bits,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'name' ORDER BY gamma)) AS name,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'company' ORDER BY gamma)) AS company,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'address' ORDER BY gamma)) AS address,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'phone' ORDER BY gamma)) AS phone,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'cif' ORDER BY gamma)) AS cif,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'birth' ORDER BY gamma)) AS birth,
  -- Each *_after is the most bits a fuzzy comparison can still earn once its leading equalities fail.
  (SELECT MAX(bits) FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'name' AND gamma <= 3) AS name_after,
  (SELECT MAX(bits) FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'company' AND gamma <= 1) AS company_after;


-- 4. The gate. A block of v_oversized records or more is listed only if a sample of its pairs holds a pair with
--    v_search_floor points or more. The sample pairs the block's first v_oversized batch records, by hash, with its
--    first v_oversized records. It leaves out the pairs another block already listed, and it is scored as the run
--    scores. So a block of 200 records whose batch holds 10 gives at most 10 × 64 sampled pairs, where its pairs
--    touching the batch number about 10 × 200.
--    A big block holds few true matches. A placeholder makes no key, as records.sql blanks it first, so a big block
--    is a crowded value that records.sql's test let through: a dummy phone held by too few customers, say.
CREATE OR REPLACE TEMP TABLE gate_pairs AS
WITH ranked AS (  -- nth_in_block is a record's place in its block by hash, and nth_in_batch its place among the batch's
  SELECT g, key, id, in_batch,
         ROW_NUMBER() OVER (PARTITION BY g, key ORDER BY `YOUR_PROJECT.nayose`.er_hash(id)) AS nth_in_block,
         IF(in_batch, ROW_NUMBER() OVER (PARTITION BY g, key, in_batch ORDER BY `YOUR_PROJECT.nayose`.er_hash(id)), NULL) AS nth_in_batch
  FROM key_blocks WHERE n >= v_oversized
)
SELECT DISTINCT a.g, a.key, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
FROM ranked AS a JOIN ranked AS b ON a.g = b.g AND a.key = b.key AND a.id <> b.id
WHERE a.nth_in_batch <= v_oversized AND b.nth_in_block <= v_oversized
  AND NOT EXISTS (SELECT 1 FROM listed AS seen WHERE seen.l = LEAST(a.id, b.id) AND seen.r = GREATEST(a.id, b.id));

CREATE OR REPLACE TEMP TABLE gated AS
-- gate_scored holds each sampled pair that the bound keeps, with its points. name_score is name_level's argument.
-- BigQuery has been seen to compute a SQL function's arguments once, before its body, so name_score runs once a pair
-- here; this is observed behaviour, not documented.
WITH gate_scored AS (
  SELECT p.l, p.r,
         `YOUR_PROJECT.nayose`.points_of(`YOUR_PROJECT.nayose`.name_level(x, y, `YOUR_PROJECT.nayose`.name_score(x, y)), `YOUR_PROJECT.nayose`.gamma_company(x, y), `YOUR_PROJECT.nayose`.gamma_address(x, y), `YOUR_PROJECT.nayose`.gamma_phone(x, y),
                   `YOUR_PROJECT.nayose`.gamma_cif(x, y), `YOUR_PROJECT.nayose`.gamma_birth(x, y), w) AS points
  FROM (SELECT DISTINCT l, r FROM gate_pairs) AS p JOIN `YOUR_PROJECT.nayose`.compared AS x ON x.id = p.l JOIN `YOUR_PROJECT.nayose`.compared AS y ON y.id = p.r
  CROSS JOIN level_bits AS w
  WHERE `YOUR_PROJECT.nayose`.could_reach(`YOUR_PROJECT.nayose`.bound_of(x, y, w), v_search_floor)
),
-- sampled counts every sampled pair of a block, those the bound dropped among them. best and hits read only the pairs
-- scored.
stats AS (
  SELECT p.g, p.key, COUNT(*) AS sampled, MAX(s.points) AS best,
         COUNT(CASE WHEN s.points >= v_search_floor THEN 1 END) AS hits
  FROM gate_pairs AS p LEFT JOIN gate_scored AS s USING (l, r) GROUP BY p.g, p.key
)
SELECT z.g, z.key, z.n AS records, `YOUR_PROJECT.nayose`.pairs_of(z.n) AS pairs,
       COALESCE(s.sampled, 0) AS sampled, s.best, COALESCE(s.hits, 0) AS hits,
       CASE WHEN COALESCE(s.hits, 0) > 0 THEN 'listed' WHEN COALESCE(s.sampled, 0) = 0 THEN 'skipped: other keys list its sampled pairs'
            ELSE 'skipped: no sampled pair reaches the floor' END AS verdict
FROM (SELECT DISTINCT g, key, n FROM key_blocks WHERE n >= v_oversized) AS z
LEFT JOIN stats AS s ON s.g = z.g AND s.key = z.key;


-- 5. The candidates. They are the pairs in listed, and every pair of a listed oversized block that touches the batch.
--    Each comes with the generators whose keys listed it.
CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.cands AS
WITH listed_or_gated AS (
  SELECT l, r, mask FROM listed
  UNION ALL
  SELECT LEAST(a.id, b.id), GREATEST(a.id, b.id), 1 << a.g
  FROM key_blocks AS a
  JOIN key_blocks AS b ON a.g = b.g AND a.key = b.key AND a.id <> b.id AND (NOT b.in_batch OR a.id < b.id)
  JOIN gated AS z ON z.g = a.g AND z.key = a.key
  WHERE a.in_batch AND z.verdict = 'listed'
),
pairs AS (SELECT l, r, BIT_OR(mask) AS mask FROM listed_or_gated GROUP BY l, r),
generator_names AS (  -- each mask becomes the generators' names, in their order, joined by +
  -- A join, not a subquery: BigQuery runs no subquery that reads a table by its outer row's mask (no equality).
  SELECT m.mask, STRING_AGG(gen.name, '+' ORDER BY gen.g) AS generators
  FROM (SELECT DISTINCT mask FROM pairs) AS m
  JOIN generators AS gen ON (m.mask >> gen.g) & 1 = 1
  GROUP BY m.mask
)
SELECT pairs.l, pairs.r, generator_names.generators FROM pairs JOIN generator_names USING (mask);


-- 6. The scores. Each candidate that the bound keeps, and every rule pair, gets its levels and its points. The pairs
--    with v_keep_from points or more are kept, and so is every rule pair. named is true if a name was compared, the
--    person's or the company's. The batch's pairs are added to the run's scored. Each pair is scored once, in the
--    batch that brings its later record, and again in each job that makes one of its records again.
CREATE OR REPLACE TEMP TABLE batch_pairs AS  -- each of the batch's candidates and rule pairs appears once
WITH rule_hits AS (
  SELECT a.i AS rule_rank, rules.rule, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
  FROM rule_blocks AS a
  JOIN rule_blocks AS b ON a.i = b.i AND a.key = b.key AND a.id <> b.id AND (NOT b.in_batch OR a.id < b.id)
  -- A function given a row reads all of its columns, so x and y are rows of compared, which holds only the columns
  -- the comparisons read.
  JOIN `YOUR_PROJECT.nayose`.compared AS x ON x.id = a.id JOIN `YOUR_PROJECT.nayose`.compared AS y ON y.id = b.id
  JOIN rules ON rules.i = a.i
  WHERE a.in_batch AND a.n < v_oversized
    AND CASE rules.rule  -- These are the fuzzy rules' tests. The exact rules (X1-X6) test their keys alone.
          WHEN 'F1_NAME~_ADDRCD_PHONE' THEN `YOUR_PROJECT.nayose`.near_name(x, y)
          WHEN 'F2_NAME~_ADDRESS~_PHONE' THEN `YOUR_PROJECT.nayose`.near_name(x, y) AND `YOUR_PROJECT.nayose`.near_address(x, y)
          WHEN 'F3_NAME~_CIF' THEN `YOUR_PROJECT.nayose`.near_name(x, y)
          WHEN 'F4_NAME_ADDRCD_PHONE~' THEN `YOUR_PROJECT.nayose`.near_phone(x, y)
          WHEN 'F5_COMPANY~_PHONE_POSTAL' THEN `YOUR_PROJECT.nayose`.near_company(x, y)
          WHEN 'F6_COMPANY~_ADDRCD_PHONE' THEN `YOUR_PROJECT.nayose`.near_company(x, y)
          ELSE TRUE END
),
rule_pairs AS (  -- each pair a rule finds, with the first rule in order that finds it (the least rule_rank)
  SELECT l, r, MIN_BY(rule, rule_rank) AS rule FROM rule_hits GROUP BY l, r
)
SELECT l, r, c.generators, p.rule FROM `YOUR_PROJECT.nayose`.cands AS c FULL JOIN rule_pairs AS p USING (l, r);

CREATE OR REPLACE TEMP TABLE batch_scored AS
WITH in_bound AS (  -- in_bound computes the names' Jaro–Winkler (s_name) once for each pair the bound keeps
  SELECT p.l, p.r, p.generators, p.rule, x, y, `YOUR_PROJECT.nayose`.name_score(x, y) AS s_name
  FROM batch_pairs AS p JOIN `YOUR_PROJECT.nayose`.compared AS x ON x.id = p.l JOIN `YOUR_PROJECT.nayose`.compared AS y ON y.id = p.r CROSS JOIN level_bits AS w
  WHERE p.rule IS NOT NULL OR `YOUR_PROJECT.nayose`.could_reach(`YOUR_PROJECT.nayose`.bound_of(x, y, w), v_keep_from)
),
levelled AS (
  SELECT l, r, generators, rule, `YOUR_PROJECT.nayose`.name_level(x, y, s_name) AS gamma_name, `YOUR_PROJECT.nayose`.gamma_company(x, y) AS gamma_company,
         `YOUR_PROJECT.nayose`.gamma_address(x, y) AS gamma_address, `YOUR_PROJECT.nayose`.gamma_phone(x, y) AS gamma_phone, `YOUR_PROJECT.nayose`.gamma_cif(x, y) AS gamma_cif,
         `YOUR_PROJECT.nayose`.gamma_birth(x, y) AS gamma_birth
  FROM in_bound
),
weighed AS (
  SELECT lv.*,
         `YOUR_PROJECT.nayose`.points_of(gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth, w) AS points
  FROM levelled AS lv CROSS JOIN level_bits AS w
)
SELECT
  l AS id_l, r AS id_r, points,
  `YOUR_PROJECT.nayose`.probability_of(points) AS match_probability,
  generators, rule, (gamma_name >= 0 OR gamma_company >= 0) AS named,
  gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth
FROM weighed
WHERE points >= v_keep_from OR rule IS NOT NULL;

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.scored AS SELECT * FROM batch_scored WHERE FALSE;
IF v_condition_2 THEN

-- The pairs a record made again had leave scored, as batch_scored holds them scored again. A pair that its keys or
-- rules no longer find, or that now scores under v_keep_from, is not kept. On BigQuery this DELETE bills scored whole,
-- so only an update that finds a new placeholder runs it.
DELETE FROM `YOUR_PROJECT.nayose`.scored
WHERE id_l IN (SELECT id FROM changed WHERE redone) OR id_r IN (SELECT id FROM changed WHERE redone);
END IF;

INSERT INTO `YOUR_PROJECT.nayose`.scored SELECT * FROM batch_scored;
-- The decide job stores people's decisions on pairs and makes the entities again from them. The decisions come in
-- given, a match table that people filled in. They are stored with the run's earlier decisions, and each pair's latest
-- decision is its standing. The entities are the connected components of the pairs whose latest decision is match
-- (entities_of, nayose/entities.py), and each is named by its smallest ID. So a later no_match on a pair parts what
-- only that pair joined. Nothing merges by itself, so a record that no decision joins is an entity alone. A build and
-- an update run this file without v_given, to make their entities from the decisions the run holds: they skip
-- sections 1 and 2, which read given. O(D + N) for D decisions.
--
-- Reads: given, the job's table of id_l, id_r, decision and why (with v_given alone), records, and decisions if the
-- run has any.
-- Values: given, TRUE if the job was given decisions. A blank value is one that `YOUR_PROJECT.nayose`.blank() finds (functions.sql): spaces
-- alone, of any width.
-- Writes: decisions (each decision that changed its pair's standing, with its round, and each pair's latest flagged)
-- and gold (each record's entity, what joined it, its kind and its entity's kind). A round is one call of this job.

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.decisions (id_l STRING, id_r STRING, decision STRING, why STRING, round INT64, latest BOOL);


-- 3. Each record is its own entity until the pairs whose latest decision is match join it to others. Only pairs of
--    this run's records join, because a decision kept from an earlier run may name records the run no longer holds.
--    resolved_by is review if people's decisions put the record with another record. entity_kind, the entity's
--    kind, is 2 (company) if any of its records is a company. It is 1 (person) if none of its records leans company
--    (kind_p under 0.5) and one is a person, and 0 (not sure) otherwise.
-- shortcut: entities_of takes every match decision in one call, a few MB for each 100,000 decisions. Past millions of
-- decisions, compute the components by label propagation in SQL.

-- joined is a table, not a WITH in gold: gold reads placed twice, and BigQuery runs a WITH once each time it is read.
CREATE OR REPLACE TEMP TABLE joined AS  -- each record that a match decision joins, with its entity
-- asked holds what entities_of is asked, as one JSON text: the pairs whose latest decision is match, both of whose
-- records the run holds.
WITH asked AS (
  SELECT TO_JSON_STRING(STRUCT(ARRAY_AGG(STRUCT(d.id_l AS l, d.id_r AS r)) AS pairs)) AS pairs FROM `YOUR_PROJECT.nayose`.decisions AS d
  WHERE d.latest AND d.decision = 'match' AND d.id_l IN (SELECT id FROM `YOUR_PROJECT.nayose`.records) AND d.id_r IN (SELECT id FROM `YOUR_PROJECT.nayose`.records)
)
SELECT JSON_VALUE(e, '$.id') AS id, JSON_VALUE(e, '$.entity') AS entity
FROM asked, UNNEST(JSON_QUERY_ARRAY(`YOUR_PROJECT.nayose`.entities_of(asked.pairs))) AS e;

CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.gold CLUSTER BY id AS  -- a lookup reads gold by its records' IDs
WITH placed AS (
  SELECT rec.id, COALESCE(j.entity, rec.id) AS entity, rec.kind, rec.kind_p, rec.kind_by, rec.kind_flagged
  FROM `YOUR_PROJECT.nayose`.records AS rec LEFT JOIN joined AS j USING (id)
),
entities AS (
  SELECT entity, COUNT(*) AS n,
         CASE WHEN LOGICAL_OR(kind = 2) THEN 2
              WHEN COALESCE(MAX(kind_p), 0) < CAST(0.5 AS FLOAT64) AND LOGICAL_OR(kind = 1) THEN 1
              ELSE 0 END AS entity_kind
  FROM placed GROUP BY entity
)
SELECT p.id, p.entity, IF(e.n > 1, 'review', NULL) AS resolved_by,
       p.kind, p.kind_p, p.kind_by, p.kind_flagged, e.entity_kind
FROM placed AS p JOIN entities AS e USING (entity);
-- This file computes report.txt's numbers, which tell what the run holds and how its latest batch went. No number
-- holds a record's value. nayose.report sets them out as report.txt. O(N·F) for the fields' fill, and O(C) over the
-- batch's pairs.
--
-- Reads: records, this_batch, set_aside, gold, decisions, cands, batch_pairs and batch_scored (score.sql), key_blocks,
-- gated and generators. nayose.report_text reads placeholders, model and fit itself.
-- Values:
--   v_looks      as JSON, the regular expression that each field's values look like (config.toml [report.looks],
--               and for company_name the legal forms)
--   v_edges      the points at which each score band starts
--   v_floor      the review floor, in points
--   v_oversized  how many records make a block oversized
--   v_sample_records, v_patterns_shown   the records FIELDS samples, and the patterns each band shows (config.toml
--               [report])
-- Writes (read by nayose.report_text, here or after a BigQuery procedure): report_counts, report_fields,
-- report_scores, report_patterns, report_generators, report_entities.


-- report_counts holds one row of counts about the run, its latest batch, its entities and kinds, its oversized
-- blocks, and each field's filled records.
CREATE OR REPLACE TEMP TABLE report_counts AS
SELECT
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.records) AS records,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.records WHERE batch = (SELECT batch FROM this_batch)) AS added,
  (SELECT batch FROM this_batch) AS batch,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.set_aside) AS set_aside,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.cands) AS candidates,
  (SELECT COUNT(*) FROM batch_scored) AS scored,
  (SELECT COUNT(*) FROM batch_scored WHERE rule IS NOT NULL) AS ruled,
  (SELECT COUNT(DISTINCT entity) FROM `YOUR_PROJECT.nayose`.gold) AS entities,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE resolved_by = 'review') AS by_people,
  (SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM `YOUR_PROJECT.nayose`.gold GROUP BY entity)) AS largest,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.decisions WHERE latest) AS decided,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE kind = 2) AS companies, (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE kind = 1) AS persons,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE kind = 0) AS unsure,
  (SELECT COUNT(DISTINCT entity) FROM `YOUR_PROJECT.nayose`.gold WHERE entity_kind = 2) AS company_entities,
  (SELECT COUNT(DISTINCT entity) FROM `YOUR_PROJECT.nayose`.gold WHERE entity_kind = 1) AS person_entities,
  (SELECT COUNT(DISTINCT entity) FROM `YOUR_PROJECT.nayose`.gold WHERE entity_kind = 0) AS unsure_entities,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE kind_flagged) AS flagged,
  (SELECT COUNT(*) FROM gated WHERE verdict = 'listed') AS oversized_listed,
  (SELECT COUNT(*) FROM gated WHERE verdict <> 'listed') AS oversized_skipped,
  COUNT(full_name) AS full_name, COUNT(person_name) AS person_name, COUNT(given_name) AS given_name,
  COUNT(company_name) AS company_name, COUNT(any_name) AS any_name, COUNT(address) AS address,
  COUNT(address_code) AS address_code, COUNT(postal_code) AS postal_code, COUNT(prefecture) AS prefecture,
  COUNT(town_code) AS town_code, COUNT(city) AS city, COUNT(phone) AS phone, COUNT(customer_id) AS customer_id,
  COUNT(birth_date) AS birth_date
FROM `YOUR_PROJECT.nayose`.records;

-- report_fields describes each field on a sample of v_sample_records records, chosen by hash so that the sample is the
-- same whatever the rows' order. It gives the share of a field's filled values that match its look, a regex
-- (looks_right), the share that its most common value holds (top_value), the share with no letter or digit
-- (no_letters), and the values' mean and longest length.
CREATE OR REPLACE TEMP TABLE report_fields AS
WITH sample AS (SELECT * FROM `YOUR_PROJECT.nayose`.records ORDER BY `YOUR_PROJECT.nayose`.er_hash(id) LIMIT 10000),
sampled_values AS (
  SELECT 'full_name' AS field, full_name AS v FROM sample UNION ALL SELECT 'person_name', person_name FROM sample
  UNION ALL SELECT 'given_name', given_name FROM sample UNION ALL SELECT 'company_name', company_name FROM sample
  UNION ALL SELECT 'any_name', any_name FROM sample UNION ALL SELECT 'address', address FROM sample
  UNION ALL SELECT 'address_code', address_code FROM sample UNION ALL SELECT 'postal_code', postal_code FROM sample
  UNION ALL SELECT 'prefecture', prefecture FROM sample UNION ALL SELECT 'town_code', town_code FROM sample
  UNION ALL SELECT 'city', city FROM sample UNION ALL SELECT 'phone', phone FROM sample
  UNION ALL SELECT 'customer_id', customer_id FROM sample UNION ALL SELECT 'birth_date', birth_date FROM sample
),
top AS (
  SELECT field, MAX(n) / SUM(n) AS top_value
  FROM (SELECT field, v, COUNT(*) AS n FROM sampled_values WHERE v IS NOT NULL GROUP BY field, v)
  GROUP BY field
),
-- looks holds each field's look from v_looks, one path a field: BigQuery reads a JSON path only as written out.
looks AS (
  SELECT 'full_name' AS field, JSON_VALUE(v_looks, '$.full_name') AS look
  UNION ALL SELECT 'person_name', JSON_VALUE(v_looks, '$.person_name')
  UNION ALL SELECT 'given_name', JSON_VALUE(v_looks, '$.given_name')
  UNION ALL SELECT 'company_name', JSON_VALUE(v_looks, '$.company_name')
  UNION ALL SELECT 'any_name', JSON_VALUE(v_looks, '$.any_name')
  UNION ALL SELECT 'address', JSON_VALUE(v_looks, '$.address')
  UNION ALL SELECT 'address_code', JSON_VALUE(v_looks, '$.address_code')
  UNION ALL SELECT 'postal_code', JSON_VALUE(v_looks, '$.postal_code')
  UNION ALL SELECT 'prefecture', JSON_VALUE(v_looks, '$.prefecture')
  UNION ALL SELECT 'town_code', JSON_VALUE(v_looks, '$.town_code')
  UNION ALL SELECT 'city', JSON_VALUE(v_looks, '$.city')
  UNION ALL SELECT 'phone', JSON_VALUE(v_looks, '$.phone')
  UNION ALL SELECT 'customer_id', JSON_VALUE(v_looks, '$.customer_id')
  UNION ALL SELECT 'birth_date', JSON_VALUE(v_looks, '$.birth_date')
)
SELECT
  field, AVG(CAST(REGEXP_CONTAINS(v, look) AS INT64)) AS looks_right,
  ANY_VALUE(top.top_value) AS top_value, AVG(CAST(NOT REGEXP_CONTAINS(v, r'[\pL\pN]') AS INT64)) AS no_letters,
  AVG(LENGTH(v)) AS length, MAX(LENGTH(v)) AS longest
FROM sampled_values LEFT JOIN top USING (field) LEFT JOIN looks USING (field)
GROUP BY field;

-- report_scores counts the batch's pairs by band. A pair scored at 0 points or more is in band k if k of v_edges are
-- at or below its points. Band -1 counts the rest of the batch's pairs (batch_pairs). With [score] keep_from at 0,
-- those are the pairs that scored below 0 points, and the pairs that the bound kept from being scored.
CREATE OR REPLACE TEMP TABLE report_scores AS
SELECT band, COUNT(*) AS pairs
FROM (SELECT ARRAY_LENGTH(ARRAY(SELECT e FROM UNNEST(v_edges) AS e WHERE e <= points)) AS band
      FROM batch_scored WHERE points >= 0)
GROUP BY band
UNION ALL
SELECT -1, (SELECT COUNT(*) FROM batch_pairs) - (SELECT COUNT(*) FROM batch_scored WHERE points >= 0);

-- report_patterns splits the batch's pairs at 0 points or more into two bands, below the review floor (v_floor) and
-- from it up. For each band it keeps the v_patterns_shown most common patterns of levels, each with its pairs and their
-- mean points. It also gives the band's total pairs and how many patterns the band holds (patterns).
CREATE OR REPLACE TEMP TABLE report_patterns AS
WITH p AS (
  SELECT points >= v_floor AS up, gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth,
         COUNT(*) AS n, AVG(points) AS mean_points
  FROM batch_scored WHERE points >= 0
  GROUP BY up, gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth
)
SELECT * FROM (
  SELECT *, SUM(n) OVER (PARTITION BY up) AS total, COUNT(*) OVER (PARTITION BY up) AS patterns,
         ROW_NUMBER() OVER (PARTITION BY up ORDER BY n DESC, mean_points DESC, gamma_name, gamma_company,
                                                     gamma_address, gamma_phone, gamma_cif, gamma_birth) AS nth
  FROM p
) WHERE nth <= v_patterns_shown;

-- report_generators describes each generator that the run uses. pairs counts the candidates its keys listed, each
-- pair once, even if a deletion generator listed the pair through several of its deletions. largest is the size of
-- its largest block that holds a batch record, and oversized counts its blocks of v_oversized records or more.
CREATE OR REPLACE TEMP TABLE report_generators AS
WITH listing AS (SELECT name, COUNT(*) AS pairs FROM `YOUR_PROJECT.nayose`.cands, UNNEST(SPLIT(generators, '+')) AS name GROUP BY name),
blocks AS (
  SELECT g, MAX(n) AS largest, COUNT(DISTINCT CASE WHEN n >= v_oversized THEN key END) AS oversized
  FROM key_blocks GROUP BY g
)
SELECT gen.g, gen.name, COALESCE(ls.pairs, 0) AS pairs, COALESCE(b.largest, 0) AS largest,
       COALESCE(b.oversized, 0) AS oversized
FROM generators AS gen LEFT JOIN listing AS ls USING (name) LEFT JOIN blocks AS b USING (g)
WHERE gen.used;

-- report_entities counts the entities of each size.
CREATE OR REPLACE TEMP TABLE report_entities AS
SELECT n AS size, COUNT(*) AS entities FROM (SELECT COUNT(*) AS n FROM `YOUR_PROJECT.nayose`.gold GROUP BY entity) GROUP BY n;
CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.method AS SELECT 'f4db6e8349053bef0bde3d9fe7f003af26b4d09a642fbac3658a623a441c2c36' AS fingerprint;
END;

CREATE OR REPLACE PROCEDURE `YOUR_PROJECT.nayose`.update() OPTIONS (strict_mode = FALSE)
BEGIN
DECLARE v_nulls STRING DEFAULT '^[ \\x{3000}]*(?:NULL|null|Null|\\\\N|NaN|nan|None|none|N/A|n/a|\\#N/A|\\-|－)[ \\x{3000}]*$|^[\\t-\\r\\x{1c}-\\x{20}\\x{85}\\x{a0}\\x{1680}\\x{2000}-\\x{200a}\\x{2028}\\x{2029}\\x{202f}\\x{205f}\\x{3000}]*$';
DECLARE v_hiragana STRING DEFAULT 'ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖ';
DECLARE v_katakana STRING DEFAULT 'ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶ';
DECLARE v_katakana_block STRING DEFAULT '゠ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶヷヸヹヺ・ーヽヾヿ';
DECLARE v_one_byte STRING DEFAULT '\U00000001\U00000002\U00000003\U00000004\U00000005\U00000006\U00000007\U00000008\U00000009\U0000000a\U0000000b\U0000000c\U0000000d\U0000000e\U0000000f\U00000010\U00000011\U00000012\U00000013\U00000014\U00000015\U00000016\U00000017\U00000018\U00000019\U0000001a\U0000001b\U0000001c\U0000001d\U0000001e\U0000001f !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`';
DECLARE v_kana_fold_from STRING DEFAULT 'ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポヴァィゥェォッャュョヮヵヶヲー';
DECLARE v_kana_fold_to STRING DEFAULT 'カキクケコサシスセソタチツテトハヒフヘホハヒフヘホフアイウエオツヤユヨワカケオウ';
DECLARE v_legal_regex STRING DEFAULT 'コクリツケンキュウカイハツホウジン|コクリツケンキユウカイハツホウジン|ユウゲンセキニンチュウカンホウジン|ユウゲンセキニンチユウカンホウジン|トクテイヒエイリカツドウホウジン|ムゲンセキニンチュウカンホウジン|ムゲンセキニンチユウカンホウジン|シャカイホケンロウムシホウジン|シヤカイホケンロウムシホウジン|ドクリツギョウセイホウジン|ドクリツギヨウセイホウジン|イッパンザイダンホウジン|イッパンシャダンホウジン|イツパンザイダンホウジン|イツパンシヤダンホウジン|イリョウホウジンザイダン|イリョウホウジンシャダン|イリヨウホウジンザイダン|イリヨウホウジンシヤダン|ギョウセイショシホウジン|ギヨウセイシヨシホウジン|コウエキザイダンホウジン|コウエキシャダンホウジン|コウエキシヤダンホウジン|コウリツダイガクホウジン|コクリツダイガクホウジン|カンリクミアイホウジン|シャカイフクシホウジン|シヤカイフクシホウジン|ノウジクミアイホウジン|コウセイホゴホウジン|シホウショシホウジン|シホウシヨシホウジン|シュウキョウホウジン|シユウキヨウホウジン|特定非営利活動法人|イリョウホウジン|イリヨウホウジン|カブシキガイシャ|カブシキガイシヤ|ガッコウホウジン|ガツコウホウジン|ゴウドウガイシャ|ゴウドウガイシヤ|ゴウメイガイシャ|ゴウメイガイシヤ|ゼイリシホウジン|ベンゴシホウジン|ユウゲンガイシャ|ユウゲンガイシヤ|ゴウシガイシャ|ゴウシガイシヤ|ソウゴガイシャ|ソウゴガイシヤ|一般社団法人|一般財団法人|公益社団法人|公益財団法人|医療法人社団|医療法人財団|社会福祉法人|\\(シホウ\\)|\\(ギヨ\\)|\\(ケン\\)|\\(ゼイ\\)|\\(ダイ\\)|\\(ノウ\\)|\\(ホゴ\\)|医療法人|合同会社|合名会社|合資会社|学校法人|宗教法人|有限会社|株式会社|相互会社|\\(カ\\)|\\(シ\\)|\\(ソ\\)|\\(ド\\)|\\(メ\\)|\\(ユ\\)|\\(同\\)|\\(名\\)|\\(有\\)|\\(株\\)|\\(資\\)|カ\\)|ユ\\)|^(?:シユウ|トクヒ|シホウ|チユウ|ザイ|シヤ|ガク|フク|ホゴ|ドク|ベン|ギヨ|ゼイ|ダイ|ノウ|ケン|カ|ユ|メ|シ|ド|ソ|イ)\\)|\\((?:シホウ|カンリ|ロウム|ギヨ|ゼイ|ダイ|ノウ|カ|ユ|メ|シ|ド|ソ|イ)$';
DECLARE v_prefecture_regex STRING DEFAULT '^(?:北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|埼玉県|千葉県|東京都|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)';
DECLARE v_flag_company ARRAY<STRING> DEFAULT ARRAY<STRING>['2'];
DECLARE v_name_line FLOAT64 DEFAULT CAST(0.99 AS FLOAT64);
DECLARE v_trust_flag BOOL DEFAULT FALSE;
DECLARE v_shared_name_column BOOL DEFAULT FALSE;
DECLARE v_ngram INT64 DEFAULT 3;
DECLARE v_intercept FLOAT64 DEFAULT CAST(3.2521136779937376 AS FLOAT64);
DECLARE v_placeholder_min INT64 DEFAULT 64;
DECLARE v_spread INT64 DEFAULT 10;
DECLARE v_crowd INT64 DEFAULT 64;
DECLARE v_lookup BOOL DEFAULT FALSE;
DECLARE v_generators ARRAY<STRING> DEFAULT ARRAY<STRING>['customer_id', 'phone_prefecture', 'phone_postal_area', 'phone_name_initial', 'person_name', 'company_name', 'company_name_deletions', 'person_name_deletions_postal_area', 'given_name_postal', 'address_phone', 'address_code_phone', 'address_name_initial', 'address_code_name_initial', 'given_name_address_code', 'customer_id_deletions', 'birth_date', 'given_name_phone', 'birth_date_deletions_prefecture', 'name_reading', 'phone_name_tail', 'postal_name_tail', 'postal_area_name_tail'];
DECLARE v_rules ARRAY<STRING> DEFAULT ARRAY<STRING>['X1_CIF_FULL_NAME', 'X2_CIF_COMPANY_NAME', 'X3_CIF_PHONE', 'X4_FULL_NAME_ADDRCD_PHONE', 'X5_COMPANY_NAME_ADDRCD_PHONE', 'F1_NAME~_ADDRCD_PHONE', 'F2_NAME~_ADDRESS~_PHONE', 'F3_NAME~_CIF', 'F4_NAME_ADDRCD_PHONE~', 'F5_COMPANY~_PHONE_POSTAL', 'F6_COMPANY~_ADDRCD_PHONE', 'X6_GIVEN_ADDRCD_PHONE'];
DECLARE v_keep_from FLOAT64 DEFAULT CAST(0.0 AS FLOAT64);
DECLARE v_search_floor FLOAT64 DEFAULT CAST(0.0 AS FLOAT64);
DECLARE v_oversized INT64 DEFAULT 64;
DECLARE v_outside INT64 DEFAULT 0;
DECLARE v_given BOOL DEFAULT FALSE;
DECLARE v_looks STRING DEFAULT '{"full_name": "^[ァ-ヴー・ｦ-ﾟ\\\\s\U00003000]+$", "person_name": "^[ァ-ヴー・ｦ-ﾟ\\\\s\U00003000]+$", "given_name": "^[ァ-ヴーｦ-ﾟ]{1,12}$", "any_name": "^[ァ-ヴー・ｦ-ﾟ\\\\s\U00003000()（）]+$", "address": "[都道府県市区町村].*[0-9０-９]", "address_code": "^[0-9]{5,}$", "postal_code": "^〒?[0-9０-９]{3}[-－]?[0-9０-９]{4}$", "prefecture": "^(北海道|東京都|京都府|大阪府|.{2,3}県)$", "town_code": "^[0-9]{11}$", "city": "[市区町村郡]$", "phone": "^[0-9]{4}$", "customer_id": "^[0-9]{8,}$", "birth_date": "^((19|20)?[0-9]{2})[-/.]?[01][0-9][-/.]?[0-3][0-9]$", "company_name": "コクリツケンキュウカイハツホウジン|コクリツケンキユウカイハツホウジン|ユウゲンセキニンチュウカンホウジン|ユウゲンセキニンチユウカンホウジン|トクテイヒエイリカツドウホウジン|ムゲンセキニンチュウカンホウジン|ムゲンセキニンチユウカンホウジン|シャカイホケンロウムシホウジン|シヤカイホケンロウムシホウジン|ドクリツギョウセイホウジン|ドクリツギヨウセイホウジン|イッパンザイダンホウジン|イッパンシャダンホウジン|イツパンザイダンホウジン|イツパンシヤダンホウジン|イリョウホウジンザイダン|イリョウホウジンシャダン|イリヨウホウジンザイダン|イリヨウホウジンシヤダン|ギョウセイショシホウジン|ギヨウセイシヨシホウジン|コウエキザイダンホウジン|コウエキシャダンホウジン|コウエキシヤダンホウジン|コウリツダイガクホウジン|コクリツダイガクホウジン|カンリクミアイホウジン|シャカイフクシホウジン|シヤカイフクシホウジン|ノウジクミアイホウジン|コウセイホゴホウジン|シホウショシホウジン|シホウシヨシホウジン|シュウキョウホウジン|シユウキヨウホウジン|特定非営利活動法人|イリョウホウジン|イリヨウホウジン|カブシキガイシャ|カブシキガイシヤ|ガッコウホウジン|ガツコウホウジン|ゴウドウガイシャ|ゴウドウガイシヤ|ゴウメイガイシャ|ゴウメイガイシヤ|ゼイリシホウジン|ベンゴシホウジン|ユウゲンガイシャ|ユウゲンガイシヤ|ゴウシガイシャ|ゴウシガイシヤ|ソウゴガイシャ|ソウゴガイシヤ|一般社団法人|一般財団法人|公益社団法人|公益財団法人|医療法人社団|医療法人財団|社会福祉法人|\\\\(シホウ\\\\)|\\\\(ギヨ\\\\)|\\\\(ケン\\\\)|\\\\(ゼイ\\\\)|\\\\(ダイ\\\\)|\\\\(ノウ\\\\)|\\\\(ホゴ\\\\)|医療法人|合同会社|合名会社|合資会社|学校法人|宗教法人|有限会社|株式会社|相互会社|\\\\(カ\\\\)|\\\\(シ\\\\)|\\\\(ソ\\\\)|\\\\(ド\\\\)|\\\\(メ\\\\)|\\\\(ユ\\\\)|\\\\(同\\\\)|\\\\(名\\\\)|\\\\(有\\\\)|\\\\(株\\\\)|\\\\(資\\\\)|カ\\\\)|ユ\\\\)|^(?:シユウ|トクヒ|シホウ|チユウ|ザイ|シヤ|ガク|フク|ホゴ|ドク|ベン|ギヨ|ゼイ|ダイ|ノウ|ケン|カ|ユ|メ|シ|ド|ソ|イ)\\\\)|\\\\((?:シホウ|カンリ|ロウム|ギヨ|ゼイ|ダイ|ノウ|カ|ユ|メ|シ|ド|ソ|イ)$"}';
DECLARE v_edges ARRAY<FLOAT64> DEFAULT ARRAY<FLOAT64>[CAST(-20.0 AS FLOAT64), CAST(-10.0 AS FLOAT64), CAST(0.0 AS FLOAT64), CAST(4.0 AS FLOAT64), CAST(6.0 AS FLOAT64), CAST(8.0 AS FLOAT64), CAST(10.0 AS FLOAT64), CAST(14.0 AS FLOAT64), CAST(18.0 AS FLOAT64)];
DECLARE v_floor FLOAT64 DEFAULT CAST(4.0 AS FLOAT64);
DECLARE v_sample_records INT64 DEFAULT 10000;
DECLARE v_patterns_shown INT64 DEFAULT 12;
DECLARE v_condition_1 BOOL DEFAULT FALSE;
DECLARE v_condition_2 BOOL DEFAULT FALSE;
DECLARE v_condition_3 BOOL DEFAULT FALSE;
SELECT IF((SELECT fingerprint FROM `YOUR_PROJECT.nayose`.method) IS DISTINCT FROM 'f4db6e8349053bef0bde3d9fe7f003af26b4d09a642fbac3658a623a441c2c36', ERROR('the method, its values or the mapping changed since the run was built: this code would read its tables, and score its batches, otherwise; build the run again'), 0);
-- This file maps the input's columns to the fields that records.sql reads. It is the mapping of the generated data,
-- whose columns design/generate.py writes. A deployment keeps its own mapping, in the same form, outside the
-- repository (in Secret Manager).
--
-- Every column is read through `YOUR_PROJECT.nayose`.read_value(functions.sql). It reads damaged values and null tokens (v_nulls, from
-- config.toml's [input] nulls) as missing, takes a list's first filled item and removes control characters. If its
-- second argument is TRUE, for a column of numbers, it also reads 12345.0 as 12345 and a number cut short in E
-- notation as missing.
-- A column that isn't text is cast to text first. A float column of codes, for example, is cast as
-- CAST(CAST(x AS INT64) AS STRING).
-- Each field takes the first of its sources, in order, whose columns are all filled. A source of two columns joins
-- them, as LAST_NAME_KANA || GIVEN_NAME_KANA does.
-- config.toml's [input] columns lists every column read here. A column that the file lacks is read as missing.

-- input_rows holds each distinct input row as the file gave it, with its ID read as mapped reads it (nayose_id).
-- records.sql sets aside rows from it as they were given, and counts its rows per ID to find an ID given with
-- different content.
CREATE OR REPLACE TEMP TABLE input_rows AS
SELECT DISTINCT `YOUR_PROJECT.nayose`.read_value(CONT_ID, TRUE, v_nulls) AS nayose_id, * FROM `YOUR_PROJECT.nayose.synthetic_records`;

CREATE OR REPLACE TEMP TABLE mapped AS
WITH source AS (
  SELECT
    `YOUR_PROJECT.nayose`.read_value(CONT_ID, TRUE, v_nulls)              AS id,
    `YOUR_PROJECT.nayose`.read_value(FULL_NAME_KANA, FALSE, v_nulls)      AS FULL_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(O_PERSON_NAME_KANA, FALSE, v_nulls)  AS O_PERSON_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(LAST_NAME_KANA, FALSE, v_nulls)      AS LAST_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(GIVEN_NAME_KANA, FALSE, v_nulls)     AS GIVEN_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(NYS_CNV_P_NAME_KANA, FALSE, v_nulls) AS NYS_CNV_P_NAME_KANA,
    `YOUR_PROJECT.nayose`.read_value(STD_ADDRESS, FALSE, v_nulls)         AS STD_ADDRESS,
    `YOUR_PROJECT.nayose`.read_value(ORIGINAL_ADDRESS, FALSE, v_nulls)    AS ORIGINAL_ADDRESS,
    `YOUR_PROJECT.nayose`.read_value(SOURCE_ADDR_CD, TRUE, v_nulls)       AS SOURCE_ADDR_CD,
    `YOUR_PROJECT.nayose`.read_value(POST_CD, TRUE, v_nulls)              AS POST_CD,
    `YOUR_PROJECT.nayose`.read_value(POST_CD_KANA, TRUE, v_nulls)         AS POST_CD_KANA,
    `YOUR_PROJECT.nayose`.read_value(ADDRESS_ONE, FALSE, v_nulls)         AS ADDRESS_ONE,
    `YOUR_PROJECT.nayose`.read_value(ADDR_CD, TRUE, v_nulls)              AS ADDR_CD,
    `YOUR_PROJECT.nayose`.read_value(ADDRESS_TWO, FALSE, v_nulls)         AS ADDRESS_TWO,
    `YOUR_PROJECT.nayose`.read_value(PHONE_NUM_4, TRUE, v_nulls)          AS PHONE_NUM_4,
    `YOUR_PROJECT.nayose`.read_value(CIF_ID, TRUE, v_nulls)               AS CIF_ID,
    `YOUR_PROJECT.nayose`.read_value(BIRTH_DATE, TRUE, v_nulls)           AS BIRTH_DATE,
    `YOUR_PROJECT.nayose`.read_value(PERSON_ORG_CODE, TRUE, v_nulls)      AS PERSON_ORG_CODE
  FROM `YOUR_PROJECT.nayose.synthetic_records`
)
SELECT
  id,
  FULL_NAME_KANA AS full_name,
  COALESCE(FULL_NAME_KANA, O_PERSON_NAME_KANA, LAST_NAME_KANA || GIVEN_NAME_KANA) AS person_name,
  GIVEN_NAME_KANA AS given_name,
  NYS_CNV_P_NAME_KANA AS company_name,
  COALESCE(FULL_NAME_KANA, O_PERSON_NAME_KANA, LAST_NAME_KANA || GIVEN_NAME_KANA, NYS_CNV_P_NAME_KANA) AS any_name,
  COALESCE(STD_ADDRESS, ORIGINAL_ADDRESS) AS address,
  SOURCE_ADDR_CD AS address_code,
  COALESCE(POST_CD, POST_CD_KANA) AS postal_code,
  ADDRESS_ONE AS prefecture,
  ADDR_CD AS town_code,
  ADDRESS_TWO AS city,
  PHONE_NUM_4 AS phone,
  CIF_ID AS customer_id,
  BIRTH_DATE AS birth_date,
  PERSON_ORG_CODE AS kind_flag
FROM source;
-- This is stage 1, records. It adds a batch of input records to the run's records. It sets aside the rows it can't
-- resolve, standardizes each field, decides each record's kind (person or company) and reads placeholders as
-- missing. Then it writes each record with the copies of its fields that the keys and comparisons read. A build is
-- a run's first batch.
-- It costs O(Δ·L) for a batch of Δ records whose values are L characters long, plus O(N) to count placeholders over
-- all N of the run's records.
-- Sections 3 and 4 are one statement, sided: section 3's CTEs decide each record's kind, and section 4's then keep
-- each name in the fields of the record's side.
--
-- A statement that follows a `-- when: <condition>` line runs only if the condition holds: run_file checks it locally,
-- and the deployed procedure wraps the statement in IF … END IF.
--
-- Reads:
--   input_rows and mapped, the batch as mapping.sql maps it;
--   name_weights, the name model (config/kind_names.npz);
--   the run's records and placeholders, which are empty before the run's first batch.
-- Values: config.toml's [records], and the regexes that nayose builds from its lists (legal_regex,
--   prefecture_regex). With v_lookup, the batch holds the records asked about (nayose.lookup). They are prepared
--   as the run's own records are, but none of their values becomes a placeholder, and every table is written as a
--   temporary table.
-- Writes:
--   set_aside, the batch's rows that are set aside, each with its reason;
--   placeholders, the run's placeholders and the new ones this batch brings;
--   records, one row per record with its fields, its kind, its copies and its batch.


-- 0. The run's records and placeholders start empty. This batch's number is one more than the last batch's, or 0 for
--    the run's first.
CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.records (
  id STRING, given_name STRING, any_name STRING, address STRING, address_code STRING, postal_code STRING,
  prefecture STRING, town_code STRING, city STRING, phone STRING, customer_id STRING, birth_date STRING,
  kind INT64, kind_p FLOAT64, kind_by STRING, kind_flagged BOOL, full_name STRING, person_name STRING,
  company_name STRING, person_name__kana_fold STRING, company_name__nfkc_strip_legal_form_kana_fold STRING,
  address__address STRING, postal_code__first3 STRING, any_name__initial STRING, given_name__kana_fold STRING,
  address__address_first3 STRING,
  person_name__kana_fold_long_vowel STRING, person_name__kana_fold_one_byte STRING,
  company_name__nfkc_strip_legal_form_kana_fold_one_byte STRING, address__address_one_byte_hash STRING,
  person_name__kana_fold_long_vowel_last3 STRING, person_name__kana_fold_letters_lo INT64,
  person_name__kana_fold_letters_hi INT64, customer STRING, batch INT64
) CLUSTER BY id;  -- On BigQuery, a lookup by ID then reads only the blocks that hold those IDs.;

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.placeholders (field STRING, value STRING, n INT64);

CREATE OR REPLACE TEMP TABLE this_batch AS SELECT COALESCE(MAX(batch) + 1, 0) AS batch FROM `YOUR_PROJECT.nayose`.records;


-- 1. This section sets aside the rows that can't be resolved. Rows identical in every column count once (mapping.sql's
--    input_rows). A row is set aside if it has no ID, if its ID is already in the run, or if another row gives
--    its ID with different content. An ID that is empty or whitespace alone, as Python counts whitespace, is no ID.
--    Since an ID already in the run is set aside, a batch given twice adds no record the second time. Every row of
--    an ID with different content is set aside, because the run can't tell which row is right.
--    The list of IDs held twice leaves out a missing ID, because a NULL in a NOT IN list fails the test for every row.

CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.set_aside AS
SELECT * EXCEPT (nayose_id),
  CASE WHEN nayose_id IS NULL OR `YOUR_PROJECT.nayose`.blank(nayose_id) THEN 'no ID'
       WHEN nayose_id IN (SELECT id FROM `YOUR_PROJECT.nayose`.records) THEN 'already in the run'
       ELSE 'the same ID with different content' END AS reason
FROM input_rows
WHERE nayose_id IS NULL
   OR `YOUR_PROJECT.nayose`.blank(nayose_id)
   OR nayose_id IN (SELECT id FROM `YOUR_PROJECT.nayose`.records)
   OR nayose_id IN (SELECT nayose_id FROM input_rows WHERE nayose_id IS NOT NULL
                    GROUP BY nayose_id HAVING COUNT(*) > 1);


-- 2. Each field is standardized by its chain of steps, in order. A value that its chain leaves empty is missing.
--    nfkc applies Unicode NFKC normalization.
--    katakana writes hiragana as katakana (v_hiragana to v_katakana).
--    strip_spaces removes every space, of any width.
--    strip_separators removes what people write between digits, as in 03-1234-5678 or (03) 1234-5678. These are
--    spaces, hyphens, dashes, minus signs, the long-vowel mark ー, slashes, dots, parentheses and 〒.
--    padded writes a one-digit part between separators with a leading zero, so 1990/1/2 reads as 1990/01/02, and
--    1990/1/12 and 1990/11/2 stay apart once the separators go (birth_date).
--    strip_legal_form removes a legal form (v_legal_regex).
--    kana_fold writes voiced kana as unvoiced, small kana as large, and ー as ウ (v_kana_fold_from to v_kana_fold_to).

CREATE OR REPLACE TEMP TABLE standardized AS
WITH admitted AS (  -- Each record that isn't set aside is admitted once.
  SELECT DISTINCT m.*
  FROM mapped AS m
  WHERE m.id IS NOT NULL
    AND NOT `YOUR_PROJECT.nayose`.blank(m.id)
    AND m.id NOT IN (SELECT id FROM `YOUR_PROJECT.nayose`.records)
    AND m.id NOT IN (SELECT nayose_id FROM input_rows WHERE nayose_id IS NOT NULL
                     GROUP BY nayose_id HAVING COUNT(*) > 1)
)
SELECT
  id,
  NULLIF(REGEXP_REPLACE(TRANSLATE(`YOUR_PROJECT.nayose`.nfkc(full_name), v_hiragana, v_katakana), r'[\s\x{3000}]+', ''), '') AS full_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(`YOUR_PROJECT.nayose`.nfkc(person_name), v_hiragana, v_katakana), r'[\s\x{3000}]+', ''), '') AS person_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(`YOUR_PROJECT.nayose`.nfkc(given_name), v_hiragana, v_katakana), r'[\s\x{3000}]+', ''), '') AS given_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(`YOUR_PROJECT.nayose`.nfkc(company_name), v_hiragana, v_katakana), r'[\s\x{3000}]+', ''), '') AS company_name,
  NULLIF(TRANSLATE(REGEXP_REPLACE(TRANSLATE(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(any_name), r'[\s\x{3000}]+', ''), v_hiragana, v_katakana),
                                  v_legal_regex, ''), v_kana_fold_from, v_kana_fold_to), '') AS any_name,
  NULLIF(address, '') AS address,
  NULLIF(address_code, '') AS address_code,
  NULLIF(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(postal_code), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '') AS postal_code,
  NULLIF(prefecture, '') AS prefecture,
  NULLIF(town_code, '') AS town_code,
  NULLIF(city, '') AS city,
  NULLIF(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(phone), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '') AS phone,
  NULLIF(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(customer_id), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '') AS customer_id,
  NULLIF(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.padded(`YOUR_PROJECT.nayose`.nfkc(birth_date)), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '')
    AS birth_date,
  NULLIF(kind_flag, '') AS kind_flag,
  any_name AS kind_name  -- Section 3 looks for a legal form in this name as written.
FROM admitted;


-- sided holds each record once, with its kind (section 3) and its names in the fields of its side (section 4).
CREATE OR REPLACE TEMP TABLE sided AS
-- 3. Each record's kind is 2 for a company, 1 for a person, or 0 if neither the engine nor the file's flag decides.
--    A legal form written in the name makes the record a company.
--    Otherwise the name model decides if it is at least name_line sure either way. The model is a logistic regression
--    on the character n-grams of the name as any_name holds it, in lower case. A name that reads as a person's never
--    overrides a flag that says company.
--    Otherwise the file's flag (kind_flag) decides. A flag in flag_company says company, and any other says person.
--    With trust_flag, the flag decides every record.
--    So, with p the name model's chance that the name is a company's (name_p) and line v_name_line:
--      the name                                    the flag           kind                kind_by
--      a written legal form, or p ≥ line           any                2                   engine
--      p ≤ 1 − line                                company            2                   flag
--      p ≤ 1 − line                                person, or none    1                   engine
--      between, or no name to read                 company or person  the flag's, 2 or 1  flag
--      between, or no name to read                 none               0                   engine
--      any, with trust_flag                        company or person  the flag's, 2 or 1  flag
--      any, with trust_flag                        none               0                   engine
--    A record's side is its kind, or, if its kind is 0, the kind it leans to (kind_p).
-- name_sums scores each distinct name once, since many records share a name: one row per distinct name that holds an
-- n-gram the model knows. As in the model's training, each n-gram counts once however often the name holds it, and an
-- n-gram the model doesn't know adds nothing, so a name with none has no row here, and judged reads its sum as 0.
WITH name_sums AS (
  SELECT grams.t, SUM(nw.coef) AS s
  FROM (
    SELECT DISTINCT t, SUBSTR(t, i, n) AS term
    FROM (SELECT DISTINCT LOWER(any_name) AS t FROM standardized WHERE any_name IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, v_ngram)) AS n,
      UNNEST(GENERATE_ARRAY(1, LENGTH(t) - n + 1)) AS i
  ) AS grams
  JOIN `YOUR_PROJECT.nayose`.name_weights AS nw ON nw.term = grams.term
  GROUP BY grams.t
),
-- judged and each CTE after it hold one row per record. written is TRUE if the name as written holds a legal form.
-- logit is the name model's log-odds that the name is a company's. flag is the file's flag as a kind: 2 company,
-- 1 person, or NULL if the file gives none.
judged AS (
  SELECT
    s.*,
    COALESCE(REGEXP_CONTAINS(NULLIF(TRANSLATE(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(kind_name), r'[\s\x{3000}]+', ''), v_hiragana, v_katakana), ''),
                             v_legal_regex), FALSE) AS written,
    IF(s.any_name IS NULL, NULL, v_intercept + COALESCE(sums.s, CAST(0 AS FLOAT64))) AS logit,
    CASE WHEN s.kind_flag IS NULL THEN NULL
         WHEN `YOUR_PROJECT.nayose`.trimmed(`YOUR_PROJECT.nayose`.nfkc(s.kind_flag))
              IN UNNEST(v_flag_company) THEN 2
         ELSE 1 END AS flag
  FROM standardized AS s
  LEFT JOIN name_sums AS sums ON sums.t = LOWER(s.any_name)
),
name_chance AS (  -- name_p is the chance that the name is a company's, or NULL if the model can read no name.
  -- The logistic is 1 / (1 + EXP(-logit)). EXP overflows past about 709.78, which BigQuery refuses, so for a logit
  -- under -700 it takes the form EXP(logit) / (1 + EXP(logit)), equal but for rounding. Every other logit keeps the
  -- first form, to the bit.
  SELECT *, IF(written, CAST(1 AS FLOAT64),
               IF(logit >= -700, 1 / (1 + EXP(-logit)), EXP(logit) / (1 + EXP(logit)))) AS name_p
  FROM judged
),
sure AS (  -- sure_kind is the engine's kind if the engine is sure (2 company, 1 person), and 0 if it isn't.
  SELECT *,
    -- With v_trust_flag the engine is never sure, so the file's flag decides every record.
    CASE WHEN kind_name IS NULL OR v_trust_flag THEN 0
         WHEN (written OR name_p >= v_name_line) THEN 2
         WHEN name_p <= 1 - v_name_line AND flag = 2 THEN 0  -- A person's name never overrides a company flag.
         WHEN name_p <= 1 - v_name_line THEN 1
         ELSE 0 END AS sure_kind
  FROM name_chance
),
-- The kind is the engine's if the engine is sure, and the file's flag if it isn't. kind_p is how far the record
-- leans to company, from 0 to 1: name_p, or with v_trust_flag the flag's 1 or 0. It is NULL if the record has no name
-- to judge, or, with v_trust_flag, no flag.
decided AS (
  SELECT *,
    CAST(IF(sure_kind <> 0, sure_kind, COALESCE(flag, 0)) AS INT64) AS kind,
    IF(kind_name IS NULL, NULL, IF(v_trust_flag, CAST(flag - 1 AS FLOAT64), name_p)) AS kind_p
  FROM sure
),
told AS (  -- each record with its kind, kind_p, kind_by and kind_flagged, and its side
  SELECT
    * EXCEPT (kind_flag, kind_name, written, logit, flag, name_p, sure_kind),
    IF(sure_kind = 0 AND flag IS NOT NULL, 'flag', 'engine') AS kind_by,
    (sure_kind <> 0 AND flag IS NOT NULL AND sure_kind <> flag) AS kind_flagged,
    -- The side tells section 4 which fields keep a name.
    CASE WHEN kind = 2 THEN 'company'
         WHEN kind = 1 THEN 'person'
         WHEN kind_p >= CAST(0.5 AS FLOAT64) THEN 'company'
         ELSE 'person' END AS side
  FROM decided
),
-- 4. A name counts once, even if it is in two fields. If a person field and the company field hold the same name
--    once kana_fold is applied, as they do when one column is mapped to both, the name is one piece of evidence. It is
--    kept only in the field on the record's side.
--    With shared_name_column, one column holds every name, a person's or a company's. Then a person field keeps its
--    name only if the record's side is person, and the company field only if the side is company.
routed AS (
  SELECT
    * EXCEPT (full_name, person_name, company_name),
    IF(v_shared_name_column AND side <> 'person', NULL, full_name) AS full_name,
    IF(v_shared_name_column AND side <> 'person', NULL, person_name) AS person_name,
    IF(v_shared_name_column AND side <> 'company', NULL, company_name) AS company_name
  FROM told
),
same AS (
  SELECT *,
    COALESCE(NULLIF(TRANSLATE(full_name, v_kana_fold_from, v_kana_fold_to), '')
             = NULLIF(TRANSLATE(company_name, v_kana_fold_from, v_kana_fold_to), ''), FALSE) AS same_full,
    COALESCE(NULLIF(TRANSLATE(person_name, v_kana_fold_from, v_kana_fold_to), '')
             = NULLIF(TRANSLATE(company_name, v_kana_fold_from, v_kana_fold_to), ''), FALSE) AS same_person
  FROM routed
)
SELECT
  * EXCEPT (full_name, person_name, company_name, same_full, same_person),
  IF(same_full AND side = 'company', NULL, full_name) AS full_name,
  IF(same_person AND side = 'company', NULL, person_name) AS person_name,
  IF((same_full OR same_person) AND side = 'person', NULL, company_name) AS company_name
FROM same;


-- 5. A placeholder is a value held by so many records that it can't be one entity's, so it is no evidence. Every
--    placeholder is read as missing.
--    For person_name, company_name, address_code, address, phone and birth_date, a value is crowded if it reaches
--    the field's bar and at least v_crowd customers hold it. The bar is v_placeholder_min records, or v_spread times the
--    field's records per value if that is more. A crowded value is a placeholder if its own pairs outnumber the pairs
--    that all the field's uncrowded values make together. With n a value's records, C(n, 2) = n(n − 1)/2 its pairs,
--    and records / values the field's filled records over its distinct values:
--      placeholder ⇔ n ≥ max(v_placeholder_min, ⌈v_spread · records / values⌉) ∧ customers ≥ v_crowd
--                    ∧ C(n, 2) > Σ C(m, 2) over the field's uncrowded values, m each one's records
--    A customer ID is a placeholder if it reaches its field's bar, n ≥ max(…) alone. Its customers and pairs aren't
--    tested.
--    Blanking one field's placeholder changes no other field's record counts. A person_name placeholder also blanks
--    full_name, given_name and any_name, but those fields aren't counted. A record's customer is its customer ID as
--    read, or its own ID if it has none, and records keeps it (customer), so a customer ID blanked later counts as it
--    did. Every field's placeholders are then found at once, and section 6 blanks them as it writes the records.
--    The run's placeholders stay, and each keeps n, the records that hold it, the batch's added. An update counts as a
--    build of the same records would: the run's records are stored with its placeholders blanked, so each run
--    placeholder counts by its n, in its field's records per value and pairs, and as crowded if it reaches the bar.
--    (Its customers only grow, so it holds as many as it did when found.) So a batch given twice changes nothing.
--    A run placeholder stays one even where a build of the run's records would no longer find it. With v_lookup, no
--    placeholder is found and no count changes.
-- known keeps the run's placeholders from before this batch, since placeholders is replaced below.
CREATE OR REPLACE TEMP TABLE known AS SELECT * FROM `YOUR_PROJECT.nayose`.placeholders;

CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.placeholders AS
-- counted holds the run's records and the batch's, each with its customer ('c' and 'r' keep a customer ID and a
-- record ID apart). The run's records were written with the run's placeholders already blanked; the batch's are as
-- read. Each step below names the one before it once or twice, as BigQuery computes a WITH again where it is named.
WITH counted AS (
  SELECT id, person_name, company_name, address_code, address, phone, birth_date, customer_id, customer
  FROM `YOUR_PROJECT.nayose`.records WHERE NOT v_lookup
  UNION ALL
  SELECT id, person_name, company_name, address_code, address, phone, birth_date, customer_id,
         COALESCE('c' || customer_id, 'r' || id)
  FROM sided
),
field_values AS (  -- each record's value of each field, with its customer
  SELECT 'person_name' AS field, person_name AS value, customer FROM counted
  UNION ALL SELECT 'company_name', company_name, customer FROM counted
  UNION ALL SELECT 'address_code', address_code, customer FROM counted
  UNION ALL SELECT 'address', address, customer FROM counted
  UNION ALL SELECT 'phone', phone, customer FROM counted
  UNION ALL SELECT 'birth_date', birth_date, customer FROM counted
  UNION ALL SELECT 'customer_id', customer_id, NULL FROM counted
),
value_counts AS (  -- Each value's records (n) and customers are counted.
  SELECT field, value, COUNT(*) AS n, COUNT(DISTINCT customer) AS customers
  FROM field_values WHERE value IS NOT NULL GROUP BY field, value
),
-- valued holds every value and every run placeholder (held), n its records now: a run placeholder's before this
-- batch, and the batch's.
valued AS (
  SELECT COALESCE(v.field, k.field) AS field, COALESCE(v.value, k.value) AS value,
         IF(k.field IS NULL, v.n, k.n + IF(v_lookup, 0, COALESCE(v.n, 0))) AS n, v.customers, k.field IS NOT NULL AS held
  FROM value_counts AS v FULL JOIN known AS k ON k.field = v.field AND k.value = v.value
),
-- Each field gets its bar (at_least), from its records per value, and the number of pairs that all its values make
-- together (all_pairs). A value held by n records makes n(n-1)/2 pairs.
field_bars AS (
  SELECT field, GREATEST(v_placeholder_min, CAST(CEIL(v_spread * SUM(n) / GREATEST(COUNT(*), 1)) AS INT64)) AS at_least,
         SUM(`YOUR_PROJECT.nayose`.pairs_of(n)) AS all_pairs
  FROM valued GROUP BY field
),
-- A value is crowded if it reaches the bar and enough customers hold it; a customer ID, or a run placeholder, needs
-- only the bar.
flagged AS (
  SELECT v.field, v.value, v.n, v.held, b.all_pairs,
         v.n >= b.at_least AND (v.field = 'customer_id' OR v.held OR v.customers >= v_crowd) AS crowded
  FROM valued AS v JOIN field_bars AS b USING (field)
),
crowded_pairs AS (SELECT field, SUM(`YOUR_PROJECT.nayose`.pairs_of(n)) AS pairs FROM flagged WHERE crowded GROUP BY field)
-- Every run placeholder stays. A crowded value is a new placeholder if its own pairs outnumber those of all the
-- field's values that aren't crowded.
SELECT f.field, f.value, f.n FROM flagged AS f LEFT JOIN crowded_pairs AS p USING (field)
WHERE f.held
   OR (NOT v_lookup AND f.crowded AND (f.field = 'customer_id' OR `YOUR_PROJECT.nayose`.pairs_of(f.n) > f.all_pairs - p.pairs));

-- new_placeholders holds the placeholders this batch found.
CREATE OR REPLACE TEMP TABLE new_placeholders AS
SELECT p.field, p.value, p.n FROM `YOUR_PROJECT.nayose`.placeholders AS p LEFT JOIN known AS k ON k.field = p.field AND k.value = p.value
WHERE k.field IS NULL;
SET v_condition_1 = (EXISTS(SELECT 1 FROM new_placeholders));
IF v_condition_1 THEN

-- 6. The records are written with the copies of their fields that the keys and comparisons read. Each copy is a chain
--    of steps from a field, and is named field__steps, as person_name__kana_fold is. The batch's records are
--    written, and so is every run's record that holds a placeholder this batch found. That record is made again with
--    the placeholder read as missing, and so are its copies.
--    These are the steps section 2 doesn't list:
--    address applies NFKC, writes 丁目, 番 or 番地 after a number as a dash, and drops 号 after a number
--    (numbers_dashed, functions.sql). It then keeps the address up to the first space after the street number
--    (up_to_street_number), which drops the building and room. Last, it removes every space and cuts the address's
--    own prefecture off its start. So 東京都千代田区丸の内1丁目2番3号
--    ABCビル5F becomes 千代田区丸の内1-2-3.
--    first3 and last3 keep a value's first or last three characters, and initial keeps its first character.
--    long_vowel writes a long vowel one way, so サトウ, サトオ and サトー read alike (kana_fold has made ー into ウ).

-- redone holds the run's records that hold a placeholder this batch found: their fields, without their copies. The
-- INSERT below makes their copies again, with the batch's.
CREATE OR REPLACE TEMP TABLE redone AS
SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
       birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
       company_name, customer, batch
FROM `YOUR_PROJECT.nayose`.records
WHERE person_name IN (SELECT value FROM new_placeholders WHERE field = 'person_name')
   OR company_name IN (SELECT value FROM new_placeholders WHERE field = 'company_name')
   OR address_code IN (SELECT value FROM new_placeholders WHERE field = 'address_code')
   OR address IN (SELECT value FROM new_placeholders WHERE field = 'address')
   OR phone IN (SELECT value FROM new_placeholders WHERE field = 'phone')
   OR birth_date IN (SELECT value FROM new_placeholders WHERE field = 'birth_date')
   OR customer_id IN (SELECT value FROM new_placeholders WHERE field = 'customer_id');
END IF;
IF NOT v_condition_1 THEN

-- If the batch found no placeholder, redone is empty, with the same columns, and no record is made again.
CREATE OR REPLACE TEMP TABLE redone AS
SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
       birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
       company_name, customer, batch
FROM `YOUR_PROJECT.nayose`.records WHERE FALSE;
END IF;
IF EXISTS (SELECT 1 FROM redone) THEN

-- The records made again leave the table here, and the INSERT below writes them anew.
DELETE FROM `YOUR_PROJECT.nayose`.records WHERE id IN (SELECT id FROM redone);
END IF;

INSERT INTO `YOUR_PROJECT.nayose`.records
-- made holds the batch's records and the run's records made again, with their fields but not yet their copies.
WITH made AS (
  SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
         birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
         company_name, COALESCE('c' || customer_id, 'r' || id) AS customer, (SELECT batch FROM this_batch) AS batch
  FROM sided
  UNION ALL
  SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
         birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
         company_name, customer, batch
  FROM redone
),
-- marked holds the records of made, person_placeholder TRUE if a record's person_name is a placeholder and
-- company_placeholder TRUE if its company_name is.
marked AS (
  SELECT *,
    person_name IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'person_name') AS person_placeholder,
    company_name IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'company_name') AS company_placeholder
  FROM made
),
-- Every placeholder is read as missing. A person_name placeholder also blanks full_name, given_name and any_name,
-- since those fields come from the same columns. A company_name placeholder blanks any_name only where the record
-- has no person_name, as any_name is the person's name where there is one (mapping.sql).
blanked AS (
  SELECT * EXCEPT (person_placeholder, company_placeholder) REPLACE (
    IF(person_placeholder, NULL, full_name) AS full_name,
    IF(person_placeholder, NULL, given_name) AS given_name,
    IF(person_placeholder OR (company_placeholder AND person_name IS NULL), NULL, any_name) AS any_name,
    IF(person_placeholder, NULL, person_name) AS person_name,
    IF(company_placeholder, NULL, company_name) AS company_name,
    IF(address_code IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'address_code'), NULL, address_code) AS address_code,
    IF(address IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'address'), NULL, address) AS address,
    IF(phone IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'phone'), NULL, phone) AS phone,
    IF(birth_date IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'birth_date'), NULL, birth_date) AS birth_date,
    IF(customer_id IN (SELECT value FROM `YOUR_PROJECT.nayose`.placeholders WHERE field = 'customer_id'), NULL, customer_id) AS customer_id)
  FROM marked
),
copies AS (
  SELECT
    *,
    NULLIF(TRANSLATE(person_name, v_kana_fold_from, v_kana_fold_to), '') AS person_name__kana_fold,
    NULLIF(TRANSLATE(REGEXP_REPLACE(`YOUR_PROJECT.nayose`.nfkc(company_name), v_legal_regex, ''), v_kana_fold_from, v_kana_fold_to), '')
      AS company_name__nfkc_strip_legal_form_kana_fold,
    NULLIF(REGEXP_REPLACE(REPLACE(`YOUR_PROJECT.nayose`.up_to_street_number(`YOUR_PROJECT.nayose`.trimmed(`YOUR_PROJECT.nayose`.numbers_dashed(`YOUR_PROJECT.nayose`.nfkc(address)))), ' ', ''),
                          v_prefecture_regex, ''), '') AS address__address,
    NULLIF(SUBSTR(postal_code, 1, 3), '') AS postal_code__first3,
    NULLIF(SUBSTR(any_name, 1, 1), '') AS any_name__initial,
    NULLIF(TRANSLATE(given_name, v_kana_fold_from, v_kana_fold_to), '') AS given_name__kana_fold
  FROM blanked
),
readings AS (
  SELECT
    *,
    NULLIF(SUBSTR(address__address, 1, 3), '') AS address__address_first3,
    NULLIF(REGEXP_REPLACE(REGEXP_REPLACE(person_name__kana_fold, r'([オコソトノホモヨロ])[ウオ]', r'\1ウ'),
                          r'([エケセテネヘメレ])[イエ]', r'\1イ'), '') AS person_name__kana_fold_long_vowel,
    -- one_byte is the copy that a similarity reads. It is NULL unless the value is katakana alone. Each katakana
    -- becomes a one-byte character of its own (v_one_byte), so DuckDB's own similarity functions, which count bytes,
    -- compare it character by character. BigQuery's JavaScript functions give the copy the same scores.
    IF(REGEXP_CONTAINS(person_name__kana_fold, r'^[\x{30a0}-\x{30ff}]+$'), TRANSLATE(person_name__kana_fold, v_katakana_block, v_one_byte), NULL)
      AS person_name__kana_fold_one_byte,
    IF(REGEXP_CONTAINS(company_name__nfkc_strip_legal_form_kana_fold, r'^[\x{30a0}-\x{30ff}]+$'),
       TRANSLATE(company_name__nfkc_strip_legal_form_kana_fold, v_katakana_block, v_one_byte), NULL)
      AS company_name__nfkc_strip_legal_form_kana_fold_one_byte,
    -- one_byte_hash is the copy that an edit distance reads. It is NULL if the value is ASCII alone, which needs no
    -- copy. Each character becomes one byte, chosen by its code point, and two characters may share a byte. So the
    -- copies are never farther apart than the values, and their distance, which DuckDB computes natively, is a cheap
    -- lower bound on the values' distance (functions.sql).
    IF(REGEXP_CONTAINS(address__address, r'[^\x00-\x7f]'), `YOUR_PROJECT.nayose`.one_byte_hash(address__address), NULL) AS address__address_one_byte_hash
  FROM copies
),
lettered AS (
  -- letters is the set of katakana a name holds, as two bit masks over its one-byte copy's codes. lo covers codes
  -- 1–63, and hi covers codes 64–96. One pass over the name makes both. `YOUR_PROJECT.nayose`.name_jw_most(functions.sql) bounds the
  -- Jaro–Winkler of two names with them.
  SELECT *, (SELECT STRUCT(COALESCE(BIT_OR(IF(UNICODE(c) < 64, CAST(1 AS INT64) << (UNICODE(c) - 1), 0)), 0) AS lo,
                           COALESCE(BIT_OR(IF(UNICODE(c) >= 64, CAST(1 AS INT64) << (UNICODE(c) - 64), 0)), 0) AS hi)
             FROM UNNEST(SPLIT(person_name__kana_fold_one_byte, '')) AS c) AS letters
  FROM readings
)
SELECT
  id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
  birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name, company_name,
  person_name__kana_fold, company_name__nfkc_strip_legal_form_kana_fold, address__address, postal_code__first3,
  any_name__initial, given_name__kana_fold, address__address_first3, person_name__kana_fold_long_vowel,
  person_name__kana_fold_one_byte, company_name__nfkc_strip_legal_form_kana_fold_one_byte,
  address__address_one_byte_hash,
  NULLIF(SUBSTR(person_name__kana_fold_long_vowel, -3), '') AS person_name__kana_fold_long_vowel_last3,
  IF(person_name__kana_fold_one_byte IS NULL, NULL, letters.lo) AS person_name__kana_fold_letters_lo,
  IF(person_name__kana_fold_one_byte IS NULL, NULL, letters.hi) AS person_name__kana_fold_letters_hi,
  customer, batch
FROM lettered;
-- Stage 3, score. This stage finds the pairs worth scoring and scores them. It pairs the records of the run's latest
-- batch, and the run's records that records.sql made again, with all the run's records. In a build, every record is
-- the batch's.
-- The pairs come from the rules and from the keys. Every pair that a key lists is a candidate. If a key's block holds
-- v_oversized records or more, the stage first scores a sample of the block's pairs, and lists the block's pairs only if
-- the sample holds a pair at v_search_floor points or more. Each pair gets its level of each comparison (functions.sql)
-- and its points from the model. The points are the prior plus each level's bits, added in the model's order, so
-- that the sum is Splink's to the last bit. The stage keeps every pair with v_keep_from points or more, and every
-- rule pair. These are the pairs a match run can offer people. Nothing merges here.
-- A pair's two records are x and y. l and r are the pair's IDs, and they can't name its records too, because a
-- WHERE clause reads a name l differently on the two engines: DuckDB as the SELECT's column l, BigQuery as the table l.
-- It costs O(Δ·b) for the batch's pairs, with Δ the batch's records and b the pairs one record's keys list, plus
-- O(Δ·L) to make the changed records' keys, L a value's length (Δ counts the records made again too), and a scan of
-- the index for the blocks the batch's keys name. The scores cost O(C·K·L²) for C candidates and K comparisons (6).
-- An update that makes records again also deletes their keys and their pairs, and on BigQuery a DELETE bills its
-- table whole: the index and scored.
--
-- A statement that follows a `-- when: <condition>` line runs only if the condition holds: run_file checks it locally,
-- and the deployed procedure wraps the statement in IF … END IF.
--
-- Reads: records, this_batch and redone (records.sql), compared (fit.sql), model (each level's bits) and fit (the
-- prior's bits at the file's size); block_size, a lookup's blocks read in part (nayose.lookup).
-- Values:
--   v_generators, v_rules   the names of the generators and the rules this run uses (config.toml [score])
--   v_keep_from            a scored pair with this many points or more is kept
--   v_search_floor         a sampled pair with this many points or more keeps its block
--   v_oversized            a block of this many records or more is checked first on a sample of as many of its records
--   v_lookup               true if the batch is a record asked about. Each of its keys is then kept, even in a block
--                         of one, so that lookup.sql can report it.
--   v_outside              how many of the run's records the records table doesn't hold. A lookup's records table
--                         holds only its record's blocks (nayose.lookup). In any other job, it is 0.
-- Writes:
--   rule_keys and every_key   each record's keys, which are the index a lookup reads by key
--   cands                     the pairs the batch's keys list, each with the generators that listed it
--   scored                    every pair kept
-- scored holds every batch's pairs. Each batch adds the pairs that touch its records, a rule's pair with its rule.
-- The pairs of a record made again leave it, and are scored again with the record's values as they are now.

-- 0. The records this job pairs, the generators and the rules.
-- changed holds the records whose keys this job makes: the batch's, and the run's records that records.sql made again
-- (redone), with redone TRUE. Every other record's keys are as the last job left them, since a record's keys change
-- only when the record does.
CREATE OR REPLACE TEMP TABLE changed AS
SELECT id, FALSE AS redone FROM `YOUR_PROJECT.nayose`.records WHERE batch = (SELECT batch FROM this_batch)
UNION ALL SELECT id, TRUE FROM redone;

-- batch_records holds the records this job pairs with all the run's records, which the statements below call the
-- batch's (in_batch). They are the batch's own records and the records made again, whose pairs are scored again
-- with their values as they are now: in an update or a build, changed whole.
CREATE OR REPLACE TEMP TABLE batch_records AS SELECT id FROM changed;

-- The generators and the rules are listed by name, in order. The statements below name each one, and read its
-- position from these lists. A generator's position (g) is its bit in a pair's mask, which cands turns into its
-- generators' names. A rule's position (i) is its rank: if several rules find a pair, the first one names it.
-- config.toml says which ones this run uses, and a name it gives that isn't listed here is refused.
-- The rules, in rank order. An X rule is exact: its key alone finds its pairs. An F rule is fuzzy: its key finds the
-- pairs, and its test then keeps those whose ~ fields are close. In a rule's name, ~ marks a field tested fuzzily,
-- outside the key (section 6's tests, functions.sql's near_*).
--   rule                           its key's fields                          its test
--   X1_CIF_FULL_NAME               customer_id, full_name                    none
--   X2_CIF_COMPANY_NAME            customer_id, company_name                 none
--   X3_CIF_PHONE                   customer_id, phone                        none
--   X4_FULL_NAME_ADDRCD_PHONE      full_name, address_code, phone            none
--   X5_COMPANY_NAME_ADDRCD_PHONE   company_name, address_code, phone         none
--   F1_NAME~_ADDRCD_PHONE          address_code, phone                       near_name
--   F2_NAME~_ADDRESS~_PHONE        phone, address__address_first3            near_name and near_address
--   F3_NAME~_CIF                   customer_id                               near_name
--   F4_NAME_ADDRCD_PHONE~          person_name, address_code                 near_phone
--   F5_COMPANY~_PHONE_POSTAL       phone, postal_code                        near_company
--   F6_COMPANY~_ADDRCD_PHONE       address_code, phone                       near_company
--   X6_GIVEN_ADDRCD_PHONE          given_name, address_code, phone           none
CREATE OR REPLACE TEMP TABLE generators AS
SELECT g, name, name IN UNNEST(v_generators) AS used FROM UNNEST([
  'customer_id', 'phone_prefecture', 'phone_postal_area', 'phone_name_initial', 'person_name', 'company_name', 'company_name_deletions',
  'person_name_deletions_postal_area', 'given_name_postal', 'address_phone', 'address_code_phone', 'address_name_initial',
  'address_code_name_initial', 'given_name_address_code', 'customer_id_deletions', 'birth_date', 'given_name_phone',
  'birth_date_deletions_prefecture', 'name_reading', 'phone_name_tail', 'postal_name_tail', 'postal_area_name_tail'
]) AS name WITH OFFSET AS g;

CREATE OR REPLACE TEMP TABLE rules AS
SELECT i, rule, rule IN UNNEST(v_rules) AS used FROM UNNEST([
  'X1_CIF_FULL_NAME', 'X2_CIF_COMPANY_NAME', 'X3_CIF_PHONE', 'X4_FULL_NAME_ADDRCD_PHONE',
  'X5_COMPANY_NAME_ADDRCD_PHONE', 'F1_NAME~_ADDRCD_PHONE', 'F2_NAME~_ADDRESS~_PHONE', 'F3_NAME~_CIF',
  'F4_NAME_ADDRCD_PHONE~', 'F5_COMPANY~_PHONE_POSTAL', 'F6_COMPANY~_ADDRCD_PHONE', 'X6_GIVEN_ADDRCD_PHONE'
]) AS rule WITH OFFSET AS i;

SELECT IF(COUNT(*) > 0, ERROR(CONCAT('config.toml [score]: no generator or rule is named ', STRING_AGG(x, ', '),
                                     '; name those score.sql lists')), 0)
FROM (SELECT x FROM UNNEST(v_generators) AS x WHERE x NOT IN (SELECT name FROM generators)
      UNION ALL SELECT x FROM UNNEST(v_rules) AS x WHERE x NOT IN (SELECT rule FROM rules));


-- 1. The rules. Each rule joins the records on its key, then applies its fuzzy tests to the pairs that join. If a key
--    value is held by v_oversized records or more, it can't be one entity's, so the rule leaves it out. The model
--    can still match those records. The batch's records are paired with all the run's records, each pair once, with
--    the lower ID first.
--    A key of several fields joins them with CHR(31), the unit separator. read_value removes every control character
--    (functions.sql), so no field holds it, and two different lists of values never make the same key.
CREATE OR REPLACE TEMP TABLE made_rule_keys AS  -- the rule keys of the records in changed
WITH changed_records AS (SELECT * FROM `YOUR_PROJECT.nayose`.records WHERE id IN (SELECT id FROM changed))
SELECT rules.i, key, id FROM (
  SELECT 'X1_CIF_FULL_NAME' AS rule, customer_id || CHR(31) || full_name AS key, id FROM changed_records
  UNION ALL SELECT 'X2_CIF_COMPANY_NAME', customer_id || CHR(31) || company_name, id FROM changed_records
  UNION ALL SELECT 'X3_CIF_PHONE', customer_id || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'X4_FULL_NAME_ADDRCD_PHONE', full_name || CHR(31) || address_code || CHR(31) || phone, id
    FROM changed_records
  UNION ALL SELECT 'X5_COMPANY_NAME_ADDRCD_PHONE', company_name || CHR(31) || address_code || CHR(31) || phone, id
    FROM changed_records
  UNION ALL SELECT 'F1_NAME~_ADDRCD_PHONE', address_code || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'F2_NAME~_ADDRESS~_PHONE', phone || CHR(31) || address__address_first3, id FROM changed_records
  UNION ALL SELECT 'F3_NAME~_CIF', customer_id, id FROM changed_records
  UNION ALL SELECT 'F4_NAME_ADDRCD_PHONE~', person_name || CHR(31) || address_code, id FROM changed_records
  UNION ALL SELECT 'F5_COMPANY~_PHONE_POSTAL', phone || CHR(31) || postal_code, id FROM changed_records
  UNION ALL SELECT 'F6_COMPANY~_ADDRCD_PHONE', address_code || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'X6_GIVEN_ADDRCD_PHONE', given_name || CHR(31) || address_code || CHR(31) || phone, id FROM changed_records
) JOIN rules USING (rule)
WHERE key IS NOT NULL AND rules.used;

-- rule_keys holds every record's rule keys. The records made again leave it, and the changed records' keys join it.
CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.rule_keys CLUSTER BY key AS SELECT i, key, id FROM made_rule_keys WHERE FALSE;
SET v_condition_2 = (EXISTS(SELECT 1 FROM changed WHERE redone));
IF v_condition_2 THEN

DELETE FROM `YOUR_PROJECT.nayose`.rule_keys WHERE id IN (SELECT id FROM changed WHERE redone);
END IF;

INSERT INTO `YOUR_PROJECT.nayose`.rule_keys SELECT i, key, id FROM made_rule_keys;
SET v_condition_3 = (EXISTS(SELECT 1 FROM this_batch WHERE batch = 0));
IF v_condition_3 THEN

-- rule_blocks holds every record of each rule key the batch holds. in_batch is TRUE for the batch's records, and n is
-- the number of records that hold the key.
-- In the run's first batch (batch 0) every record is the batch's, so every rule key is. A lookup takes the second
-- form whatever its batch, so that only the record it looks up is in_batch.
CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, key, id, TRUE AS in_batch, COUNT(*) OVER (PARTITION BY i, key) AS n FROM `YOUR_PROJECT.nayose`.rule_keys;
END IF;
IF NOT v_condition_3 THEN

CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, key, id, id IN (SELECT id FROM batch_records) AS in_batch, COUNT(*) OVER (PARTITION BY i, key) AS n
FROM `YOUR_PROJECT.nayose`.rule_keys
JOIN (SELECT DISTINCT i, key FROM made_rule_keys WHERE id IN (SELECT id FROM batch_records)) USING (i, key);
END IF;


-- 2. The keys. Each generator makes a key for each record from one or more of its fields, joined by CHR(31) as a
--    rule's are. The records with the same key form a block. A deletion generator makes several keys for a record.
--    They are its value with each character deleted in turn, and the value whole, each joined to the generator's other
--    fields. Deleting any character of a run of equal characters gives the same value, so a run gives its key once.
CREATE OR REPLACE TEMP TABLE made_keys AS  -- the keys of the records in changed
WITH changed_records AS (SELECT * FROM `YOUR_PROJECT.nayose`.records WHERE id IN (SELECT id FROM changed))
SELECT generators.g, key, id FROM (
  SELECT 'customer_id' AS name, customer_id AS key, id FROM changed_records
  UNION ALL SELECT 'phone_prefecture', phone || CHR(31) || prefecture, id FROM changed_records
  UNION ALL SELECT 'phone_postal_area', phone || CHR(31) || postal_code__first3, id FROM changed_records
  UNION ALL SELECT 'phone_name_initial', phone || CHR(31) || any_name__initial, id FROM changed_records
  UNION ALL SELECT 'person_name', person_name__kana_fold, id FROM changed_records
  UNION ALL SELECT 'company_name', company_name__nfkc_strip_legal_form_kana_fold, id FROM changed_records
  UNION ALL SELECT 'company_name_deletions', SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT company_name__nfkc_strip_legal_form_kana_fold AS x, id FROM changed_records
          WHERE company_name__nfkc_strip_legal_form_kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'person_name_deletions_postal_area', rest || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT person_name__kana_fold AS x, postal_code__first3 AS rest, id FROM changed_records
          WHERE person_name__kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'given_name_postal', given_name__kana_fold || CHR(31) || postal_code, id FROM changed_records
  UNION ALL SELECT 'address_phone', address__address || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'address_code_phone', address_code || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'address_name_initial', address__address || CHR(31) || any_name__initial, id FROM changed_records
  UNION ALL SELECT 'address_code_name_initial', address_code || CHR(31) || any_name__initial, id FROM changed_records
  UNION ALL SELECT 'given_name_address_code', given_name__kana_fold || CHR(31) || address_code, id FROM changed_records
  UNION ALL SELECT 'customer_id_deletions', SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT customer_id AS x, id FROM changed_records WHERE customer_id IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'birth_date', birth_date, id FROM changed_records
  UNION ALL SELECT 'given_name_phone', given_name__kana_fold || CHR(31) || phone, id FROM changed_records
  UNION ALL SELECT 'birth_date_deletions_prefecture', rest || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT birth_date AS x, prefecture AS rest, id FROM changed_records WHERE birth_date IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'name_reading', person_name__kana_fold_long_vowel, id FROM changed_records
  UNION ALL SELECT 'phone_name_tail', phone || CHR(31) || person_name__kana_fold_long_vowel_last3, id FROM changed_records
  UNION ALL SELECT 'postal_name_tail', postal_code || CHR(31) || person_name__kana_fold_long_vowel_last3, id FROM changed_records
  UNION ALL SELECT 'postal_area_name_tail', postal_code__first3 || CHR(31) || person_name__kana_fold_long_vowel_last3, id
    FROM changed_records
) JOIN generators USING (name)
WHERE key IS NOT NULL AND generators.used;

-- every_key holds every record's keys, which are the index a lookup reads by key. The records made again leave it,
-- and the changed records' keys join it.
CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.every_key CLUSTER BY key AS SELECT g, key, id FROM made_keys WHERE FALSE;
IF v_condition_2 THEN

DELETE FROM `YOUR_PROJECT.nayose`.every_key WHERE id IN (SELECT id FROM changed WHERE redone);
END IF;

INSERT INTO `YOUR_PROJECT.nayose`.every_key SELECT g, key, id FROM made_keys;

-- block_size gives a block's whole size if records holds only part of it. A lookup makes the table first, with the
-- blocks it read in part. In any other job, this statement makes it empty.
CREATE TEMP TABLE IF NOT EXISTS block_size (g INT64, key STRING, n INT64);
IF v_condition_3 THEN

-- key_blocks gives each key its block's size n among all the run's records. It keeps only the blocks that touch the
-- batch and hold two records or more, since only those can make a pair. A lookup also keeps its record's blocks of
-- one, so that lookup.sql can report every key.
-- In the run's first batch every record is the batch's, so every block is.
CREATE OR REPLACE TEMP TABLE key_blocks AS
SELECT g, key, id, TRUE AS in_batch, n FROM (SELECT g, key, id, COUNT(*) OVER (PARTITION BY g, key) AS n FROM `YOUR_PROJECT.nayose`.every_key)
WHERE n > 1;
END IF;
IF NOT v_condition_3 THEN

CREATE OR REPLACE TEMP TABLE key_blocks AS
-- touched holds every record of each block that a key of the batch names. held is the number of records the run
-- holds in the block.
WITH touched AS (
  SELECT e.g, e.key, e.id, COUNT(*) OVER (PARTITION BY e.g, e.key) AS held
  FROM `YOUR_PROJECT.nayose`.every_key AS e
  JOIN (SELECT DISTINCT g, key FROM made_keys WHERE id IN (SELECT id FROM batch_records)) USING (g, key)
)
SELECT t.g, t.key, t.id, t.id IN (SELECT id FROM batch_records) AS in_batch, COALESCE(u.n, t.held) AS n
FROM touched AS t LEFT JOIN block_size AS u USING (g, key)
WHERE (t.held > 1 OR v_lookup)  -- records holds two of the block's records or more, or the job is a lookup
  -- and the block at its whole size (block_size) holds two records or more, or the record is the batch's. So a lookup
  -- keeps a block of one only for the record it looks up.
  AND (COALESCE(u.n, t.held) > 1 OR t.id IN (SELECT id FROM batch_records));
END IF;

-- listed holds every pair that touches the batch and shares a block of fewer than v_oversized records. mask has one
-- bit set for each generator whose keys list the pair.
CREATE OR REPLACE TEMP TABLE listed AS
SELECT LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r, BIT_OR(1 << a.g) AS mask
FROM key_blocks AS a
JOIN key_blocks AS b ON a.g = b.g AND a.key = b.key AND a.id <> b.id AND (NOT b.in_batch OR a.id < b.id)
WHERE a.in_batch AND a.n < v_oversized
GROUP BY l, r;

CREATE OR REPLACE TEMP TABLE level_bits AS
-- run_records counts the run's records. v_outside counts those a lookup didn't read.
WITH size AS (SELECT COUNT(*) + v_outside AS run_records FROM `YOUR_PROJECT.nayose`.records),
rate AS (  -- λ is a per-pair rate, so it is rescaled to the run's size, as em.fitted rescales it
  SELECT LEAST(f.probability * (f.fit_records - 1) / GREATEST(size.run_records - 1, 1), `YOUR_PROJECT.nayose`.lambda_cap()) AS rate
  FROM `YOUR_PROJECT.nayose`.fit AS f, size
),
prior AS (  -- the prior is fit's own if the run has as many records as when fit ran, else the rescaled λ's bits
  SELECT IF(f.records = size.run_records, f.prior_bits, LOG(rate.rate / (1 - rate.rate), 2)) AS prior_bits
  FROM `YOUR_PROJECT.nayose`.fit AS f, size, rate
)
SELECT
  (SELECT prior_bits FROM prior) AS prior_bits,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'name' ORDER BY gamma)) AS name,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'company' ORDER BY gamma)) AS company,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'address' ORDER BY gamma)) AS address,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'phone' ORDER BY gamma)) AS phone,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'cif' ORDER BY gamma)) AS cif,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'birth' ORDER BY gamma)) AS birth,
  -- Each *_after is the most bits a fuzzy comparison can still earn once its leading equalities fail.
  (SELECT MAX(bits) FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'name' AND gamma <= 3) AS name_after,
  (SELECT MAX(bits) FROM `YOUR_PROJECT.nayose`.model WHERE comparison = 'company' AND gamma <= 1) AS company_after;


-- 4. The gate. A block of v_oversized records or more is listed only if a sample of its pairs holds a pair with
--    v_search_floor points or more. The sample pairs the block's first v_oversized batch records, by hash, with its
--    first v_oversized records. It leaves out the pairs another block already listed, and it is scored as the run
--    scores. So a block of 200 records whose batch holds 10 gives at most 10 × 64 sampled pairs, where its pairs
--    touching the batch number about 10 × 200.
--    A big block holds few true matches. A placeholder makes no key, as records.sql blanks it first, so a big block
--    is a crowded value that records.sql's test let through: a dummy phone held by too few customers, say.
CREATE OR REPLACE TEMP TABLE gate_pairs AS
WITH ranked AS (  -- nth_in_block is a record's place in its block by hash, and nth_in_batch its place among the batch's
  SELECT g, key, id, in_batch,
         ROW_NUMBER() OVER (PARTITION BY g, key ORDER BY `YOUR_PROJECT.nayose`.er_hash(id)) AS nth_in_block,
         IF(in_batch, ROW_NUMBER() OVER (PARTITION BY g, key, in_batch ORDER BY `YOUR_PROJECT.nayose`.er_hash(id)), NULL) AS nth_in_batch
  FROM key_blocks WHERE n >= v_oversized
)
SELECT DISTINCT a.g, a.key, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
FROM ranked AS a JOIN ranked AS b ON a.g = b.g AND a.key = b.key AND a.id <> b.id
WHERE a.nth_in_batch <= v_oversized AND b.nth_in_block <= v_oversized
  AND NOT EXISTS (SELECT 1 FROM listed AS seen WHERE seen.l = LEAST(a.id, b.id) AND seen.r = GREATEST(a.id, b.id));

CREATE OR REPLACE TEMP TABLE gated AS
-- gate_scored holds each sampled pair that the bound keeps, with its points. name_score is name_level's argument.
-- BigQuery has been seen to compute a SQL function's arguments once, before its body, so name_score runs once a pair
-- here; this is observed behaviour, not documented.
WITH gate_scored AS (
  SELECT p.l, p.r,
         `YOUR_PROJECT.nayose`.points_of(`YOUR_PROJECT.nayose`.name_level(x, y, `YOUR_PROJECT.nayose`.name_score(x, y)), `YOUR_PROJECT.nayose`.gamma_company(x, y), `YOUR_PROJECT.nayose`.gamma_address(x, y), `YOUR_PROJECT.nayose`.gamma_phone(x, y),
                   `YOUR_PROJECT.nayose`.gamma_cif(x, y), `YOUR_PROJECT.nayose`.gamma_birth(x, y), w) AS points
  FROM (SELECT DISTINCT l, r FROM gate_pairs) AS p JOIN `YOUR_PROJECT.nayose`.compared AS x ON x.id = p.l JOIN `YOUR_PROJECT.nayose`.compared AS y ON y.id = p.r
  CROSS JOIN level_bits AS w
  WHERE `YOUR_PROJECT.nayose`.could_reach(`YOUR_PROJECT.nayose`.bound_of(x, y, w), v_search_floor)
),
-- sampled counts every sampled pair of a block, those the bound dropped among them. best and hits read only the pairs
-- scored.
stats AS (
  SELECT p.g, p.key, COUNT(*) AS sampled, MAX(s.points) AS best,
         COUNT(CASE WHEN s.points >= v_search_floor THEN 1 END) AS hits
  FROM gate_pairs AS p LEFT JOIN gate_scored AS s USING (l, r) GROUP BY p.g, p.key
)
SELECT z.g, z.key, z.n AS records, `YOUR_PROJECT.nayose`.pairs_of(z.n) AS pairs,
       COALESCE(s.sampled, 0) AS sampled, s.best, COALESCE(s.hits, 0) AS hits,
       CASE WHEN COALESCE(s.hits, 0) > 0 THEN 'listed' WHEN COALESCE(s.sampled, 0) = 0 THEN 'skipped: other keys list its sampled pairs'
            ELSE 'skipped: no sampled pair reaches the floor' END AS verdict
FROM (SELECT DISTINCT g, key, n FROM key_blocks WHERE n >= v_oversized) AS z
LEFT JOIN stats AS s ON s.g = z.g AND s.key = z.key;


-- 5. The candidates. They are the pairs in listed, and every pair of a listed oversized block that touches the batch.
--    Each comes with the generators whose keys listed it.
CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.cands AS
WITH listed_or_gated AS (
  SELECT l, r, mask FROM listed
  UNION ALL
  SELECT LEAST(a.id, b.id), GREATEST(a.id, b.id), 1 << a.g
  FROM key_blocks AS a
  JOIN key_blocks AS b ON a.g = b.g AND a.key = b.key AND a.id <> b.id AND (NOT b.in_batch OR a.id < b.id)
  JOIN gated AS z ON z.g = a.g AND z.key = a.key
  WHERE a.in_batch AND z.verdict = 'listed'
),
pairs AS (SELECT l, r, BIT_OR(mask) AS mask FROM listed_or_gated GROUP BY l, r),
generator_names AS (  -- each mask becomes the generators' names, in their order, joined by +
  -- A join, not a subquery: BigQuery runs no subquery that reads a table by its outer row's mask (no equality).
  SELECT m.mask, STRING_AGG(gen.name, '+' ORDER BY gen.g) AS generators
  FROM (SELECT DISTINCT mask FROM pairs) AS m
  JOIN generators AS gen ON (m.mask >> gen.g) & 1 = 1
  GROUP BY m.mask
)
SELECT pairs.l, pairs.r, generator_names.generators FROM pairs JOIN generator_names USING (mask);


-- 6. The scores. Each candidate that the bound keeps, and every rule pair, gets its levels and its points. The pairs
--    with v_keep_from points or more are kept, and so is every rule pair. named is true if a name was compared, the
--    person's or the company's. The batch's pairs are added to the run's scored. Each pair is scored once, in the
--    batch that brings its later record, and again in each job that makes one of its records again.
CREATE OR REPLACE TEMP TABLE batch_pairs AS  -- each of the batch's candidates and rule pairs appears once
WITH rule_hits AS (
  SELECT a.i AS rule_rank, rules.rule, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
  FROM rule_blocks AS a
  JOIN rule_blocks AS b ON a.i = b.i AND a.key = b.key AND a.id <> b.id AND (NOT b.in_batch OR a.id < b.id)
  -- A function given a row reads all of its columns, so x and y are rows of compared, which holds only the columns
  -- the comparisons read.
  JOIN `YOUR_PROJECT.nayose`.compared AS x ON x.id = a.id JOIN `YOUR_PROJECT.nayose`.compared AS y ON y.id = b.id
  JOIN rules ON rules.i = a.i
  WHERE a.in_batch AND a.n < v_oversized
    AND CASE rules.rule  -- These are the fuzzy rules' tests. The exact rules (X1-X6) test their keys alone.
          WHEN 'F1_NAME~_ADDRCD_PHONE' THEN `YOUR_PROJECT.nayose`.near_name(x, y)
          WHEN 'F2_NAME~_ADDRESS~_PHONE' THEN `YOUR_PROJECT.nayose`.near_name(x, y) AND `YOUR_PROJECT.nayose`.near_address(x, y)
          WHEN 'F3_NAME~_CIF' THEN `YOUR_PROJECT.nayose`.near_name(x, y)
          WHEN 'F4_NAME_ADDRCD_PHONE~' THEN `YOUR_PROJECT.nayose`.near_phone(x, y)
          WHEN 'F5_COMPANY~_PHONE_POSTAL' THEN `YOUR_PROJECT.nayose`.near_company(x, y)
          WHEN 'F6_COMPANY~_ADDRCD_PHONE' THEN `YOUR_PROJECT.nayose`.near_company(x, y)
          ELSE TRUE END
),
rule_pairs AS (  -- each pair a rule finds, with the first rule in order that finds it (the least rule_rank)
  SELECT l, r, MIN_BY(rule, rule_rank) AS rule FROM rule_hits GROUP BY l, r
)
SELECT l, r, c.generators, p.rule FROM `YOUR_PROJECT.nayose`.cands AS c FULL JOIN rule_pairs AS p USING (l, r);

CREATE OR REPLACE TEMP TABLE batch_scored AS
WITH in_bound AS (  -- in_bound computes the names' Jaro–Winkler (s_name) once for each pair the bound keeps
  SELECT p.l, p.r, p.generators, p.rule, x, y, `YOUR_PROJECT.nayose`.name_score(x, y) AS s_name
  FROM batch_pairs AS p JOIN `YOUR_PROJECT.nayose`.compared AS x ON x.id = p.l JOIN `YOUR_PROJECT.nayose`.compared AS y ON y.id = p.r CROSS JOIN level_bits AS w
  WHERE p.rule IS NOT NULL OR `YOUR_PROJECT.nayose`.could_reach(`YOUR_PROJECT.nayose`.bound_of(x, y, w), v_keep_from)
),
levelled AS (
  SELECT l, r, generators, rule, `YOUR_PROJECT.nayose`.name_level(x, y, s_name) AS gamma_name, `YOUR_PROJECT.nayose`.gamma_company(x, y) AS gamma_company,
         `YOUR_PROJECT.nayose`.gamma_address(x, y) AS gamma_address, `YOUR_PROJECT.nayose`.gamma_phone(x, y) AS gamma_phone, `YOUR_PROJECT.nayose`.gamma_cif(x, y) AS gamma_cif,
         `YOUR_PROJECT.nayose`.gamma_birth(x, y) AS gamma_birth
  FROM in_bound
),
weighed AS (
  SELECT lv.*,
         `YOUR_PROJECT.nayose`.points_of(gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth, w) AS points
  FROM levelled AS lv CROSS JOIN level_bits AS w
)
SELECT
  l AS id_l, r AS id_r, points,
  `YOUR_PROJECT.nayose`.probability_of(points) AS match_probability,
  generators, rule, (gamma_name >= 0 OR gamma_company >= 0) AS named,
  gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth
FROM weighed
WHERE points >= v_keep_from OR rule IS NOT NULL;

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.scored AS SELECT * FROM batch_scored WHERE FALSE;
IF v_condition_2 THEN

-- The pairs a record made again had leave scored, as batch_scored holds them scored again. A pair that its keys or
-- rules no longer find, or that now scores under v_keep_from, is not kept. On BigQuery this DELETE bills scored whole,
-- so only an update that finds a new placeholder runs it.
DELETE FROM `YOUR_PROJECT.nayose`.scored
WHERE id_l IN (SELECT id FROM changed WHERE redone) OR id_r IN (SELECT id FROM changed WHERE redone);
END IF;

INSERT INTO `YOUR_PROJECT.nayose`.scored SELECT * FROM batch_scored;
-- The decide job stores people's decisions on pairs and makes the entities again from them. The decisions come in
-- given, a match table that people filled in. They are stored with the run's earlier decisions, and each pair's latest
-- decision is its standing. The entities are the connected components of the pairs whose latest decision is match
-- (entities_of, nayose/entities.py), and each is named by its smallest ID. So a later no_match on a pair parts what
-- only that pair joined. Nothing merges by itself, so a record that no decision joins is an entity alone. A build and
-- an update run this file without v_given, to make their entities from the decisions the run holds: they skip
-- sections 1 and 2, which read given. O(D + N) for D decisions.
--
-- Reads: given, the job's table of id_l, id_r, decision and why (with v_given alone), records, and decisions if the
-- run has any.
-- Values: given, TRUE if the job was given decisions. A blank value is one that `YOUR_PROJECT.nayose`.blank() finds (functions.sql): spaces
-- alone, of any width.
-- Writes: decisions (each decision that changed its pair's standing, with its round, and each pair's latest flagged)
-- and gold (each record's entity, what joined it, its kind and its entity's kind). A round is one call of this job.

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.decisions (id_l STRING, id_r STRING, decision STRING, why STRING, round INT64, latest BOOL);


-- 3. Each record is its own entity until the pairs whose latest decision is match join it to others. Only pairs of
--    this run's records join, because a decision kept from an earlier run may name records the run no longer holds.
--    resolved_by is review if people's decisions put the record with another record. entity_kind, the entity's
--    kind, is 2 (company) if any of its records is a company. It is 1 (person) if none of its records leans company
--    (kind_p under 0.5) and one is a person, and 0 (not sure) otherwise.
-- shortcut: entities_of takes every match decision in one call, a few MB for each 100,000 decisions. Past millions of
-- decisions, compute the components by label propagation in SQL.

-- joined is a table, not a WITH in gold: gold reads placed twice, and BigQuery runs a WITH once each time it is read.
CREATE OR REPLACE TEMP TABLE joined AS  -- each record that a match decision joins, with its entity
-- asked holds what entities_of is asked, as one JSON text: the pairs whose latest decision is match, both of whose
-- records the run holds.
WITH asked AS (
  SELECT TO_JSON_STRING(STRUCT(ARRAY_AGG(STRUCT(d.id_l AS l, d.id_r AS r)) AS pairs)) AS pairs FROM `YOUR_PROJECT.nayose`.decisions AS d
  WHERE d.latest AND d.decision = 'match' AND d.id_l IN (SELECT id FROM `YOUR_PROJECT.nayose`.records) AND d.id_r IN (SELECT id FROM `YOUR_PROJECT.nayose`.records)
)
SELECT JSON_VALUE(e, '$.id') AS id, JSON_VALUE(e, '$.entity') AS entity
FROM asked, UNNEST(JSON_QUERY_ARRAY(`YOUR_PROJECT.nayose`.entities_of(asked.pairs))) AS e;

CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.gold CLUSTER BY id AS  -- a lookup reads gold by its records' IDs
WITH placed AS (
  SELECT rec.id, COALESCE(j.entity, rec.id) AS entity, rec.kind, rec.kind_p, rec.kind_by, rec.kind_flagged
  FROM `YOUR_PROJECT.nayose`.records AS rec LEFT JOIN joined AS j USING (id)
),
entities AS (
  SELECT entity, COUNT(*) AS n,
         CASE WHEN LOGICAL_OR(kind = 2) THEN 2
              WHEN COALESCE(MAX(kind_p), 0) < CAST(0.5 AS FLOAT64) AND LOGICAL_OR(kind = 1) THEN 1
              ELSE 0 END AS entity_kind
  FROM placed GROUP BY entity
)
SELECT p.id, p.entity, IF(e.n > 1, 'review', NULL) AS resolved_by,
       p.kind, p.kind_p, p.kind_by, p.kind_flagged, e.entity_kind
FROM placed AS p JOIN entities AS e USING (entity);
-- This file computes report.txt's numbers, which tell what the run holds and how its latest batch went. No number
-- holds a record's value. nayose.report sets them out as report.txt. O(N·F) for the fields' fill, and O(C) over the
-- batch's pairs.
--
-- Reads: records, this_batch, set_aside, gold, decisions, cands, batch_pairs and batch_scored (score.sql), key_blocks,
-- gated and generators. nayose.report_text reads placeholders, model and fit itself.
-- Values:
--   v_looks      as JSON, the regular expression that each field's values look like (config.toml [report.looks],
--               and for company_name the legal forms)
--   v_edges      the points at which each score band starts
--   v_floor      the review floor, in points
--   v_oversized  how many records make a block oversized
--   v_sample_records, v_patterns_shown   the records FIELDS samples, and the patterns each band shows (config.toml
--               [report])
-- Writes (read by nayose.report_text, here or after a BigQuery procedure): report_counts, report_fields,
-- report_scores, report_patterns, report_generators, report_entities.


-- report_counts holds one row of counts about the run, its latest batch, its entities and kinds, its oversized
-- blocks, and each field's filled records.
CREATE OR REPLACE TEMP TABLE report_counts AS
SELECT
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.records) AS records,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.records WHERE batch = (SELECT batch FROM this_batch)) AS added,
  (SELECT batch FROM this_batch) AS batch,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.set_aside) AS set_aside,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.cands) AS candidates,
  (SELECT COUNT(*) FROM batch_scored) AS scored,
  (SELECT COUNT(*) FROM batch_scored WHERE rule IS NOT NULL) AS ruled,
  (SELECT COUNT(DISTINCT entity) FROM `YOUR_PROJECT.nayose`.gold) AS entities,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE resolved_by = 'review') AS by_people,
  (SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM `YOUR_PROJECT.nayose`.gold GROUP BY entity)) AS largest,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.decisions WHERE latest) AS decided,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE kind = 2) AS companies, (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE kind = 1) AS persons,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE kind = 0) AS unsure,
  (SELECT COUNT(DISTINCT entity) FROM `YOUR_PROJECT.nayose`.gold WHERE entity_kind = 2) AS company_entities,
  (SELECT COUNT(DISTINCT entity) FROM `YOUR_PROJECT.nayose`.gold WHERE entity_kind = 1) AS person_entities,
  (SELECT COUNT(DISTINCT entity) FROM `YOUR_PROJECT.nayose`.gold WHERE entity_kind = 0) AS unsure_entities,
  (SELECT COUNT(*) FROM `YOUR_PROJECT.nayose`.gold WHERE kind_flagged) AS flagged,
  (SELECT COUNT(*) FROM gated WHERE verdict = 'listed') AS oversized_listed,
  (SELECT COUNT(*) FROM gated WHERE verdict <> 'listed') AS oversized_skipped,
  COUNT(full_name) AS full_name, COUNT(person_name) AS person_name, COUNT(given_name) AS given_name,
  COUNT(company_name) AS company_name, COUNT(any_name) AS any_name, COUNT(address) AS address,
  COUNT(address_code) AS address_code, COUNT(postal_code) AS postal_code, COUNT(prefecture) AS prefecture,
  COUNT(town_code) AS town_code, COUNT(city) AS city, COUNT(phone) AS phone, COUNT(customer_id) AS customer_id,
  COUNT(birth_date) AS birth_date
FROM `YOUR_PROJECT.nayose`.records;

-- report_fields describes each field on a sample of v_sample_records records, chosen by hash so that the sample is the
-- same whatever the rows' order. It gives the share of a field's filled values that match its look, a regex
-- (looks_right), the share that its most common value holds (top_value), the share with no letter or digit
-- (no_letters), and the values' mean and longest length.
CREATE OR REPLACE TEMP TABLE report_fields AS
WITH sample AS (SELECT * FROM `YOUR_PROJECT.nayose`.records ORDER BY `YOUR_PROJECT.nayose`.er_hash(id) LIMIT 10000),
sampled_values AS (
  SELECT 'full_name' AS field, full_name AS v FROM sample UNION ALL SELECT 'person_name', person_name FROM sample
  UNION ALL SELECT 'given_name', given_name FROM sample UNION ALL SELECT 'company_name', company_name FROM sample
  UNION ALL SELECT 'any_name', any_name FROM sample UNION ALL SELECT 'address', address FROM sample
  UNION ALL SELECT 'address_code', address_code FROM sample UNION ALL SELECT 'postal_code', postal_code FROM sample
  UNION ALL SELECT 'prefecture', prefecture FROM sample UNION ALL SELECT 'town_code', town_code FROM sample
  UNION ALL SELECT 'city', city FROM sample UNION ALL SELECT 'phone', phone FROM sample
  UNION ALL SELECT 'customer_id', customer_id FROM sample UNION ALL SELECT 'birth_date', birth_date FROM sample
),
top AS (
  SELECT field, MAX(n) / SUM(n) AS top_value
  FROM (SELECT field, v, COUNT(*) AS n FROM sampled_values WHERE v IS NOT NULL GROUP BY field, v)
  GROUP BY field
),
-- looks holds each field's look from v_looks, one path a field: BigQuery reads a JSON path only as written out.
looks AS (
  SELECT 'full_name' AS field, JSON_VALUE(v_looks, '$.full_name') AS look
  UNION ALL SELECT 'person_name', JSON_VALUE(v_looks, '$.person_name')
  UNION ALL SELECT 'given_name', JSON_VALUE(v_looks, '$.given_name')
  UNION ALL SELECT 'company_name', JSON_VALUE(v_looks, '$.company_name')
  UNION ALL SELECT 'any_name', JSON_VALUE(v_looks, '$.any_name')
  UNION ALL SELECT 'address', JSON_VALUE(v_looks, '$.address')
  UNION ALL SELECT 'address_code', JSON_VALUE(v_looks, '$.address_code')
  UNION ALL SELECT 'postal_code', JSON_VALUE(v_looks, '$.postal_code')
  UNION ALL SELECT 'prefecture', JSON_VALUE(v_looks, '$.prefecture')
  UNION ALL SELECT 'town_code', JSON_VALUE(v_looks, '$.town_code')
  UNION ALL SELECT 'city', JSON_VALUE(v_looks, '$.city')
  UNION ALL SELECT 'phone', JSON_VALUE(v_looks, '$.phone')
  UNION ALL SELECT 'customer_id', JSON_VALUE(v_looks, '$.customer_id')
  UNION ALL SELECT 'birth_date', JSON_VALUE(v_looks, '$.birth_date')
)
SELECT
  field, AVG(CAST(REGEXP_CONTAINS(v, look) AS INT64)) AS looks_right,
  ANY_VALUE(top.top_value) AS top_value, AVG(CAST(NOT REGEXP_CONTAINS(v, r'[\pL\pN]') AS INT64)) AS no_letters,
  AVG(LENGTH(v)) AS length, MAX(LENGTH(v)) AS longest
FROM sampled_values LEFT JOIN top USING (field) LEFT JOIN looks USING (field)
GROUP BY field;

-- report_scores counts the batch's pairs by band. A pair scored at 0 points or more is in band k if k of v_edges are
-- at or below its points. Band -1 counts the rest of the batch's pairs (batch_pairs). With [score] keep_from at 0,
-- those are the pairs that scored below 0 points, and the pairs that the bound kept from being scored.
CREATE OR REPLACE TEMP TABLE report_scores AS
SELECT band, COUNT(*) AS pairs
FROM (SELECT ARRAY_LENGTH(ARRAY(SELECT e FROM UNNEST(v_edges) AS e WHERE e <= points)) AS band
      FROM batch_scored WHERE points >= 0)
GROUP BY band
UNION ALL
SELECT -1, (SELECT COUNT(*) FROM batch_pairs) - (SELECT COUNT(*) FROM batch_scored WHERE points >= 0);

-- report_patterns splits the batch's pairs at 0 points or more into two bands, below the review floor (v_floor) and
-- from it up. For each band it keeps the v_patterns_shown most common patterns of levels, each with its pairs and their
-- mean points. It also gives the band's total pairs and how many patterns the band holds (patterns).
CREATE OR REPLACE TEMP TABLE report_patterns AS
WITH p AS (
  SELECT points >= v_floor AS up, gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth,
         COUNT(*) AS n, AVG(points) AS mean_points
  FROM batch_scored WHERE points >= 0
  GROUP BY up, gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth
)
SELECT * FROM (
  SELECT *, SUM(n) OVER (PARTITION BY up) AS total, COUNT(*) OVER (PARTITION BY up) AS patterns,
         ROW_NUMBER() OVER (PARTITION BY up ORDER BY n DESC, mean_points DESC, gamma_name, gamma_company,
                                                     gamma_address, gamma_phone, gamma_cif, gamma_birth) AS nth
  FROM p
) WHERE nth <= v_patterns_shown;

-- report_generators describes each generator that the run uses. pairs counts the candidates its keys listed, each
-- pair once, even if a deletion generator listed the pair through several of its deletions. largest is the size of
-- its largest block that holds a batch record, and oversized counts its blocks of v_oversized records or more.
CREATE OR REPLACE TEMP TABLE report_generators AS
WITH listing AS (SELECT name, COUNT(*) AS pairs FROM `YOUR_PROJECT.nayose`.cands, UNNEST(SPLIT(generators, '+')) AS name GROUP BY name),
blocks AS (
  SELECT g, MAX(n) AS largest, COUNT(DISTINCT CASE WHEN n >= v_oversized THEN key END) AS oversized
  FROM key_blocks GROUP BY g
)
SELECT gen.g, gen.name, COALESCE(ls.pairs, 0) AS pairs, COALESCE(b.largest, 0) AS largest,
       COALESCE(b.oversized, 0) AS oversized
FROM generators AS gen LEFT JOIN listing AS ls USING (name) LEFT JOIN blocks AS b USING (g)
WHERE gen.used;

-- report_entities counts the entities of each size.
CREATE OR REPLACE TEMP TABLE report_entities AS
SELECT n AS size, COUNT(*) AS entities FROM (SELECT COUNT(*) AS n FROM `YOUR_PROJECT.nayose`.gold GROUP BY entity) GROUP BY n;
END;

CREATE OR REPLACE PROCEDURE `YOUR_PROJECT.nayose`.decide() OPTIONS (strict_mode = FALSE)
BEGIN
DECLARE v_given BOOL DEFAULT TRUE;
SELECT IF((SELECT fingerprint FROM `YOUR_PROJECT.nayose`.method) IS DISTINCT FROM 'f4db6e8349053bef0bde3d9fe7f003af26b4d09a642fbac3658a623a441c2c36', ERROR('the method, its values or the mapping changed since the run was built: this code would read its tables, and score its batches, otherwise; build the run again'), 0);
-- The decide job stores people's decisions on pairs and makes the entities again from them. The decisions come in
-- given, a match table that people filled in. They are stored with the run's earlier decisions, and each pair's latest
-- decision is its standing. The entities are the connected components of the pairs whose latest decision is match
-- (entities_of, nayose/entities.py), and each is named by its smallest ID. So a later no_match on a pair parts what
-- only that pair joined. Nothing merges by itself, so a record that no decision joins is an entity alone. A build and
-- an update run this file without v_given, to make their entities from the decisions the run holds: they skip
-- sections 1 and 2, which read given. O(D + N) for D decisions.
--
-- Reads: given, the job's table of id_l, id_r, decision and why (with v_given alone), records, and decisions if the
-- run has any.
-- Values: given, TRUE if the job was given decisions. A blank value is one that `YOUR_PROJECT.nayose`.blank() finds (functions.sql): spaces
-- alone, of any width.
-- Writes: decisions (each decision that changed its pair's standing, with its round, and each pair's latest flagged)
-- and gold (each record's entity, what joined it, its kind and its entity's kind). A round is one call of this job.

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.nayose`.decisions (id_l STRING, id_r STRING, decision STRING, why STRING, round INT64, latest BOOL);

-- 1. given_text reads what people said, each value as text. A blank value (spaces of any width) is missing, and the
--    decision is put in lower case. An ID that a spreadsheet saved as a number (151 for 0000000151) then names no
--    record, and the check below refuses it. said holds each decided pair once, with the lower ID first and one
--    why. A row without a decision is skipped.
CREATE OR REPLACE TEMP TABLE given_text AS
SELECT IF(`YOUR_PROJECT.nayose`.blank(l), NULL, l) AS id_l, IF(`YOUR_PROJECT.nayose`.blank(r), NULL, r) AS id_r,
       NULLIF(LOWER(`YOUR_PROJECT.nayose`.trimmed(d)), '') AS decision, NULLIF(`YOUR_PROJECT.nayose`.trimmed(why), '') AS why
FROM (SELECT CAST(id_l AS STRING) AS l, CAST(id_r AS STRING) AS r, CAST(decision AS STRING) AS d,
             CAST(why AS STRING) AS why
      FROM `YOUR_PROJECT.nayose`.given);

CREATE OR REPLACE TEMP TABLE said AS
SELECT id_l, id_r, decision, MIN(why) AS why
FROM (SELECT LEAST(id_l, id_r) AS id_l, GREATEST(id_l, id_r) AS id_r, decision, why
      FROM given_text WHERE decision IS NOT NULL)
GROUP BY id_l, id_r, decision;

-- The check refuses the table and says what to do, for the first of these it finds, in this order: a decided row
-- without both IDs, a table with rows but no decision, a decision other than match or no_match, a pair decided both
-- ways, and an ID that names no record of the run. They are one statement, as BigQuery spends about a second on each.
SELECT CASE
  WHEN lacking > 0 THEN ERROR(CONCAT('given: ', CAST(lacking AS STRING), ' decided rows lack an ID; fill in both IDs of each decided row, or clear its decision'))
  WHEN given_rows > 0 AND decided = 0 THEN ERROR('given: no row has a decision; write match or no_match in the decision column')
  WHEN other_decisions IS NOT NULL THEN ERROR(CONCAT('given: a decision is match or no_match, not ', other_decisions,
                                                     '; correct those rows, or leave them empty'))
  WHEN both_ways > 0 THEN ERROR(CONCAT('given: ', CAST(both_ways AS STRING), ' pairs decided both ways, as ', both_l, ' and ', both_r,
                                       '; keep one decision per pair'))
  WHEN unknown > 0 THEN ERROR(CONCAT('given: ', CAST(unknown AS STRING), ' IDs name no record of the run, as ', unknown_id,
                                     '; check the IDs as the run wrote them: a spreadsheet may read 0000000151 as the number 151'))
  ELSE 0 END
FROM (SELECT COUNT(CASE WHEN decision IS NOT NULL AND (id_l IS NULL OR id_r IS NULL) THEN 1 END) AS lacking,
             COUNT(*) AS given_rows, COUNT(decision) AS decided FROM given_text),
     (SELECT STRING_AGG(DISTINCT decision, ', ') AS other_decisions FROM said WHERE decision NOT IN ('match', 'no_match')),
     (SELECT COUNT(*) AS both_ways, MIN(id_l) AS both_l, MIN(id_r) AS both_r
      FROM (SELECT id_l, id_r FROM said GROUP BY id_l, id_r HAVING COUNT(*) > 1)),
     (SELECT COUNT(*) AS unknown, MIN(id) AS unknown_id
      FROM (SELECT id_l AS id FROM said UNION DISTINCT SELECT id_r FROM said) WHERE id NOT IN (SELECT id FROM `YOUR_PROJECT.nayose`.records));


-- 2. decisions keeps the run's decisions and adds each new one that changes its pair's latest decision, so a table
--    given twice adds nothing. The new ones get the next round's number. Each pair's last decision is flagged latest.
CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.decisions AS
WITH stored_and_said AS (
  SELECT id_l, id_r, decision, why, round FROM `YOUR_PROJECT.nayose`.decisions
  UNION ALL
  SELECT s.id_l, s.id_r, s.decision, s.why, (SELECT COALESCE(MAX(round), -1) + 1 FROM `YOUR_PROJECT.nayose`.decisions)
  FROM said AS s
  WHERE NOT EXISTS (SELECT 1 FROM `YOUR_PROJECT.nayose`.decisions AS d
                    WHERE d.latest AND d.id_l = s.id_l AND d.id_r = s.id_r AND d.decision = s.decision)
)
SELECT *, ROW_NUMBER() OVER (PARTITION BY id_l, id_r ORDER BY round DESC) = 1 AS latest FROM stored_and_said;


-- 3. Each record is its own entity until the pairs whose latest decision is match join it to others. Only pairs of
--    this run's records join, because a decision kept from an earlier run may name records the run no longer holds.
--    resolved_by is review if people's decisions put the record with another record. entity_kind, the entity's
--    kind, is 2 (company) if any of its records is a company. It is 1 (person) if none of its records leans company
--    (kind_p under 0.5) and one is a person, and 0 (not sure) otherwise.
-- shortcut: entities_of takes every match decision in one call, a few MB for each 100,000 decisions. Past millions of
-- decisions, compute the components by label propagation in SQL.

-- joined is a table, not a WITH in gold: gold reads placed twice, and BigQuery runs a WITH once each time it is read.
CREATE OR REPLACE TEMP TABLE joined AS  -- each record that a match decision joins, with its entity
-- asked holds what entities_of is asked, as one JSON text: the pairs whose latest decision is match, both of whose
-- records the run holds.
WITH asked AS (
  SELECT TO_JSON_STRING(STRUCT(ARRAY_AGG(STRUCT(d.id_l AS l, d.id_r AS r)) AS pairs)) AS pairs FROM `YOUR_PROJECT.nayose`.decisions AS d
  WHERE d.latest AND d.decision = 'match' AND d.id_l IN (SELECT id FROM `YOUR_PROJECT.nayose`.records) AND d.id_r IN (SELECT id FROM `YOUR_PROJECT.nayose`.records)
)
SELECT JSON_VALUE(e, '$.id') AS id, JSON_VALUE(e, '$.entity') AS entity
FROM asked, UNNEST(JSON_QUERY_ARRAY(`YOUR_PROJECT.nayose`.entities_of(asked.pairs))) AS e;

CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.gold CLUSTER BY id AS  -- a lookup reads gold by its records' IDs
WITH placed AS (
  SELECT rec.id, COALESCE(j.entity, rec.id) AS entity, rec.kind, rec.kind_p, rec.kind_by, rec.kind_flagged
  FROM `YOUR_PROJECT.nayose`.records AS rec LEFT JOIN joined AS j USING (id)
),
entities AS (
  SELECT entity, COUNT(*) AS n,
         CASE WHEN LOGICAL_OR(kind = 2) THEN 2
              WHEN COALESCE(MAX(kind_p), 0) < CAST(0.5 AS FLOAT64) AND LOGICAL_OR(kind = 1) THEN 1
              ELSE 0 END AS entity_kind
  FROM placed GROUP BY entity
)
SELECT p.id, p.entity, IF(e.n > 1, 'review', NULL) AS resolved_by,
       p.kind, p.kind_p, p.kind_by, p.kind_flagged, e.entity_kind
FROM placed AS p JOIN entities AS e USING (entity);
END;

CREATE OR REPLACE PROCEDURE `YOUR_PROJECT.nayose`.match(v_threshold FLOAT64) OPTIONS (strict_mode = FALSE)
BEGIN
SELECT IF((SELECT fingerprint FROM `YOUR_PROJECT.nayose`.method) IS DISTINCT FROM 'f4db6e8349053bef0bde3d9fe7f003af26b4d09a642fbac3658a623a441c2c36', ERROR('the method, its values or the mapping changed since the run was built: this code would read its tables, and score its batches, otherwise; build the run again'), 0);

-- shown gives each comparison's levels as people read them, each with its label and its bits rounded to two places.
-- A missing side is level -1, labelled missing, with 0 bits. lookup.sql's shown uses the same labels.
CREATE OR REPLACE TEMP TABLE shown AS
SELECT comparison, gamma, label, ROUND(bits, 2) AS bits FROM `YOUR_PROJECT.nayose`.model
UNION ALL SELECT DISTINCT comparison, -1, 'missing', CAST(0 AS FLOAT64) FROM `YOUR_PROJECT.nayose`.model;

-- pair_records holds only the columns the table shows and household reads, because a row passed to a function is
-- billed whole.
CREATE OR REPLACE TABLE `YOUR_PROJECT.nayose`.matched AS
WITH pair_records AS (
  SELECT id, person_name, given_name, company_name, address_code, address, postal_code, phone, customer_id, birth_date,
         address__address, given_name__kana_fold, person_name__kana_fold_long_vowel_last3
  FROM `YOUR_PROJECT.nayose`.records
)
SELECT
  CAST(NULL AS STRING) AS decision, CAST(NULL AS STRING) AS why,
  s.id_l, s.id_r, s.points, s.match_probability, s.rule, s.named,
  `YOUR_PROJECT.nayose`.household(x, y) AS household, s.generators,
  x.person_name AS person_name_l, y.person_name AS person_name_r,
  x.given_name AS given_name_l, y.given_name AS given_name_r,
  x.company_name AS company_name_l, y.company_name AS company_name_r,
  x.address_code AS address_code_l, y.address_code AS address_code_r,
  x.address AS address_l, y.address AS address_r, x.postal_code AS postal_code_l, y.postal_code AS postal_code_r,
  x.phone AS phone_l, y.phone AS phone_r, x.customer_id AS customer_id_l, y.customer_id AS customer_id_r,
  x.birth_date AS birth_date_l, y.birth_date AS birth_date_r,
  nm.label AS name, nm.bits AS name_bits, c.label AS company, c.bits AS company_bits,
  a.label AS address, a.bits AS address_bits, p.label AS phone, p.bits AS phone_bits,
  i.label AS cif, i.bits AS cif_bits, b.label AS birth, b.bits AS birth_bits
FROM `YOUR_PROJECT.nayose`.scored AS s
JOIN pair_records AS x ON x.id = s.id_l JOIN pair_records AS y ON y.id = s.id_r
JOIN shown AS nm ON nm.comparison = 'name' AND nm.gamma = s.gamma_name
JOIN shown AS c ON c.comparison = 'company' AND c.gamma = s.gamma_company
JOIN shown AS a ON a.comparison = 'address' AND a.gamma = s.gamma_address
JOIN shown AS p ON p.comparison = 'phone' AND p.gamma = s.gamma_phone
JOIN shown AS i ON i.comparison = 'cif' AND i.gamma = s.gamma_cif
JOIN shown AS b ON b.comparison = 'birth' AND b.gamma = s.gamma_birth
WHERE s.points >= v_threshold
  AND NOT EXISTS (SELECT 1 FROM `YOUR_PROJECT.nayose`.decisions AS d
                  WHERE d.id_l = s.id_l AND d.id_r = s.id_r AND d.latest AND d.decision = 'no_match')
ORDER BY s.points DESC, s.id_l, s.id_r;
END;
