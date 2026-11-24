-- Stage 3, score: the pairs worth scoring and their scores, as er/'s rules, candidates and score steps make them, for
-- the run's latest batch against all its records (a build: every record new). The rules' pairs; every pair a key
-- lists, each key's blocks of @oversized records or more checked on a sample first; each pair's level of each
-- comparison (functions.sql) and its weight from the model (the prior's bits and each level's, added in the model's
-- order, to the last bit). Kept: every pair from @keep_from bits up, and every rule pair: what a match run offers
-- people. Nothing merges. O(Δ·b) for the batch's pairs, plus O(N·L) to make every record's keys again.
--
-- Reads: records and this_batch (records.sql), compared (fit.sql), model and fit (each level's bits, the prior's
-- bits at the file's size). Values: @keys and @rules (by name: the generators and rules this run uses, config.toml
-- [score]), @keep_from (bits: where scored pairs are kept from), @search_floor (bits: a sampled pair at it or above
-- keeps its block), @oversized (a block of this many records or more is checked on a sample of as many of its records).
-- A pair's two records are x and y (l and r name its IDs: DuckDB reads a WHERE's l as the SELECT's, BigQuery as the table).
-- Writes: rule_pairs (the first rule in order naming each pair), cands (the pairs the batch's keys list, the keys that
-- listed each in sources), gated (each oversized block the batch reaches, its sample and whether it was kept), scored
-- (every pair kept). rule_pairs and scored hold every batch's; a batch adds the pairs touching its records.

CREATE OR REPLACE TEMP TABLE fresh AS SELECT id FROM records WHERE batch = (SELECT batch FROM this_batch);

-- The generators and the rules, by name, in order: a generator's position is its bit in sources, a rule's its rank
-- (the first in order names a pair). Those this run uses are config.toml's; a name it gives that isn't here is refused.
CREATE OR REPLACE TEMP TABLE generators AS
SELECT g, name, name IN UNNEST(@keys) AS used FROM UNNEST([
  'cif', 'phone_prefecture', 'phone_postal_area', 'phone_name_initial', 'person_name', 'company_name', 'company_name_deletions',
  'person_name_deletions_postal_area', 'given_name_postal', 'address_phone', 'address_code_phone', 'address_name_initial',
  'address_code_name_initial', 'given_name_address_code', 'cif_deletions', 'birth_date', 'given_name_phone',
  'birth_date_deletions_prefecture', 'name_reading', 'phone_given_tail', 'postal_given_tail', 'postal_area_given_tail'
]) AS name WITH OFFSET AS g;

CREATE OR REPLACE TEMP TABLE rules AS
SELECT i, rule, stage, rule IN UNNEST(@rules) AS used FROM UNNEST([
  STRUCT(0 AS i, 'X1_CIF_PERSON_NAME' AS rule, 'exact' AS stage), STRUCT(1, 'X2_CIF_COMPANY_NAME', 'exact'),
  STRUCT(2, 'X3_CIF_PHONE', 'exact'), STRUCT(3, 'X4_PERSON_NAME_ADDRCD_PHONE', 'exact'),
  STRUCT(4, 'X5_COMPANY_NAME_ADDRCD_PHONE', 'exact'), STRUCT(5, 'F1_NAME~_ADDRCD_PHONE', 'fuzzy'),
  STRUCT(6, 'F2_NAME~_ADDRESS~_PHONE', 'fuzzy'), STRUCT(7, 'F3_NAME~_CIF', 'fuzzy'), STRUCT(8, 'F4_NAME_ADDRCD_PHONE~', 'fuzzy'),
  STRUCT(9, 'F5_COMPANY~_PHONE_POSTAL', 'fuzzy'), STRUCT(10, 'F6_COMPANY~_ADDRCD_PHONE', 'fuzzy'), STRUCT(11, 'F7_GIVEN_ADDRCD_PHONE', 'fuzzy')
]);

SELECT IF(COUNT(*) > 0, ERROR(CONCAT('config.toml [score]: no generator or rule is named ', STRING_AGG(x, ', '),
                                     '; name those score.sql lists')), 0)
FROM (SELECT x FROM UNNEST(@keys) AS x WHERE x NOT IN (SELECT name FROM generators)
      UNION ALL SELECT x FROM UNNEST(@rules) AS x WHERE x NOT IN (SELECT rule FROM rules));


-- 1. The rules: each one join on its keys, its fuzzy tests on the pairs that join. A value of a rule's keys held by
--    @oversized records or more is not one customer's: the rule leaves it out (the model can still match them).
--    The batch's records against all: each pair once, the lower ID first.
CREATE OR REPLACE TEMP TABLE rule_keys AS  -- each rule's key of each record, with how many records hold it (n)
SELECT i, k, id, n, id IN (SELECT id FROM fresh) AS new FROM (
  SELECT i, k, id, COUNT(*) OVER (PARTITION BY i, k) AS n FROM (
    SELECT 0 AS i, customer_id || CHR(31) || full_name AS k, id FROM records
    UNION ALL SELECT 1, customer_id || CHR(31) || company_name, id FROM records
    UNION ALL SELECT 2, customer_id || CHR(31) || phone, id FROM records
    UNION ALL SELECT 3, full_name || CHR(31) || address_code || CHR(31) || phone, id FROM records
    UNION ALL SELECT 4, company_name || CHR(31) || address_code || CHR(31) || phone, id FROM records
    UNION ALL SELECT 5, address_code || CHR(31) || phone, id FROM records
    UNION ALL SELECT 6, phone || CHR(31) || address__address_first3, id FROM records
    UNION ALL SELECT 7, customer_id, id FROM records
    UNION ALL SELECT 8, person_name || CHR(31) || address_code, id FROM records
    UNION ALL SELECT 9, phone || CHR(31) || postal_code, id FROM records
    UNION ALL SELECT 10, address_code || CHR(31) || phone, id FROM records
    UNION ALL SELECT 11, given_name || CHR(31) || address_code || CHR(31) || phone, id FROM records
  ) WHERE k IS NOT NULL AND i IN (SELECT i FROM rules WHERE used)
);

CREATE TABLE IF NOT EXISTS rule_pairs (l STRING, r STRING, rule STRING, stage STRING);

CREATE OR REPLACE TEMP TABLE batch_rule_pairs AS
WITH found AS (
  SELECT a.i, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
  FROM rule_keys AS a JOIN rule_keys AS b ON a.i = b.i AND a.k = b.k AND a.id <> b.id AND (NOT b.new OR a.id < b.id)
  JOIN records AS x ON x.id = a.id JOIN records AS y ON y.id = b.id
  WHERE a.new AND a.n < @oversized
    AND CASE a.i WHEN 5 THEN near_name(x, y) WHEN 6 THEN near_name(x, y) AND near_address(x, y) WHEN 7 THEN near_name(x, y)
                 WHEN 8 THEN near_phone(x, y) WHEN 9 THEN near_company(x, y) WHEN 10 THEN near_company(x, y) ELSE TRUE END
)
SELECT f.l, f.r, rules.rule, rules.stage
FROM (SELECT l, r, MIN(i) AS i FROM found GROUP BY l, r) AS f JOIN rules USING (i);

INSERT INTO rule_pairs SELECT * FROM batch_rule_pairs;


-- 2. The keys: each generator's block of each record, its keys joined (a deletion key's: the value with each one
--    character deleted, a run of equal characters once, and the value whole, within its other keys). In the order of
--    their bits in sources.
CREATE OR REPLACE TEMP TABLE key_blocks AS
SELECT g, k, id, id IN (SELECT id FROM fresh) AS new FROM (
  SELECT 0 AS g, customer_id AS k, id FROM records                                                      -- cif
  UNION ALL SELECT 1, phone || CHR(31) || prefecture, id FROM records                                   -- phone_prefecture
  UNION ALL SELECT 2, phone || CHR(31) || postal_code__first3, id FROM records                          -- phone_postal_area
  UNION ALL SELECT 3, phone || CHR(31) || any_name__initial, id FROM records                            -- phone_name_initial
  UNION ALL SELECT 4, person_name__kana_fold, id FROM records                                           -- person_name
  UNION ALL SELECT 5, company_name__nfkc_strip_legal_form_kana_fold, id FROM records                    -- company_name
  UNION ALL SELECT 6, SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id                                       -- company_name_deletions
    FROM (SELECT company_name__nfkc_strip_legal_form_kana_fold AS x, id FROM records WHERE company_name__nfkc_strip_legal_form_kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 7, w || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id                      -- person_name_deletions_postal_area
    FROM (SELECT person_name__kana_fold AS x, postal_code__first3 AS w, id FROM records WHERE person_name__kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 8, given_name__kana_fold || CHR(31) || postal_code, id FROM records                  -- given_name_postal
  UNION ALL SELECT 9, address__address || CHR(31) || phone, id FROM records                             -- address_phone
  UNION ALL SELECT 10, address_code || CHR(31) || phone, id FROM records                                -- address_code_phone
  UNION ALL SELECT 11, address__address || CHR(31) || any_name__initial, id FROM records                -- address_name_initial
  UNION ALL SELECT 12, address_code || CHR(31) || any_name__initial, id FROM records                    -- address_code_name_initial
  UNION ALL SELECT 13, given_name__kana_fold || CHR(31) || address_code, id FROM records                -- given_name_address_code
  UNION ALL SELECT 14, SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id                                      -- cif_deletions
    FROM (SELECT customer_id AS x, id FROM records WHERE customer_id IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 15, birth_date, id FROM records                                                      -- birth_date
  UNION ALL SELECT 16, given_name__kana_fold || CHR(31) || phone, id FROM records                       -- given_name_phone
  UNION ALL SELECT 17, w || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id                     -- birth_date_deletions_prefecture
    FROM (SELECT birth_date AS x, prefecture AS w, id FROM records WHERE birth_date IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 18, person_name__kana_fold_long_vowel, id FROM records                               -- name_reading
  UNION ALL SELECT 19, phone || CHR(31) || person_name__kana_fold_long_vowel_last3, id FROM records     -- phone_given_tail
  UNION ALL SELECT 20, postal_code || CHR(31) || person_name__kana_fold_long_vowel_last3, id FROM records  -- postal_given_tail
  UNION ALL SELECT 21, postal_code__first3 || CHR(31) || person_name__kana_fold_long_vowel_last3, id FROM records  -- postal_area_given_tail
) WHERE k IS NOT NULL AND g IN (SELECT g FROM generators WHERE used);

CREATE OR REPLACE TEMP TABLE key_sizes AS  -- each block the batch reaches, with its size among all the records
SELECT g, k, COUNT(*) AS n FROM key_blocks GROUP BY g, k HAVING LOGICAL_OR(new);

-- every pair of a block under @oversized records that touches the batch, each generator's bit set
CREATE OR REPLACE TEMP TABLE listed AS
SELECT LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r, BIT_OR(1 << a.g) AS bits
FROM key_blocks AS a JOIN key_blocks AS b ON a.g = b.g AND a.k = b.k AND a.id <> b.id AND (NOT b.new OR a.id < b.id)
JOIN key_sizes AS s ON s.g = a.g AND s.k = a.k
WHERE a.new AND s.n < @oversized
GROUP BY 1, 2;


-- 3. The model's bits, as a score reads them: the prior's, and each comparison's by level (gamma + 1: the missing
--    level, -1, weighs 0). A pair's weight: the prior and its levels' bits, added in the model's order.
CREATE OR REPLACE TEMP TABLE weights AS
WITH prior AS (  -- λ at the run's size: as fit found it, or for a lookup's (the run's records and the one asked), rescaled
  SELECT IF(f.records = n.n, f.prior_bits, LOG(lam / (1 - lam), 2)) AS bits
  FROM fit AS f, (SELECT COUNT(*) AS n FROM records) AS n,
       (SELECT LEAST(f.probability * (f.fit_rows - 1) / GREATEST(n.n - 1, 1), 1 - CAST(0.000000001 AS FLOAT64)) AS lam
        FROM fit AS f, (SELECT COUNT(*) AS n FROM records) AS n)
)
SELECT
  (SELECT bits FROM prior) AS prior,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'name' ORDER BY gamma)) AS name,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'company' ORDER BY gamma)) AS company,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'address' ORDER BY gamma)) AS address,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'phone' ORDER BY gamma)) AS phone,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'cif' ORDER BY gamma)) AS cif,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'birth' ORDER BY gamma)) AS birth,
  -- what a fuzzy comparison can still reach once its leading equalities fail: the best of its later levels
  (SELECT MAX(bits) FROM model WHERE comparison = 'name' AND gamma <= 3) AS name_after,
  (SELECT MAX(bits) FROM model WHERE comparison = 'company' AND gamma <= 1) AS company_after,
  (SELECT MAX(bits) FROM model WHERE comparison = 'address' AND gamma <= 2) AS address_after;

CREATE OR REPLACE TEMP FUNCTION weight_of(g_name INT64, g_company INT64, g_address INT64, g_phone INT64, g_cif INT64, g_birth INT64,
                                          w ANY TYPE) AS (  -- the levels' names apart from w's fields: DuckDB substitutes a parameter in a field's name too
  w.prior + w.name[OFFSET(g_name + 1)] + w.company[OFFSET(g_company + 1)] + w.address[OFFSET(g_address + 1)]
  + w.phone[OFFSET(g_phone + 1)] + w.cif[OFFSET(g_cif + 1)] + w.birth[OFFSET(g_birth + 1)]
);

-- An upper bound of a pair's weight, from its equalities alone: a fuzzy comparison at its level where a leading
-- equality settles it, else at the best of its later levels; the cheap ones at their own. No pair it rules out could
-- reach the floor, and the costly comparisons are made only on the pairs it keeps.
CREATE OR REPLACE TEMP FUNCTION bound_of(l ANY TYPE, r ANY TYPE, w ANY TYPE) AS (
  w.prior
  + CASE WHEN l.person_name IS NULL OR r.person_name IS NULL THEN CAST(0 AS FLOAT64)
         WHEN l.person_name = r.person_name THEN w.name[OFFSET(7)]
         WHEN l.person_name__kana_fold = r.person_name__kana_fold THEN w.name[OFFSET(6)]
         WHEN l.person_name__kana_fold_long_vowel = r.person_name__kana_fold_long_vowel THEN w.name[OFFSET(5)]
         ELSE w.name_after END
  + CASE WHEN l.company_name IS NULL OR r.company_name IS NULL THEN CAST(0 AS FLOAT64)
         WHEN l.company_name__nfkc_strip_legal_form_kana_fold = r.company_name__nfkc_strip_legal_form_kana_fold THEN w.company[OFFSET(3)]
         ELSE w.company_after END
  + CASE WHEN (l.address_code IS NULL OR r.address_code IS NULL) AND (l.address IS NULL OR r.address IS NULL)
              AND (l.postal_code IS NULL OR r.postal_code IS NULL) THEN CAST(0 AS FLOAT64)
         WHEN l.address_code = r.address_code OR l.address__address = r.address__address THEN w.address[OFFSET(4)]
         ELSE w.address_after END
  + w.phone[OFFSET(gamma_phone(l, r) + 1)] + w.cif[OFFSET(gamma_cif(l, r) + 1)] + w.birth[OFFSET(gamma_birth(l, r) + 1)]
);


-- 4. The gate: a block of @oversized records or more is joined only if a sample of its pairs (the first @oversized
--    of its batch records by hash against its first @oversized records), less those another block listed, scored as
--    the run scores, holds a pair at @search_floor bits or more. A big block holds few true matches, and a
--    placeholder's (a dummy phone) none.
CREATE OR REPLACE TEMP TABLE gate_pairs AS
WITH ranked AS (
  SELECT b.g, b.k, b.id, b.new,
         ROW_NUMBER() OVER (PARTITION BY b.g, b.k ORDER BY er_hash(b.id)) AS rank,
         IF(b.new, ROW_NUMBER() OVER (PARTITION BY b.g, b.k, b.new ORDER BY er_hash(b.id)), NULL) AS new_rank
  FROM key_blocks AS b JOIN key_sizes AS s ON s.g = b.g AND s.k = b.k WHERE s.n >= @oversized
)
SELECT DISTINCT a.g, a.k, LEAST(a.id, c.id) AS l, GREATEST(a.id, c.id) AS r
FROM ranked AS a JOIN ranked AS c ON a.g = c.g AND a.k = c.k AND a.id <> c.id
WHERE a.new_rank <= @oversized AND c.rank <= @oversized
  AND NOT EXISTS (SELECT 1 FROM listed AS x WHERE x.l = LEAST(a.id, c.id) AND x.r = GREATEST(a.id, c.id));

CREATE OR REPLACE TABLE gated AS
WITH scored_sample AS (
  SELECT p.l, p.r, weight_of(gamma_name(x, y), gamma_company(x, y), gamma_address(x, y), gamma_phone(x, y), gamma_cif(x, y), gamma_birth(x, y), w) AS w
  FROM (SELECT DISTINCT l, r FROM gate_pairs) AS p JOIN compared AS x ON x.id = p.l JOIN compared AS y ON y.id = p.r CROSS JOIN weights AS w
  WHERE bound_of(x, y, w) >= @search_floor - CAST(0.000000001 AS FLOAT64)
),
stats AS (
  SELECT p.g, p.k, COUNT(*) AS sampled, MAX(s.w) AS best, COUNT(CASE WHEN s.w >= @search_floor THEN 1 END) AS hits
  FROM gate_pairs AS p LEFT JOIN scored_sample AS s USING (l, r) GROUP BY p.g, p.k
)
SELECT z.g, z.k AS value, z.n AS records, DIV(z.n * (z.n - 1), 2) AS pairs, COALESCE(s.sampled, 0) AS sampled, s.best, COALESCE(s.hits, 0) AS hits,
       CASE WHEN COALESCE(s.hits, 0) > 0 THEN 'kept' WHEN COALESCE(s.sampled, 0) = 0 THEN 'skipped: other keys list its sampled pairs'
            ELSE 'skipped: no sampled pair reaches the floor' END AS decision
FROM key_sizes AS z LEFT JOIN stats AS s ON s.g = z.g AND s.k = z.k
WHERE z.n >= @oversized;


-- 5. The candidates: the pairs listed, and every pair of a block kept that touches the batch, each with the keys that
--    listed it (sources).
CREATE OR REPLACE TABLE cands AS
WITH every AS (
  SELECT l, r, bits FROM listed
  UNION ALL
  SELECT LEAST(a.id, b.id), GREATEST(a.id, b.id), 1 << a.g
  FROM key_blocks AS a JOIN key_blocks AS b ON a.g = b.g AND a.k = b.k AND a.id <> b.id AND (NOT b.new OR a.id < b.id)
  JOIN gated AS z ON z.g = a.g AND z.value = a.k
  WHERE a.new AND z.decision = 'kept'
),
pairs AS (SELECT l, r, BIT_OR(bits) AS bits FROM every GROUP BY l, r),
named AS (  -- each set of bits as the generators' names, in their order
  SELECT bits, ARRAY_TO_STRING(ARRAY(SELECT name FROM generators WHERE (bits >> g) & 1 = 1 ORDER BY g), '+') AS sources
  FROM (SELECT DISTINCT bits FROM pairs)
)
SELECT pairs.l, pairs.r, named.sources FROM pairs JOIN named USING (bits);


-- 6. The scores: every candidate and rule pair of the batch the bound keeps, its levels and its weight; kept from
--    @keep_from bits up, and every rule pair. named: a name was compared (the person's or the company's). Added to
--    the run's: a pair touching a batch is scored once, as that batch's.
CREATE OR REPLACE TEMP TABLE batch_scored AS
WITH pairs AS (
  SELECT l, r, c.sources, p.rule FROM cands AS c FULL JOIN batch_rule_pairs AS p USING (l, r)
),
levelled AS (
  SELECT p.l, p.r, p.sources, p.rule, gamma_name(x, y) AS gamma_name, gamma_company(x, y) AS gamma_company,
         gamma_address(x, y) AS gamma_address, gamma_phone(x, y) AS gamma_phone, gamma_cif(x, y) AS gamma_cif, gamma_birth(x, y) AS gamma_birth
  FROM pairs AS p JOIN compared AS x ON x.id = p.l JOIN compared AS y ON y.id = p.r CROSS JOIN weights AS w
  WHERE p.rule IS NOT NULL OR bound_of(x, y, w) >= @keep_from - CAST(0.000000001 AS FLOAT64)
),
weighed AS (
  SELECT x.*, weight_of(gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth, w) AS match_weight
  FROM levelled AS x CROSS JOIN weights AS w
)
SELECT
  l AS id_l, r AS id_r, match_weight,
  CASE WHEN match_weight >= 0 THEN CAST(1 AS FLOAT64) / (CAST(1 AS FLOAT64) + POWER(CAST(2 AS FLOAT64), -match_weight))
       ELSE POWER(CAST(2 AS FLOAT64), match_weight) / (CAST(1 AS FLOAT64) + POWER(CAST(2 AS FLOAT64), match_weight)) END AS match_probability,
  sources, rule, (gamma_name >= 0 OR gamma_company >= 0) AS named,
  gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth
FROM weighed
WHERE match_weight >= @keep_from OR rule IS NOT NULL;

CREATE TABLE IF NOT EXISTS scored AS SELECT * FROM batch_scored WHERE FALSE;

INSERT INTO scored SELECT * FROM batch_scored;
