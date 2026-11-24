-- Stage 2, fit: the counts the model is learned from, on a sample of a fixed size (so its cost doesn't grow with the
-- file), and u counted on the sample and on the file to be scored, each a scope; then the model, learned from them by
-- fit_model (nayose/em.py, a Python function on both engines): Fellegi–Sunter as Splink 5.0 fits it. Every count an
-- exact integer. The comparisons are functions.sql's. O(n + P_prior + P_em·K) on the sample of n records;
-- O(N + max_pairs·K) for u on each scope.
--
-- An update (@refit false) keeps the model the run's build fitted: no sample, no EM; u is measured again on the
-- run's records, a sampled comparison only once it has gone stale (fit_model with the stored fit).
--
-- Reads: records, fit (an update's). Values: config.toml [fit]: @fit_rows, @seed, @fit_u_max_pairs and @u_max_pairs
-- (about how many pairs u samples on the sample and on the file), @settings (all of it, as JSON, for fit_model);
-- @refit (a build: the model learned again).
-- Writes: fit_sample, model (each level's m and u as fitted, file_m and file_u on the file, and bits: log2(file_m /
-- file_u), what a score adds), fit (λ, the sample's size, the file's, prior_bits: λ's at its size, the notes the report reads,
-- and fitted: fit_model's answer whole, what an update starts from).

CREATE TABLE IF NOT EXISTS fit (probability FLOAT64, fit_rows INT64, records INT64, prior_bits FLOAT64, notes STRING, fitted STRING);


-- 1. The columns the fit reads of a record (the comparisons', the near-certain rules', EM's keys): only these are read,
--    and billed. The sample: whole postal areas by hash, so households stay together and a smaller sample is part of
--    a bigger one.
CREATE OR REPLACE VIEW compared AS
SELECT
  id, person_name, full_name, given_name__kana_fold, person_name__kana_fold, person_name__kana_fold_long_vowel,
  person_name__kana_fold_one_byte, person_name__kana_fold_letters_lo, person_name__kana_fold_letters_hi,
  company_name, company_name__nfkc_strip_legal_form_kana_fold,
  company_name__nfkc_strip_legal_form_kana_fold_one_byte, address_code, address, address__address,
  address__address_one_byte_hash, postal_code, phone, customer_id, birth_date
FROM records;

-- when: @refit
CREATE OR REPLACE TABLE fit_sample AS
SELECT compared.* FROM compared
JOIN (SELECT id FROM records WHERE @refit ORDER BY er_hash(postal_code__first3), er_hash(id) LIMIT @fit_rows) USING (id);

-- when: NOT @refit
CREATE OR REPLACE TABLE fit_sample AS SELECT * FROM compared WHERE FALSE;  -- an update learns nothing: no sample


-- 2. λ, how likely two random records are one customer, from the pairs the near-certain rules find: each pair once,
--    whichever rules find it. Each rule's own pairs too: a rule that finds none in the sample is skipped (named).
CREATE OR REPLACE TABLE fit_prior AS
SELECT
  (SELECT COUNT(*) FROM fit_sample) AS records,
  (SELECT COUNT(*) FROM (
     SELECT l.id AS l, r.id AS r FROM fit_sample AS l JOIN fit_sample AS r
       ON l.customer_id = r.customer_id AND l.full_name = r.full_name AND l.id < r.id
     UNION DISTINCT
     SELECT l.id, r.id FROM fit_sample AS l JOIN fit_sample AS r
       ON l.customer_id = r.customer_id AND l.company_name = r.company_name AND l.id < r.id
     UNION DISTINCT
     SELECT l.id, r.id FROM fit_sample AS l JOIN fit_sample AS r
       ON l.full_name = r.full_name AND l.address_code = r.address_code AND l.phone = r.phone AND l.id < r.id
  )) AS found,
  (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample
     WHERE customer_id IS NOT NULL AND full_name IS NOT NULL GROUP BY customer_id, full_name)) AS cif_name,
  (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample
     WHERE customer_id IS NOT NULL AND company_name IS NOT NULL GROUP BY customer_id, company_name)) AS cif_company,
  (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample
     WHERE full_name IS NOT NULL AND address_code IS NOT NULL AND phone IS NOT NULL GROUP BY full_name, address_code, phone)) AS name_code_phone;


-- 3. EM's pairs, a session a key: the sample's pairs sharing a phone, then an address, each pattern of levels with
--    its count. A comparison the key chose its pairs by can't be learned from them: NULL in its session.
CREATE OR REPLACE TABLE em_patterns AS
WITH paired AS (  -- each session's pairs, the two records whole, their names' Jaro–Winkler once (name_score)
  SELECT 'phone' AS session, l, r, name_score(l, r) AS s_name FROM fit_sample AS l JOIN fit_sample AS r ON l.phone = r.phone AND l.id < r.id
  UNION ALL
  SELECT 'address', l, r, name_score(l, r) FROM fit_sample AS l JOIN fit_sample AS r ON l.address__address = r.address__address AND l.id < r.id
)
SELECT session, name, company, address, phone, cif, birth, COUNT(*) AS pairs
FROM (
  SELECT session, name_level(l, r, s_name) AS name, gamma_company(l, r) AS company,
         IF(session = 'address', CAST(NULL AS INT64), gamma_address(l, r)) AS address,
         IF(session = 'phone', CAST(NULL AS INT64), gamma_phone(l, r)) AS phone, gamma_cif(l, r) AS cif, gamma_birth(l, r) AS birth
  FROM paired
)
GROUP BY 1, 2, 3, 4, 5, 6, 7;


-- 4. u: how often two different customers land in each level, on the sample (what the model is learned with) and on
--    the file (what it scores with: in a bigger file, a field whose values grow with it agrees by chance less often).
--    A level of equality (and a near level of one edit after its column's equality) is counted exactly from how many
--    records hold each value, never pair by pair: a sample would miss an agreement rarer than one pair in a billion.
--    The rest is Splink's random sample of about max_pairs pairs.
CREATE OR REPLACE VIEW u_records AS
SELECT 'sample' AS scope, * FROM fit_sample
UNION ALL
SELECT 'file', * FROM compared;

-- 4a. Each comparison's pairs outside its missing level: every pair, less those where each of its columns is empty on
--     a side. A record's mask: which of the comparison's columns it fills; two masks sharing none make missing pairs.
CREATE OR REPLACE TEMP TABLE u_masks AS
SELECT scope, 'name' AS comparison, IF(person_name IS NOT NULL, 1, 0) AS mask, COUNT(*) AS n FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'company', IF(company_name IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'address', IF(address_code IS NOT NULL, 1, 0) + IF(address IS NOT NULL, 2, 0) + IF(postal_code IS NOT NULL, 4, 0), COUNT(*)
          FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'phone', IF(phone IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'cif', IF(customer_id IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'birth', IF(birth_date IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE u_outside AS
WITH every AS (SELECT scope, DIV(COUNT(*) * (COUNT(*) - 1), 2) AS pairs FROM u_records GROUP BY scope),
missing AS (
  SELECT a.scope, a.comparison, SUM(IF(a.mask = b.mask, DIV(a.n * (a.n - 1), 2), a.n * b.n)) AS pairs
  FROM u_masks AS a JOIN u_masks AS b ON a.scope = b.scope AND a.comparison = b.comparison AND a.mask <= b.mask AND (a.mask & b.mask) = 0
  GROUP BY a.scope, a.comparison
)
SELECT c.scope, c.comparison, every.pairs - COALESCE(missing.pairs, 0) AS pairs
FROM (SELECT DISTINCT scope, comparison FROM u_masks) AS c JOIN every USING (scope) LEFT JOIN missing USING (scope, comparison);

-- 4b. The levels of equality, up to each comparison's first fuzzy level: the pairs equal on a set of columns (all
--     filled) are Σ n(n−1)/2 over its values; a level that follows others counts the pairs equal on it and on none
--     before it, by inclusion–exclusion (sign).
CREATE OR REPLACE TABLE u_counted AS
SELECT scope, comparison, label, SUM(sign * DIV(n * (n - 1), 2)) AS pairs
FROM (
  SELECT scope, 'name' AS comparison, 'exact' AS label, 1 AS sign, COUNT(*) AS n
  FROM u_records WHERE person_name IS NOT NULL GROUP BY scope, person_name
  UNION ALL SELECT scope, 'name', 'fold exact', 1, COUNT(*)
  FROM u_records WHERE person_name__kana_fold IS NOT NULL GROUP BY scope, person_name__kana_fold
  UNION ALL SELECT scope, 'name', 'fold exact', -1, COUNT(*)
  FROM u_records WHERE person_name IS NOT NULL AND person_name__kana_fold IS NOT NULL GROUP BY scope, person_name, person_name__kana_fold
  UNION ALL SELECT scope, 'name', 'same reading', 1, COUNT(*)
  FROM u_records WHERE person_name__kana_fold_long_vowel IS NOT NULL GROUP BY scope, person_name__kana_fold_long_vowel
  UNION ALL SELECT scope, 'name', 'same reading', -1, COUNT(*)
  FROM u_records WHERE person_name IS NOT NULL AND person_name__kana_fold_long_vowel IS NOT NULL
  GROUP BY scope, person_name, person_name__kana_fold_long_vowel
  UNION ALL SELECT scope, 'name', 'same reading', -1, COUNT(*)
  FROM u_records WHERE person_name__kana_fold IS NOT NULL AND person_name__kana_fold_long_vowel IS NOT NULL
  GROUP BY scope, person_name__kana_fold, person_name__kana_fold_long_vowel
  UNION ALL SELECT scope, 'name', 'same reading', 1, COUNT(*)
  FROM u_records WHERE person_name IS NOT NULL AND person_name__kana_fold IS NOT NULL AND person_name__kana_fold_long_vowel IS NOT NULL
  GROUP BY scope, person_name, person_name__kana_fold, person_name__kana_fold_long_vowel
  UNION ALL SELECT scope, 'company', 'exact', 1, COUNT(*)
  FROM u_records WHERE company_name__nfkc_strip_legal_form_kana_fold IS NOT NULL GROUP BY scope, company_name__nfkc_strip_legal_form_kana_fold
  UNION ALL SELECT scope, 'address', 'same address', 1, COUNT(*) FROM u_records WHERE address_code IS NOT NULL GROUP BY scope, address_code
  UNION ALL SELECT scope, 'address', 'same address', 1, COUNT(*) FROM u_records WHERE address__address IS NOT NULL GROUP BY scope, address__address
  UNION ALL SELECT scope, 'address', 'same address', -1, COUNT(*)
  FROM u_records WHERE address_code IS NOT NULL AND address__address IS NOT NULL GROUP BY scope, address_code, address__address
  UNION ALL SELECT scope, 'phone', 'exact', 1, COUNT(*) FROM u_records WHERE phone IS NOT NULL GROUP BY scope, phone
  UNION ALL SELECT scope, 'cif', 'exact', 1, COUNT(*) FROM u_records WHERE customer_id IS NOT NULL GROUP BY scope, customer_id
  UNION ALL SELECT scope, 'birth', 'exact', 1, COUNT(*) FROM u_records WHERE birth_date IS NOT NULL GROUP BY scope, birth_date
)
GROUP BY scope, comparison, label;

-- 4c. One edit after equality, by keys, never pair by pair: values of one length one substitution apart share exactly
--     one key (the value without its i-th character, at i), two neighbours swapped apart exactly one (Damerau: the
--     pair in order, at i), so a key's records pair (Σn)² − Σn² over 2 ways; a value one character longer is one
--     deletion away (Hamming, which pads the shorter, its last character), joined on the shorter values.
CREATE OR REPLACE TEMP TABLE u_values AS
SELECT scope, 'phone' AS comparison, phone AS x, COUNT(*) AS n, LENGTH(phone) AS len FROM u_records WHERE phone IS NOT NULL GROUP BY scope, phone
UNION ALL SELECT scope, 'cif', customer_id, COUNT(*), LENGTH(customer_id) FROM u_records WHERE customer_id IS NOT NULL GROUP BY scope, customer_id
UNION ALL SELECT scope, 'birth', birth_date, COUNT(*), LENGTH(birth_date) FROM u_records WHERE birth_date IS NOT NULL GROUP BY scope, birth_date;

CREATE OR REPLACE TABLE u_near AS
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
                 SUBSTR(x, 1, i - 1) || LEAST(SUBSTR(x, i, 1), SUBSTR(x, i + 1, 1)) || GREATEST(SUBSTR(x, i, 1), SUBSTR(x, i + 1, 1)) || SUBSTR(x, i + 2))
  GROUP BY scope, comparison
),
shorter AS (  -- each value with a character deleted: Hamming its last; else each, a run of equal characters once
  SELECT scope, comparison, x, n, len, SUBSTR(x, 1, len - 1) AS d FROM u_values WHERE comparison = 'phone'
  UNION ALL
  SELECT scope, comparison, x, n, len, SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1) FROM u_values, UNNEST(GENERATE_ARRAY(1, len + 1)) AS i
  WHERE comparison <> 'phone' AND (i = 1 OR i > len OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1))
),
longer AS (
  SELECT scope, comparison, SUM(nn) AS pairs
  FROM (SELECT DISTINCT a.scope, a.comparison, a.x AS ax, b.x AS bx, a.n * b.n AS nn FROM shorter AS a JOIN u_values AS b
        ON b.scope = a.scope AND b.comparison = a.comparison AND b.x = a.d AND b.len = a.len - 1)
  GROUP BY scope, comparison
)
SELECT c.scope, c.comparison, 'one digit off' AS label, COALESCE(s.pairs, 0) + COALESCE(w.pairs, 0) + COALESCE(l.pairs, 0) AS pairs
FROM (SELECT DISTINCT scope, comparison FROM u_outside WHERE comparison IN ('phone', 'cif', 'birth')) AS c
LEFT JOIN substituted AS s USING (scope, comparison)
LEFT JOIN swapped AS w USING (scope, comparison)
LEFT JOIN longer AS l USING (scope, comparison);

-- 4d. The records, and how many fill the column a comparison is filled most by: what bounds a level no sampled pair
--     reached
CREATE OR REPLACE TABLE u_filled AS
SELECT
  scope, COUNT(*) AS records, COUNT(person_name) AS name, COUNT(company_name) AS company,
  GREATEST(COUNT(address_code), COUNT(address), COUNT(postal_code)) AS address,
  COUNT(phone) AS phone, COUNT(customer_id) AS cif, COUNT(birth_date) AS birth
FROM u_records GROUP BY scope;

-- 4e. The rest sampled, as Splink samples: the records whose hash of ID and seed falls under their scope's cut, every
--     pair of them, each pair's level of each comparison, counted. A comparison counted to its else level (each of
--     its levels counted, pairs left for its else level) isn't sampled. An update samples only once refresh would
--     sample a comparison again (em.py's stale: resampled, from the counts above); else its sample would go unused.
CREATE OR REPLACE TEMP TABLE u_plan AS
SELECT
  o.scope,
  COALESCE(LOGICAL_OR(o.comparison = 'phone' AND NOT (c.pairs > 0 AND n.pairs > 0 AND c.pairs + n.pairs < o.pairs)), TRUE) AS phone,
  COALESCE(LOGICAL_OR(o.comparison = 'cif' AND NOT (c.pairs > 0 AND n.pairs > 0 AND c.pairs + n.pairs < o.pairs)), TRUE) AS cif,
  COALESCE(LOGICAL_OR(o.comparison = 'birth' AND NOT (c.pairs > 0 AND n.pairs > 0 AND c.pairs + n.pairs < o.pairs)), TRUE) AS birth
FROM u_outside AS o
JOIN u_counted AS c ON c.scope = o.scope AND c.comparison = o.comparison AND c.label = 'exact'
JOIN u_near AS n ON n.scope = o.scope AND n.comparison = o.comparison
GROUP BY o.scope;

-- when: NOT @refit
CREATE OR REPLACE TEMP TABLE u_again AS  -- the comparisons an update samples again, comma-separated: none, mostly
SELECT resampled(TO_JSON_STRING(STRUCT(
  (SELECT ARRAY_AGG(t) FROM levels AS t) AS levels, (SELECT ARRAY_AGG(t) FROM u_outside AS t) AS outside,
  (SELECT ARRAY_AGG(t) FROM u_counted AS t) AS counted, (SELECT ARRAY_AGG(t) FROM u_near AS t) AS near,
  (SELECT ARRAY_AGG(t) FROM u_filled AS t) AS filled, (SELECT ARRAY_AGG(t) FROM u_plan AS t) AS plan
)), @settings, (SELECT fitted FROM fit)) AS comparisons;

-- when: @refit
CREATE OR REPLACE TEMP TABLE u_again AS SELECT 'each' AS comparisons;  -- a build samples, as fit_model's learn needs

CREATE TABLE IF NOT EXISTS u_sampled (scope STRING, comparison STRING, gamma INT64, pairs INT64);  -- where none was ever drawn

-- when: (SELECT comparisons FROM u_again) <> ''
CREATE OR REPLACE TEMP TABLE u_drawn AS  -- the share: of a scope's n records, about max_pairs pairs, as Splink draws
WITH share AS (
  SELECT 'sample' AS scope, CAST(0.5 AS FLOAT64) * (SQRT(8 * @fit_u_max_pairs + 1) + 1) / GREATEST((SELECT COUNT(*) FROM fit_sample), 1) AS share
  UNION ALL
  SELECT 'file', CAST(0.5 AS FLOAT64) * (SQRT(8 * @u_max_pairs + 1) + 1) / GREATEST((SELECT COUNT(*) FROM records), 1)
)
SELECT u_records.* FROM u_records JOIN share USING (scope)
WHERE share >= 1 OR MOD(er_hash(id || '_' || @seed), 1000000000) < GREATEST(1, ROUND(share * 1000000000));

-- when: (SELECT comparisons FROM u_again) <> ''
CREATE OR REPLACE TEMP TABLE u_patterns AS  -- the pairs' patterns of levels, counted as they are made: none is stored
WITH paired AS (  -- the drawn pairs, the two records whole, their names' Jaro–Winkler once (name_score)
  SELECT l.scope, l, r, name_score(l, r) AS s_name FROM u_drawn AS l JOIN u_drawn AS r ON l.scope = r.scope AND l.id < r.id
)
SELECT
  p.scope, name_level(p.l, p.r, p.s_name) AS name, gamma_company(p.l, p.r) AS company, gamma_address(p.l, p.r) AS address,
  IF(plan.phone, gamma_phone(p.l, p.r), NULL) AS phone, IF(plan.cif, gamma_cif(p.l, p.r), NULL) AS cif, IF(plan.birth, gamma_birth(p.l, p.r), NULL) AS birth,
  COUNT(*) AS pairs
FROM paired AS p JOIN u_plan AS plan ON plan.scope = p.scope
GROUP BY 1, 2, 3, 4, 5, 6, 7;

-- when: (SELECT comparisons FROM u_again) <> ''
CREATE OR REPLACE TABLE u_sampled AS
SELECT scope, 'name' AS comparison, name AS gamma, SUM(pairs) AS pairs FROM u_patterns GROUP BY scope, name
UNION ALL SELECT scope, 'company', company, SUM(pairs) FROM u_patterns GROUP BY scope, company
UNION ALL SELECT scope, 'address', address, SUM(pairs) FROM u_patterns GROUP BY scope, address
UNION ALL SELECT scope, 'phone', phone, SUM(pairs) FROM u_patterns WHERE phone IS NOT NULL GROUP BY scope, phone
UNION ALL SELECT scope, 'cif', cif, SUM(pairs) FROM u_patterns WHERE cif IS NOT NULL GROUP BY scope, cif
UNION ALL SELECT scope, 'birth', birth, SUM(pairs) FROM u_patterns WHERE birth IS NOT NULL GROUP BY scope, birth;


-- 5. The model: fit_model learns it from every count above, given as one JSON text, and gives it back as one: each
--    level's m and u as fitted on the sample, and its m and u on the file (file_m, file_u, what scores read).
CREATE OR REPLACE TEMP TABLE learned AS
SELECT fit_model(TO_JSON_STRING(STRUCT(
  (SELECT ARRAY_AGG(t) FROM levels AS t) AS levels, (SELECT ARRAY_AGG(t) FROM fit_prior AS t) AS prior,
  (SELECT ARRAY_AGG(t) FROM em_patterns AS t) AS patterns, (SELECT ARRAY_AGG(t) FROM u_outside AS t) AS outside,
  (SELECT ARRAY_AGG(t) FROM u_counted AS t) AS counted, (SELECT ARRAY_AGG(t) FROM u_near AS t) AS near,
  (SELECT ARRAY_AGG(t) FROM u_sampled AS t) AS sampled, (SELECT ARRAY_AGG(t) FROM u_filled AS t) AS filled,
  (SELECT ARRAY_AGG(t) FROM u_plan AS t) AS plan
)), @settings, IF(@refit, NULL, (SELECT fitted FROM fit))) AS out;

CREATE OR REPLACE TABLE model AS
SELECT
  CAST(JSON_VALUE(lv, '$.position') AS INT64) AS position, JSON_VALUE(lv, '$.comparison') AS comparison,
  CAST(JSON_VALUE(lv, '$.gamma') AS INT64) AS gamma, JSON_VALUE(lv, '$.label') AS label, JSON_VALUE(lv, '$.kind') AS kind,
  CAST(JSON_VALUE(lv, '$.m') AS FLOAT64) AS m, CAST(JSON_VALUE(lv, '$.u') AS FLOAT64) AS u,
  CAST(JSON_VALUE(lv, '$.file_m') AS FLOAT64) AS file_m, CAST(JSON_VALUE(lv, '$.file_u') AS FLOAT64) AS file_u,
  CAST(JSON_VALUE(lv, '$.bits') AS FLOAT64) AS bits
FROM learned, UNNEST(JSON_QUERY_ARRAY(out, '$.levels')) AS lv;

CREATE OR REPLACE TABLE fit AS
SELECT CAST(JSON_VALUE(out, '$.probability') AS FLOAT64) AS probability, CAST(JSON_VALUE(out, '$.fit_rows') AS INT64) AS fit_rows,
       CAST(JSON_VALUE(out, '$.records') AS INT64) AS records,
       CAST(JSON_VALUE(out, '$.prior_bits') AS FLOAT64) AS prior_bits, JSON_QUERY(out, '$.notes') AS notes, out AS fitted
FROM learned;
