-- Stage 2 (fit) learns the model that weighs a pair, Fellegi–Sunter as Splink 5.0 fits it. It learns from counts made
-- on a sample of a fixed size, so its cost doesn't grow with the file. λ comes from the pairs the near-certain rules
-- find, m from EM's pairs, and u from pairs counted exactly or sampled. u is counted again on the file to be scored,
-- because the scores use the file's u. The sample and the file are the two scopes. fit_model (nayose/em.py, a Python
-- function on both engines) learns the model from the counts. Every count is an exact integer. The comparisons are
-- functions.sql's. O(n + P_prior + P_em·K) on the sample of n records, and O(N + max_pairs·K) for u on each scope.
--
-- An update (@refit false) keeps the model that the run's build fitted, so it draws no sample and runs no EM. It
-- measures u again on the run's records, and fit_model starts from the stored fit. It samples a comparison's u again
-- only once the comparison has gone stale.
--
-- A statement that follows a `-- when: <condition>` line runs only if the condition holds: run_file checks it
-- locally, and the deployed procedure wraps the statement in IF … END IF.
--
-- Reads: records, levels (functions.sql), and on an update fit and u_sampled as the last job left them.
-- Values: @fit_rows, @seed, @fit_u_max_pairs, @u_max_pairs and @settings come from config.toml [fit]. @fit_rows is the
-- sample's size, in records. @seed seeds the hash that draws u's sampled pairs. @fit_u_max_pairs and @u_max_pairs are
-- about how many pairs u samples on the sample and on the file. @settings is all of [fit] as JSON, for fit_model.
-- @refit is true for a build, which learns the model again.
-- Writes:
--   compared     a view of the columns that the fit and the scores read of a record
--   fit_sample   the sample, empty on an update
--   fit_prior    the sample's size and the pairs that the near-certain rules find in it
--   em_patterns  EM's patterns of levels, by session (one for each key)
--   u_records    a view of each scope's records
--   u_outside, u_counted, u_near and u_filled
--                u's exact counts, and the fill that bounds the u of a level no sampled pair reached
--   u_sampled    the sampled pairs' levels, counted. An update keeps the last job's unless it samples again.
--   model        each level's m and u as fitted on the sample, its file_m and file_u on the file, and its bits,
--                log2(file_m / file_u), which a score adds
--   fit          λ (probability), the sample's size, the file's size, prior_bits (the prior in bits at the file's
--                size), the notes the report reads, and fitted (fit_model's whole answer, which an update starts from)

CREATE TABLE IF NOT EXISTS fit (probability FLOAT64, fit_rows INT64, records INT64, prior_bits FLOAT64, notes STRING,
                                fitted STRING);


-- 1. compared holds the columns that the comparisons, the near-certain rules and EM's keys read. Only these columns
--    are read, so only these are billed. The sample takes postal areas whole, in the order of their hash, until it
--    holds @fit_rows records, and cuts the last area by its records' hash. So a household's records stay together,
--    but in that last area, and a smaller sample is part of a bigger one.
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
JOIN (SELECT id FROM records ORDER BY er_hash(postal_code__first3), er_hash(id) LIMIT @fit_rows) USING (id);

-- when: NOT @refit
-- An update learns nothing, so its sample is empty.
CREATE OR REPLACE TABLE fit_sample AS SELECT * FROM compared WHERE FALSE;


-- 2. λ is how likely two random records are one customer. fit_model estimates it from found, the pairs that any of
--    the near-certain rules find in the sample, each pair counted once. Each rule's own count is kept too, because a
--    rule that finds no pair in the sample is skipped, and the report names it.
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
     WHERE full_name IS NOT NULL AND address_code IS NOT NULL AND phone IS NOT NULL
     GROUP BY full_name, address_code, phone)) AS name_code_phone;


-- 3. EM learns in sessions, one for each key. The phone session's pairs are the sample's pairs that share a phone,
--    and the address session's share an address. Each pattern of levels is stored once, with its count of pairs. A
--    session can't learn the comparison its key chose the pairs by, as every pair agrees on it, so that comparison
--    is NULL in its session.
CREATE OR REPLACE TABLE em_patterns AS
WITH paired AS (  -- a pair keeps its two records whole, and name_score runs once a pair for name_level
  SELECT 'phone' AS session, l, r, name_score(l, r) AS s_name
  FROM fit_sample AS l JOIN fit_sample AS r ON l.phone = r.phone AND l.id < r.id
  UNION ALL
  SELECT 'address', l, r, name_score(l, r)
  FROM fit_sample AS l JOIN fit_sample AS r ON l.address__address = r.address__address AND l.id < r.id
)
SELECT session, name, company, address, phone, cif, birth, COUNT(*) AS pairs
FROM (
  SELECT session, name_level(l, r, s_name) AS name, gamma_company(l, r) AS company,
         IF(session = 'address', CAST(NULL AS INT64), gamma_address(l, r)) AS address,
         IF(session = 'phone', CAST(NULL AS INT64), gamma_phone(l, r)) AS phone, gamma_cif(l, r) AS cif,
         gamma_birth(l, r) AS birth
  FROM paired
)
GROUP BY 1, 2, 3, 4, 5, 6, 7;


-- 4. u is how often two different customers land in a level. It is counted on the sample, which the model is
--    learned with, and on the file, which the scores use. The two differ because in a bigger file, a field whose
--    values grow with the file agrees by chance less often. A comparison's equality levels before its first fuzzy
--    level are counted exactly, from how many records hold each value, never pair by pair. So is the one-edit level
--    that follows equality for phone, cif and birth. A sample of pairs would miss an agreement rarer than one pair
--    in a billion. The other levels' u comes from a random sample of about max_pairs pairs, drawn as Splink draws it.
CREATE OR REPLACE VIEW u_records AS
SELECT 'sample' AS scope, * FROM fit_sample
UNION ALL
SELECT 'file', * FROM compared;

-- 4a. u_outside counts each comparison's pairs outside its missing level, and each u is a share of these pairs. A
--     pair is missing if each of the comparison's columns is empty on at least one side. A record's mask has a bit
--     for each of the comparison's columns it fills, so two records make a missing pair if their masks share no bit.
--     u_outside is every pair less the missing ones.
CREATE OR REPLACE TEMP TABLE u_masks AS
SELECT scope, 'name' AS comparison, IF(person_name IS NOT NULL, 1, 0) AS mask, COUNT(*) AS n
FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'company', IF(company_name IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'address',
                 IF(address_code IS NOT NULL, 1, 0) + IF(address IS NOT NULL, 2, 0) + IF(postal_code IS NOT NULL, 4, 0),
                 COUNT(*)
          FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'phone', IF(phone IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'cif', IF(customer_id IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2, 3
UNION ALL SELECT scope, 'birth', IF(birth_date IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE u_outside AS
WITH every AS (SELECT scope, DIV(COUNT(*) * (COUNT(*) - 1), 2) AS pairs FROM u_records GROUP BY scope),
missing AS (
  SELECT a.scope, a.comparison, SUM(IF(a.mask = b.mask, DIV(a.n * (a.n - 1), 2), a.n * b.n)) AS pairs
  FROM u_masks AS a JOIN u_masks AS b
    ON a.scope = b.scope AND a.comparison = b.comparison AND a.mask <= b.mask AND (a.mask & b.mask) = 0
  GROUP BY a.scope, a.comparison
)
SELECT c.scope, c.comparison, every.pairs - COALESCE(missing.pairs, 0) AS pairs
FROM (SELECT DISTINCT scope, comparison FROM u_masks) AS c
JOIN every USING (scope) LEFT JOIN missing USING (scope, comparison);

-- 4b. u_counted counts each comparison's equality levels, up to its first fuzzy level. The pairs equal on a set of
--     columns, all filled, number Σ n(n−1)/2, with n the number of records holding each combination of values. A
--     level that follows others counts only the pairs equal on it and on no level before it. Address's 'same address'
--     level counts the pairs equal on the address code or on the address. Both come by inclusion–exclusion, and sign
--     adds or takes away each term.
CREATE OR REPLACE TABLE u_counted AS
SELECT scope, comparison, label, SUM(sign * DIV(n * (n - 1), 2)) AS pairs
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

-- 4c. u_near counts the one-edit level ('one digit off') that follows equality for phone, cif and birth. It counts
--     by keys, never pair by pair. Two values of one length that differ by one substitution share exactly one key,
--     the value without its i-th character, together with i. For cif and birth, Damerau–Levenshtein also counts two
--     swapped neighbours as one edit. Two such values share exactly one swap key, the value with its i-th and
--     (i+1)-th characters put in order, together with i. If a key's values are held by n records each, the key
--     makes ((Σn)² − Σn²) / 2 pairs of records whose values differ. A value one character longer than another is
--     one deletion away from it, so each longer value's deletions are joined to the shorter values.
CREATE OR REPLACE TEMP TABLE u_values AS
SELECT scope, 'phone' AS comparison, phone AS x, COUNT(*) AS n, LENGTH(phone) AS len
FROM u_records WHERE phone IS NOT NULL GROUP BY scope, phone
UNION ALL SELECT scope, 'cif', customer_id, COUNT(*), LENGTH(customer_id)
          FROM u_records WHERE customer_id IS NOT NULL GROUP BY scope, customer_id
UNION ALL SELECT scope, 'birth', birth_date, COUNT(*), LENGTH(birth_date)
          FROM u_records WHERE birth_date IS NOT NULL GROUP BY scope, birth_date;

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
       COALESCE(s.pairs, 0) + COALESCE(w.pairs, 0) + COALESCE(l.pairs, 0) AS pairs
FROM (SELECT DISTINCT scope, comparison FROM u_outside WHERE comparison IN ('phone', 'cif', 'birth')) AS c
LEFT JOIN substituted AS s USING (scope, comparison)
LEFT JOIN swapped AS w USING (scope, comparison)
LEFT JOIN longer AS l USING (scope, comparison);

-- 4d. u_filled counts each scope's records, and for each comparison the records that fill its column. For address it
--     takes the most filled of its three columns. From these, fit_model estimates how many sampled pairs fill each
--     comparison, and that number bounds the u of a level that no sampled pair reached.
CREATE OR REPLACE TABLE u_filled AS
SELECT
  scope, COUNT(*) AS records, COUNT(person_name) AS name, COUNT(company_name) AS company,
  GREATEST(COUNT(address_code), COUNT(address), COUNT(postal_code)) AS address,
  COUNT(phone) AS phone, COUNT(customer_id) AS cif, COUNT(birth_date) AS birth
FROM u_records GROUP BY scope;

-- 4e. The other levels' u is sampled as Splink samples it. A scope's records are drawn if the hash of their ID and
--     @seed falls under the scope's cut. Every pair of a scope's drawn records gets its level in each comparison,
--     and the levels are counted. A comparison isn't sampled if all its levels are counted exactly. That happens if
--     its exact and one-edit levels both hold pairs, and some pairs are left for its else level. u_plan tells, for
--     each scope, whether phone, cif and birth are sampled. The other comparisons have fuzzy levels, so they are
--     always sampled. An update samples only if refresh would sample some comparison again (em.py's stale, asked
--     through resampled). Otherwise its sample would go unused.
CREATE OR REPLACE TEMP TABLE u_plan AS
SELECT
  o.scope,
  COALESCE(LOGICAL_OR(o.comparison = 'phone' AND NOT (c.pairs > 0 AND n.pairs > 0 AND c.pairs + n.pairs < o.pairs)),
           TRUE) AS phone,
  COALESCE(LOGICAL_OR(o.comparison = 'cif' AND NOT (c.pairs > 0 AND n.pairs > 0 AND c.pairs + n.pairs < o.pairs)),
           TRUE) AS cif,
  COALESCE(LOGICAL_OR(o.comparison = 'birth' AND NOT (c.pairs > 0 AND n.pairs > 0 AND c.pairs + n.pairs < o.pairs)),
           TRUE) AS birth
FROM u_outside AS o
JOIN u_counted AS c ON c.scope = o.scope AND c.comparison = o.comparison AND c.label = 'exact'
JOIN u_near AS n ON n.scope = o.scope AND n.comparison = o.comparison
GROUP BY o.scope;

-- when: NOT @refit
CREATE OR REPLACE TEMP TABLE u_again AS  -- an update samples these comparisons again. Mostly there are none.
SELECT resampled(TO_JSON_STRING(STRUCT(
  (SELECT ARRAY_AGG(t) FROM levels AS t) AS levels, (SELECT ARRAY_AGG(t) FROM u_outside AS t) AS outside,
  (SELECT ARRAY_AGG(t) FROM u_counted AS t) AS counted, (SELECT ARRAY_AGG(t) FROM u_near AS t) AS near,
  (SELECT ARRAY_AGG(t) FROM u_filled AS t) AS filled, (SELECT ARRAY_AGG(t) FROM u_plan AS t) AS plan
)), @settings, (SELECT fitted FROM fit)) AS comparisons;

-- when: @refit
CREATE OR REPLACE TEMP TABLE u_again AS  -- a build always samples (em.py's learn needs it), so it lists them all
SELECT 'name,company,address,phone,cif,birth' AS comparisons;

-- u_sampled starts empty if no job has drawn a sample yet.
CREATE TABLE IF NOT EXISTS u_sampled (scope STRING, comparison STRING, gamma INT64, pairs INT64);

-- k records make k(k−1)/2 pairs, so about max_pairs pairs take k = (√(8·max_pairs + 1) + 1) / 2 of a scope's n
-- records. Each scope draws the share k / n, as Splink does, and all its records if the share is 1 or more.
-- when: (SELECT comparisons FROM u_again) <> ''
CREATE OR REPLACE TEMP TABLE u_drawn AS
WITH share AS (
  SELECT 'sample' AS scope,
         CAST(0.5 AS FLOAT64) * (SQRT(8 * @fit_u_max_pairs + 1) + 1) / GREATEST((SELECT COUNT(*) FROM fit_sample), 1)
           AS share
  UNION ALL
  SELECT 'file', CAST(0.5 AS FLOAT64) * (SQRT(8 * @u_max_pairs + 1) + 1) / GREATEST((SELECT COUNT(*) FROM records), 1)
)
SELECT u_records.* FROM u_records JOIN share USING (scope)
WHERE share >= 1 OR MOD(er_hash(id || '_' || @seed), 1000000000) < GREATEST(1, ROUND(share * 1000000000));

-- Each pattern of levels that the drawn pairs make is counted as the pairs are made, so no pair is stored. A
-- comparison that u_plan doesn't sample is NULL.
-- when: (SELECT comparisons FROM u_again) <> ''
CREATE OR REPLACE TEMP TABLE u_patterns AS
WITH paired AS (  -- a pair keeps its two records whole, and name_score runs once a pair for name_level
  SELECT l.scope, l, r, name_score(l, r) AS s_name
  FROM u_drawn AS l JOIN u_drawn AS r ON l.scope = r.scope AND l.id < r.id
)
SELECT
  p.scope, name_level(p.l, p.r, p.s_name) AS name, gamma_company(p.l, p.r) AS company,
  gamma_address(p.l, p.r) AS address, IF(plan.phone, gamma_phone(p.l, p.r), NULL) AS phone,
  IF(plan.cif, gamma_cif(p.l, p.r), NULL) AS cif, IF(plan.birth, gamma_birth(p.l, p.r), NULL) AS birth,
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


-- 5. fit_model learns the model from every count above, passed as one JSON text, and returns it as one JSON text. An
--    update also passes the stored fit, which fit_model starts from. The answer holds each level's m and u as fitted
--    on the sample, its file_m and file_u on the file, and its bits from those, which the scores add.
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
  CAST(JSON_VALUE(lv, '$.gamma') AS INT64) AS gamma, JSON_VALUE(lv, '$.label') AS label,
  JSON_VALUE(lv, '$.kind') AS kind,
  CAST(JSON_VALUE(lv, '$.m') AS FLOAT64) AS m, CAST(JSON_VALUE(lv, '$.u') AS FLOAT64) AS u,
  CAST(JSON_VALUE(lv, '$.file_m') AS FLOAT64) AS file_m, CAST(JSON_VALUE(lv, '$.file_u') AS FLOAT64) AS file_u,
  CAST(JSON_VALUE(lv, '$.bits') AS FLOAT64) AS bits
FROM learned, UNNEST(JSON_QUERY_ARRAY(out, '$.levels')) AS lv;

CREATE OR REPLACE TABLE fit AS
SELECT CAST(JSON_VALUE(out, '$.probability') AS FLOAT64) AS probability,
       CAST(JSON_VALUE(out, '$.fit_rows') AS INT64) AS fit_rows,
       CAST(JSON_VALUE(out, '$.records') AS INT64) AS records,
       CAST(JSON_VALUE(out, '$.prior_bits') AS FLOAT64) AS prior_bits, JSON_QUERY(out, '$.notes') AS notes, out AS fitted
FROM learned;
