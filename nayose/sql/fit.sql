-- Stage 2 (fit) learns the model that weighs a pair, Fellegi–Sunter as Splink 5.0 fits it. It learns from counts made
-- on a sample of a fixed size, so its cost doesn't grow with the file. λ comes from the pairs the near-certain rules
-- find, m from EM's pairs, and u from pairs counted exactly or sampled. u is counted again on the file to be scored,
-- because the scores use the file's u. The sample and the file are the two scopes. fit_model (nayose/em.py, a Python
-- function on both engines) learns the model from the counts. Every count is an exact integer. The comparisons are
-- functions.sql's. O(n + P_prior + P_em·K) on the sample of n records, and O(N + max_pairs·K) for u on each scope.
--
-- A build runs this stage; an update doesn't, and scores with the model the build left. A build given a model
-- (@refit false: scripts/benchmark.py's, fitted on another file) draws no sample and runs no EM, and measures that
-- model's u on its records.
--
-- @refit acts on the data, not by skipping a statement (no statement here has a `-- when:` line). With @refit false,
-- fit_sample is empty, so the sample's counts and EM's pairs are empty too, and learned's one IF hands fit's model to
-- fit_model, which keeps it.
--
-- Reads: records, and with @refit false the model given (fit).
-- Values: @fit_records, @seed, @fit_u_max_pairs, @u_max_pairs and @settings come from config.toml [fit]. @fit_records
-- is the sample's size, in records. @seed seeds the hash that draws u's sampled pairs. @fit_u_max_pairs and
-- @u_max_pairs are about how many pairs u samples on the sample and on the file. @settings is all of [fit] as JSON,
-- for fit_model.
-- @refit is false for a build given a model, which learns none.
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
CREATE TABLE IF NOT EXISTS fit (probability FLOAT64, fit_records INT64, records INT64, prior_bits FLOAT64, notes STRING,
                                fitted STRING);


-- 1. compared holds the columns that the comparisons, the near-certain rules and EM's keys read. Only these columns
--    are read, so only these are billed. The sample takes postal areas whole, in the order of their hash, until it
--    holds @fit_records records, and cuts the last area by its records' hash. So a household's records stay together,
--    but in that last area, and a smaller sample is part of a bigger one.
CREATE OR REPLACE VIEW compared AS
SELECT
  id, person_name, full_name, given_name__kana_fold, person_name__kana_fold, person_name__kana_fold_long_vowel,
  person_name__kana_fold_one_byte, person_name__kana_fold_letters_lo, person_name__kana_fold_letters_hi,
  company_name, company_name__nfkc_strip_legal_form_kana_fold,
  company_name__nfkc_strip_legal_form_kana_fold_one_byte, address_code, address, address__address,
  address__address_one_byte_hash, postal_code, phone, customer_id, birth_date
FROM records;

-- A build given a model (@refit false) learns none, so its sample is empty.
CREATE OR REPLACE TEMP TABLE fit_sample AS
SELECT compared.* FROM compared
JOIN (SELECT id FROM records WHERE @refit ORDER BY er_hash(postal_code__first3), er_hash(id) LIMIT @fit_records)
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
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM compared)
SELECT scope, 'name' AS comparison, IF(person_name IS NOT NULL, 1, 0) AS mask, COUNT(*) AS n
FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'company', IF(company_name IS NOT NULL, 1, 0) AS mask, COUNT(*) FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'address',
                 IF(address_code IS NOT NULL, 1, 0) + IF(address IS NOT NULL, 2, 0) + IF(postal_code IS NOT NULL, 4, 0)
                   AS mask,
                 COUNT(*)
          FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'phone', IF(phone IS NOT NULL, 1, 0) AS mask, COUNT(*) FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'cif', IF(customer_id IS NOT NULL, 1, 0) AS mask, COUNT(*) FROM u_records GROUP BY scope, mask
UNION ALL SELECT scope, 'birth', IF(birth_date IS NOT NULL, 1, 0) AS mask, COUNT(*) FROM u_records GROUP BY scope, mask;

CREATE OR REPLACE TEMP TABLE u_outside AS
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM compared),
all_pairs AS (SELECT scope, pairs_of(COUNT(*)) AS pairs FROM u_records GROUP BY scope),
missing AS (
  SELECT a.scope, a.comparison, SUM(IF(a.mask = b.mask, pairs_of(a.n), a.n * b.n)) AS pairs
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
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM compared)
SELECT scope, comparison, label, SUM(sign * pairs_of(n)) AS pairs
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
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM compared)
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
--     @seed falls under the scope's cut. Every pair of a scope's drawn records gets its level in each comparison,
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

-- records_for_pairs returns how many records make about max_pairs pairs. k records make k(k−1)/2 pairs, so about
-- max_pairs pairs take k = (√(8·max_pairs + 1) + 1) / 2 records.
CREATE OR REPLACE TEMP FUNCTION records_for_pairs(max_pairs FLOAT64) AS (
  CAST(0.5 AS FLOAT64) * (SQRT(8 * max_pairs + 1) + 1)
);

-- Each scope draws the share k / n of its n records, as Splink does, and all its records if the share is 1 or more.
-- A record is drawn if its hash, read in billionths (MOD 1,000,000,000), falls under the share, so a share is drawn
-- to the nearest billionth, and at least one billionth.
CREATE OR REPLACE TEMP TABLE u_drawn AS
WITH u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM compared),
shares AS (
  SELECT 'sample' AS scope, records_for_pairs(@fit_u_max_pairs) / GREATEST((SELECT COUNT(*) FROM fit_sample), 1) AS share
  UNION ALL
  SELECT 'file', records_for_pairs(@u_max_pairs) / GREATEST((SELECT COUNT(*) FROM records), 1)
)
SELECT u_records.* FROM u_records JOIN shares USING (scope)
WHERE share >= 1 OR MOD(er_hash(id || '_' || @seed), 1000000000) < GREATEST(1, ROUND(share * 1000000000));

-- Each pattern of levels that the drawn pairs make is counted as the pairs are made, so no pair is stored. A
-- comparison that u_plan doesn't sample is NULL.
CREATE OR REPLACE TEMP TABLE u_patterns AS
WITH paired AS (  -- a pair keeps its two records whole, and name_score runs once a pair for name_level
  SELECT x.scope, x, y, name_score(x, y) AS s_name
  FROM u_drawn AS x JOIN u_drawn AS y ON x.scope = y.scope AND x.id < y.id
)
SELECT scope, name, company, address, phone, cif, birth, COUNT(*) AS pairs
FROM (  -- a subquery, so that the GROUP BY's phone, cif and birth name the levels, not u_plan's columns of those names
  SELECT
    p.scope, name_level(p.x, p.y, p.s_name) AS name, gamma_company(p.x, p.y) AS company,
    gamma_address(p.x, p.y) AS address, IF(plan.phone, gamma_phone(p.x, p.y), NULL) AS phone,
    IF(plan.cif, gamma_cif(p.x, p.y), NULL) AS cif, IF(plan.birth, gamma_birth(p.x, p.y), NULL) AS birth
  FROM paired AS p JOIN u_plan AS plan ON plan.scope = p.scope
)
GROUP BY scope, name, company, address, phone, cif, birth;

-- 3. fit_model learns the model. It takes counts, settings (@settings) and given_fit (a build given a model passes
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
    (SELECT COALESCE(SUM(pairs_of(n)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample  -- X1's pairs
       WHERE customer_id IS NOT NULL AND full_name IS NOT NULL GROUP BY customer_id, full_name)) AS cif_name,
    (SELECT COALESCE(SUM(pairs_of(n)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample  -- X2's pairs
       WHERE customer_id IS NOT NULL AND company_name IS NOT NULL GROUP BY customer_id, company_name)) AS cif_company,
    (SELECT COALESCE(SUM(pairs_of(n)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample  -- X4's pairs
       WHERE full_name IS NOT NULL AND address_code IS NOT NULL AND phone IS NOT NULL
       GROUP BY full_name, address_code, phone)) AS name_code_phone
),
-- EM learns in sessions, one for each field it pairs records by ([fit] em_sessions). The phone session's pairs are
-- the sample's pairs that share a phone, and the address session's share an address. Each pattern of levels is
-- stored once, with its count of pairs. A session can't learn the comparison its field chose the pairs by, as
-- every pair agrees on it, so that comparison is NULL in its session.
em_pairs AS (  -- a pair keeps its two records whole, and name_score runs once a pair for name_level
  SELECT 'phone' AS session, x, y, name_score(x, y) AS s_name
  FROM fit_sample AS x JOIN fit_sample AS y ON x.phone = y.phone AND x.id < y.id
  UNION ALL
  SELECT 'address', x, y, name_score(x, y)
  FROM fit_sample AS x JOIN fit_sample AS y ON x.address__address = y.address__address AND x.id < y.id
),
em_patterns AS (
  SELECT session, name, company, address, phone, cif, birth, COUNT(*) AS pairs
  FROM (
    SELECT session, name_level(x, y, s_name) AS name, gamma_company(x, y) AS company,
           IF(session = 'address', CAST(NULL AS INT64), gamma_address(x, y)) AS address,
           IF(session = 'phone', CAST(NULL AS INT64), gamma_phone(x, y)) AS phone, gamma_cif(x, y) AS cif,
           gamma_birth(x, y) AS birth
    FROM em_pairs
  )
  GROUP BY session, name, company, address, phone, cif, birth
),
-- u_filled counts each scope's records, and for each comparison the records that fill its column. For address it
-- takes the most filled of its three columns. From these, fit_model estimates how many sampled pairs fill each
-- comparison, and that number bounds the u of a level that no sampled pair reached.
u_records AS (SELECT 'sample' AS scope, * FROM fit_sample UNION ALL SELECT 'file', * FROM compared),
u_filled AS (
  SELECT
    scope, COUNT(*) AS records, COUNT(person_name) AS name, COUNT(company_name) AS company,
    GREATEST(COUNT(address_code), COUNT(address), COUNT(postal_code)) AS address,
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
SELECT fit_model(TO_JSON_STRING(STRUCT(
  (SELECT ARRAY_AGG(t) FROM levels AS t) AS levels, (SELECT ARRAY_AGG(t) FROM fit_prior AS t) AS prior,
  (SELECT ARRAY_AGG(t) FROM em_patterns AS t) AS patterns, (SELECT ARRAY_AGG(t) FROM u_outside AS t) AS outside,
  (SELECT ARRAY_AGG(t) FROM u_counted AS t) AS counted, (SELECT ARRAY_AGG(t) FROM u_one_edit AS t) AS one_edit,
  (SELECT ARRAY_AGG(t) FROM u_sampled AS t) AS sampled, (SELECT ARRAY_AGG(t) FROM u_filled AS t) AS filled,
  (SELECT ARRAY_AGG(t) FROM u_plan AS t) AS plan
)), @settings, IF(@refit, NULL, (SELECT fitted FROM fit))) AS out;

CREATE OR REPLACE TABLE model AS
SELECT
  CAST(JSON_VALUE(lv, '$.position') AS INT64) AS position, JSON_VALUE(lv, '$.comparison') AS comparison,
  CAST(JSON_VALUE(lv, '$.gamma') AS INT64) AS gamma, JSON_VALUE(lv, '$.label') AS label,
  JSON_VALUE(lv, '$.agreement') AS agreement,
  CAST(JSON_VALUE(lv, '$.m') AS FLOAT64) AS m, CAST(JSON_VALUE(lv, '$.u') AS FLOAT64) AS u,
  CAST(JSON_VALUE(lv, '$.file_m') AS FLOAT64) AS file_m, CAST(JSON_VALUE(lv, '$.file_u') AS FLOAT64) AS file_u,
  CAST(JSON_VALUE(lv, '$.bits') AS FLOAT64) AS bits
FROM learned, UNNEST(JSON_QUERY_ARRAY(out, '$.levels')) AS lv;

CREATE OR REPLACE TABLE fit AS
SELECT CAST(JSON_VALUE(out, '$.probability') AS FLOAT64) AS probability,
       CAST(JSON_VALUE(out, '$.fit_records') AS INT64) AS fit_records,
       CAST(JSON_VALUE(out, '$.records') AS INT64) AS records,
       CAST(JSON_VALUE(out, '$.prior_bits') AS FLOAT64) AS prior_bits, JSON_QUERY(out, '$.notes') AS notes, out AS fitted
FROM learned;
