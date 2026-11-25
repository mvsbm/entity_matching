-- Stage 3, score. This stage finds the pairs worth scoring and scores them. It pairs the records of the run's latest
-- batch, and the run's records that records.sql made again, with all the run's records. In a build, every record is
-- the batch's.
-- The pairs come from the rules and from the keys. Every pair that a key lists is a candidate. If a key's block holds
-- @oversized records or more, the stage first scores a sample of the block's pairs, and lists the block's pairs only if
-- the sample holds a pair at @search_floor points or more. Each pair gets its level of each comparison (functions.sql)
-- and its points from the model. The points are the prior plus each level's bits, added in the model's order, so
-- that the sum is Splink's to the last bit. The stage keeps every pair with @keep_from points or more, and every
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
--   @generators, @rules   the names of the generators and the rules this run uses (config.toml [score])
--   @keep_from            a scored pair with this many points or more is kept
--   @search_floor         a sampled pair with this many points or more keeps its block
--   @oversized            a block of this many records or more is checked first on a sample of as many of its records
--   @lookup               true if the batch is a record asked about. Each of its keys is then kept, even in a block
--                         of one, so that lookup.sql can report it.
--   @outside              how many of the run's records the records table doesn't hold. A lookup's records table
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
-- when: NOT @lookup
CREATE OR REPLACE TEMP TABLE changed AS
SELECT id, FALSE AS redone FROM records WHERE batch = (SELECT batch FROM this_batch)
UNION ALL SELECT id, TRUE FROM redone;

-- A lookup's records table holds only the records the lookup read, and its index starts empty, so it makes the keys
-- of every record it holds.
-- when: @lookup
CREATE OR REPLACE TEMP TABLE changed AS SELECT id, FALSE AS redone FROM records;

-- batch_records holds the records this job pairs with all the run's records, which the statements below call the
-- batch's (in_batch). They are the batch's own records and the records made again, whose pairs are scored again
-- with their values as they are now: in an update or a build, changed whole.
-- when: NOT @lookup
CREATE OR REPLACE TEMP TABLE batch_records AS SELECT id FROM changed;

-- A lookup pairs the record it looks up alone, the one record of its batch.
-- when: @lookup
CREATE OR REPLACE TEMP TABLE batch_records AS SELECT id FROM records WHERE batch = (SELECT batch FROM this_batch);

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
SELECT g, name, name IN UNNEST(@generators) AS used FROM UNNEST([
  'customer_id', 'phone_prefecture', 'phone_postal_area', 'phone_name_initial', 'person_name', 'company_name', 'company_name_deletions',
  'person_name_deletions_postal_area', 'given_name_postal', 'address_phone', 'address_code_phone', 'address_name_initial',
  'address_code_name_initial', 'given_name_address_code', 'customer_id_deletions', 'birth_date', 'given_name_phone',
  'birth_date_deletions_prefecture', 'name_reading', 'phone_name_tail', 'postal_name_tail', 'postal_area_name_tail'
]) AS name WITH OFFSET AS g;

CREATE OR REPLACE TEMP TABLE rules AS
SELECT i, rule, rule IN UNNEST(@rules) AS used FROM UNNEST([
  'X1_CIF_FULL_NAME', 'X2_CIF_COMPANY_NAME', 'X3_CIF_PHONE', 'X4_FULL_NAME_ADDRCD_PHONE',
  'X5_COMPANY_NAME_ADDRCD_PHONE', 'F1_NAME~_ADDRCD_PHONE', 'F2_NAME~_ADDRESS~_PHONE', 'F3_NAME~_CIF',
  'F4_NAME_ADDRCD_PHONE~', 'F5_COMPANY~_PHONE_POSTAL', 'F6_COMPANY~_ADDRCD_PHONE', 'X6_GIVEN_ADDRCD_PHONE'
]) AS rule WITH OFFSET AS i;

SELECT IF(COUNT(*) > 0, ERROR(CONCAT('config.toml [score]: no generator or rule is named ', STRING_AGG(x, ', '),
                                     '; name those score.sql lists')), 0)
FROM (SELECT x FROM UNNEST(@generators) AS x WHERE x NOT IN (SELECT name FROM generators)
      UNION ALL SELECT x FROM UNNEST(@rules) AS x WHERE x NOT IN (SELECT rule FROM rules));


-- 1. The rules. Each rule joins the records on its key, then applies its fuzzy tests to the pairs that join. If a key
--    value is held by @oversized records or more, it can't be one entity's, so the rule leaves it out. The model
--    can still match those records. The batch's records are paired with all the run's records, each pair once, with
--    the lower ID first.
--    A key of several fields joins them with CHR(31), the unit separator. read_value removes every control character
--    (functions.sql), so no field holds it, and two different lists of values never make the same key.
CREATE OR REPLACE TEMP TABLE made_rule_keys AS  -- the rule keys of the records in changed
WITH changed_records AS (SELECT * FROM records WHERE id IN (SELECT id FROM changed))
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
CREATE TABLE IF NOT EXISTS rule_keys CLUSTER BY key AS SELECT i, key, id FROM made_rule_keys WHERE FALSE;

-- when: EXISTS (SELECT 1 FROM changed WHERE redone)
DELETE FROM rule_keys WHERE id IN (SELECT id FROM changed WHERE redone);

INSERT INTO rule_keys SELECT i, key, id FROM made_rule_keys;

-- rule_blocks holds every record of each rule key the batch holds. in_batch is TRUE for the batch's records, and n is
-- the number of records that hold the key.
-- In the run's first batch (batch 0) every record is the batch's, so every rule key is. A lookup takes the second
-- form whatever its batch, so that only the record it looks up is in_batch.
-- when: NOT @lookup AND EXISTS (SELECT 1 FROM this_batch WHERE batch = 0)
CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, key, id, TRUE AS in_batch, COUNT(*) OVER (PARTITION BY i, key) AS n FROM rule_keys;

-- when: @lookup OR EXISTS (SELECT 1 FROM this_batch WHERE batch > 0)
CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, key, id, id IN (SELECT id FROM batch_records) AS in_batch, COUNT(*) OVER (PARTITION BY i, key) AS n
FROM rule_keys
JOIN (SELECT DISTINCT i, key FROM made_rule_keys WHERE id IN (SELECT id FROM batch_records)) USING (i, key);


-- 2. The keys. Each generator makes a key for each record from one or more of its fields, joined by CHR(31) as a
--    rule's are. The records with the same key form a block. A deletion generator makes several keys for a record.
--    They are its value with each character deleted in turn, and the value whole, each joined to the generator's other
--    fields. Deleting any character of a run of equal characters gives the same value, so a run gives its key once.
CREATE OR REPLACE TEMP TABLE made_keys AS  -- the keys of the records in changed
WITH changed_records AS (SELECT * FROM records WHERE id IN (SELECT id FROM changed))
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
CREATE TABLE IF NOT EXISTS every_key CLUSTER BY key AS SELECT g, key, id FROM made_keys WHERE FALSE;

-- when: EXISTS (SELECT 1 FROM changed WHERE redone)
DELETE FROM every_key WHERE id IN (SELECT id FROM changed WHERE redone);

INSERT INTO every_key SELECT g, key, id FROM made_keys;

-- block_size gives a block's whole size if records holds only part of it. A lookup makes the table first, with the
-- blocks it read in part. In any other job, this statement makes it empty.
CREATE TEMP TABLE IF NOT EXISTS block_size (g INT64, key STRING, n INT64);

-- key_blocks gives each key its block's size n among all the run's records. It keeps only the blocks that touch the
-- batch and hold two records or more, since only those can make a pair. A lookup also keeps its record's blocks of
-- one, so that lookup.sql can report every key.
-- In the run's first batch every record is the batch's, so every block is.
-- when: NOT @lookup AND EXISTS (SELECT 1 FROM this_batch WHERE batch = 0)
CREATE OR REPLACE TEMP TABLE key_blocks AS
SELECT g, key, id, TRUE AS in_batch, n FROM (SELECT g, key, id, COUNT(*) OVER (PARTITION BY g, key) AS n FROM every_key)
WHERE n > 1;

-- when: @lookup OR EXISTS (SELECT 1 FROM this_batch WHERE batch > 0)
CREATE OR REPLACE TEMP TABLE key_blocks AS
-- touched holds every record of each block that a key of the batch names. held is the number of records the run
-- holds in the block.
WITH touched AS (
  SELECT e.g, e.key, e.id, COUNT(*) OVER (PARTITION BY e.g, e.key) AS held
  FROM every_key AS e
  JOIN (SELECT DISTINCT g, key FROM made_keys WHERE id IN (SELECT id FROM batch_records)) USING (g, key)
)
SELECT t.g, t.key, t.id, t.id IN (SELECT id FROM batch_records) AS in_batch, COALESCE(u.n, t.held) AS n
FROM touched AS t LEFT JOIN block_size AS u USING (g, key)
WHERE (t.held > 1 OR @lookup)  -- records holds two of the block's records or more, or the job is a lookup
  -- and the block at its whole size (block_size) holds two records or more, or the record is the batch's. So a lookup
  -- keeps a block of one only for the record it looks up.
  AND (COALESCE(u.n, t.held) > 1 OR t.id IN (SELECT id FROM batch_records));

-- listed holds every pair that touches the batch and shares a block of fewer than @oversized records. mask has one
-- bit set for each generator whose keys list the pair.
CREATE OR REPLACE TEMP TABLE listed AS
SELECT LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r, BIT_OR(1 << a.g) AS mask
FROM key_blocks AS a
JOIN key_blocks AS b ON a.g = b.g AND a.key = b.key AND a.id <> b.id AND (NOT b.in_batch OR a.id < b.id)
WHERE a.in_batch AND a.n < @oversized
GROUP BY l, r;


-- 3. The model's bits, as a score reads them. level_bits holds the prior and, for each comparison, an array of
--    its levels' bits. Level γ's bits are at OFFSET(γ + 1), so the missing level, -1, is at OFFSET(0) and weighs 0.
--    points_of gives a pair's points, the prior plus its levels' bits, added in the model's order. bound_of gives an
--    upper bound of a pair's points from cheap tests alone.
--    Each array lists the model's levels in order of gamma, so OFFSET(γ + 1) is level γ only if model holds every
--    gamma of the comparison from 0 up, without a gap. It does: fit.sql writes a row for each of functions.sql's
--    levels.
-- lambda_cap is the most the rescaled λ can be, a hair under 1, so that its log-odds stay finite (em.py's LAMBDA_CAP).
CREATE OR REPLACE TEMP FUNCTION lambda_cap() AS (1 - CAST(0.000000001 AS FLOAT64));

CREATE OR REPLACE TEMP TABLE level_bits AS
-- run_records counts the run's records. @outside counts those a lookup didn't read.
WITH size AS (SELECT COUNT(*) + @outside AS run_records FROM records),
rate AS (  -- λ is a per-pair rate, so it is rescaled to the run's size, as em.fitted rescales it
  SELECT LEAST(f.probability * (f.fit_records - 1) / GREATEST(size.run_records - 1, 1), lambda_cap()) AS rate
  FROM fit AS f, size
),
prior AS (  -- the prior is fit's own if the run has as many records as when fit ran, else the rescaled λ's bits
  SELECT IF(f.records = size.run_records, f.prior_bits, LOG(rate.rate / (1 - rate.rate), 2)) AS prior_bits
  FROM fit AS f, size, rate
)
SELECT
  (SELECT prior_bits FROM prior) AS prior_bits,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'name' ORDER BY gamma)) AS name,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'company' ORDER BY gamma)) AS company,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'address' ORDER BY gamma)) AS address,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'phone' ORDER BY gamma)) AS phone,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'cif' ORDER BY gamma)) AS cif,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'birth' ORDER BY gamma)) AS birth,
  -- Each *_after is the most bits a fuzzy comparison can still earn once its leading equalities fail.
  (SELECT MAX(bits) FROM model WHERE comparison = 'name' AND gamma <= 3) AS name_after,
  (SELECT MAX(bits) FROM model WHERE comparison = 'company' AND gamma <= 1) AS company_after;

-- bits_at returns level gamma's bits from one of level_bits' arrays, as functions.sql numbers the levels. A missing
-- side (level -1) is at OFFSET(0) and weighs 0. gamma is ANY TYPE, as is could_reach's bound, because DuckDB binds a
-- typed parameter's argument twice, and these arguments are whole comparisons.
CREATE OR REPLACE TEMP FUNCTION bits_at(levels ANY TYPE, gamma ANY TYPE) AS (levels[OFFSET(gamma + 1)]);

-- points_of's level parameters are gamma_name, gamma_company and so on, not the names of w's fields (name,
-- company…), because DuckDB would substitute a parameter into a field of the same name too.
CREATE OR REPLACE TEMP FUNCTION points_of(gamma_name INT64, gamma_company INT64, gamma_address INT64, gamma_phone INT64,
                                          gamma_cif INT64, gamma_birth INT64, w ANY TYPE) AS (
  w.prior_bits + bits_at(w.name, gamma_name) + bits_at(w.company, gamma_company) + bits_at(w.address, gamma_address)
  + bits_at(w.phone, gamma_phone) + bits_at(w.cif, gamma_cif) + bits_at(w.birth, gamma_birth)
);

-- probability_of turns a pair's points (its log2 odds) into its match probability, 1 / (1 + 2^-points). It takes two
-- forms so that POWER never gets a large argument, which BigQuery refuses as an overflow.
CREATE OR REPLACE TEMP FUNCTION probability_of(points FLOAT64) AS (
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
CREATE OR REPLACE TEMP FUNCTION name_bound(x ANY TYPE, y ANY TYPE, w ANY TYPE) AS (
  CASE WHEN x.person_name IS NULL OR y.person_name IS NULL THEN bits_at(w.name, -1)
       WHEN x.person_name = y.person_name THEN bits_at(w.name, 6)                                     -- exact
       WHEN x.person_name__kana_fold = y.person_name__kana_fold THEN bits_at(w.name, 5)               -- fold exact
       WHEN x.person_name__kana_fold_long_vowel = y.person_name__kana_fold_long_vowel
         THEN bits_at(w.name, 4)                                                                      -- same reading
       WHEN x.person_name__kana_fold IS NULL OR y.person_name__kana_fold IS NULL THEN w.name_after
       ELSE GREATEST(IF(x.given_name__kana_fold = y.given_name__kana_fold, bits_at(w.name, 2), bits_at(w.name, 0)),
                     CASE WHEN name_jw_most(x, y) < cut_from(CAST(0.75 AS FLOAT64))
                            THEN bits_at(w.name, 0)  -- most pairs stop here, so name_jw_most runs once for them
                          WHEN name_jw_most(x, y) < cut_from(CAST(0.95 AS FLOAT64))
                            THEN GREATEST(bits_at(w.name, 0), bits_at(w.name, 1))  -- else, fold JW low
                          ELSE GREATEST(bits_at(w.name, 0), bits_at(w.name, 1), bits_at(w.name, 3))  -- and JW high
                     END)
  END
);

-- company_bound takes the company's JW low level only if jaro_winkler_most allows it.
CREATE OR REPLACE TEMP FUNCTION company_bound(x ANY TYPE, y ANY TYPE, w ANY TYPE) AS (
  CASE WHEN x.company_name IS NULL OR y.company_name IS NULL THEN bits_at(w.company, -1)
       WHEN x.company_name__nfkc_strip_legal_form_kana_fold = y.company_name__nfkc_strip_legal_form_kana_fold
         THEN bits_at(w.company, 2)                                                                   -- exact
       WHEN x.company_name__nfkc_strip_legal_form_kana_fold IS NULL
            OR y.company_name__nfkc_strip_legal_form_kana_fold IS NULL
         THEN w.company_after
       WHEN jaro_winkler_most(x.company_name__nfkc_strip_legal_form_kana_fold,
                              y.company_name__nfkc_strip_legal_form_kana_fold)
            >= cut_from(CAST(0.8 AS FLOAT64)) THEN w.company_after
       ELSE bits_at(w.company, 0)                                                                     -- else
  END
);

-- address_bound takes "address close" only if the two addresses' lengths differ by two characters or less, and "same
-- postal" only if the postal codes are equal.
CREATE OR REPLACE TEMP FUNCTION address_bound(x ANY TYPE, y ANY TYPE, w ANY TYPE) AS (
  CASE WHEN (x.address_code IS NULL OR y.address_code IS NULL) AND (x.address IS NULL OR y.address IS NULL)
            AND (x.postal_code IS NULL OR y.postal_code IS NULL) THEN bits_at(w.address, -1)
       WHEN x.address_code = y.address_code OR x.address__address = y.address__address
         THEN bits_at(w.address, 3)                                                                   -- same address
       ELSE GREATEST(bits_at(w.address, 0),                                                           -- else
                     IF(x.address__address IS NOT NULL AND y.address__address IS NOT NULL
                        AND ABS(LENGTH(x.address__address) - LENGTH(y.address__address)) <= 2,
                        bits_at(w.address, 2), bits_at(w.address, 0)),                                -- address close
                     IF(x.postal_code = y.postal_code, bits_at(w.address, 1), bits_at(w.address, 0)))  -- same postal
  END
);

-- bound_of adds the prior and each comparison's bound in the model's order, as points_of adds a pair's points. The
-- cheap comparisons (phone, cif and birth) take their own level.
CREATE OR REPLACE TEMP FUNCTION bound_of(x ANY TYPE, y ANY TYPE, w ANY TYPE) AS (
  w.prior_bits + name_bound(x, y, w) + company_bound(x, y, w) + address_bound(x, y, w)
  + bits_at(w.phone, gamma_phone(x, y)) + bits_at(w.cif, gamma_cif(x, y)) + bits_at(w.birth, gamma_birth(x, y))
);

-- could_reach is TRUE if a pair whose points are at most bound could reach floor. bound_of adds its bits in
-- points_of's order, each at least the pair's own level's, so rounding never leaves a pair's bound under its points.
-- rounding_margin, under the floor, keeps the test safe should the two orders ever part.
CREATE OR REPLACE TEMP FUNCTION rounding_margin() AS (CAST(0.000000001 AS FLOAT64));

CREATE OR REPLACE TEMP FUNCTION could_reach(bound ANY TYPE, floor ANY TYPE) AS (
  bound >= floor - rounding_margin()
);


-- 4. The gate. A block of @oversized records or more is listed only if a sample of its pairs holds a pair with
--    @search_floor points or more. The sample pairs the block's first @oversized batch records, by hash, with its
--    first @oversized records. It leaves out the pairs another block already listed, and it is scored as the run
--    scores. So a block of 200 records whose batch holds 10 gives at most 10 × 64 sampled pairs, where its pairs
--    touching the batch number about 10 × 200.
--    A big block holds few true matches. A placeholder makes no key, as records.sql blanks it first, so a big block
--    is a crowded value that records.sql's test let through: a dummy phone held by too few customers, say.
CREATE OR REPLACE TEMP TABLE gate_pairs AS
WITH ranked AS (  -- nth_in_block is a record's place in its block by hash, and nth_in_batch its place among the batch's
  SELECT g, key, id, in_batch,
         ROW_NUMBER() OVER (PARTITION BY g, key ORDER BY er_hash(id)) AS nth_in_block,
         IF(in_batch, ROW_NUMBER() OVER (PARTITION BY g, key, in_batch ORDER BY er_hash(id)), NULL) AS nth_in_batch
  FROM key_blocks WHERE n >= @oversized
)
SELECT DISTINCT a.g, a.key, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
FROM ranked AS a JOIN ranked AS b ON a.g = b.g AND a.key = b.key AND a.id <> b.id
WHERE a.nth_in_batch <= @oversized AND b.nth_in_block <= @oversized
  AND NOT EXISTS (SELECT 1 FROM listed AS seen WHERE seen.l = LEAST(a.id, b.id) AND seen.r = GREATEST(a.id, b.id));

CREATE OR REPLACE TEMP TABLE gated AS
-- gate_scored holds each sampled pair that the bound keeps, with its points. name_score is name_level's argument.
-- BigQuery has been seen to compute a SQL function's arguments once, before its body, so name_score runs once a pair
-- here; this is observed behaviour, not documented.
WITH gate_scored AS (
  SELECT p.l, p.r,
         points_of(name_level(x, y, name_score(x, y)), gamma_company(x, y), gamma_address(x, y), gamma_phone(x, y),
                   gamma_cif(x, y), gamma_birth(x, y), w) AS points
  FROM (SELECT DISTINCT l, r FROM gate_pairs) AS p JOIN compared AS x ON x.id = p.l JOIN compared AS y ON y.id = p.r
  CROSS JOIN level_bits AS w
  WHERE could_reach(bound_of(x, y, w), @search_floor)
),
-- sampled counts every sampled pair of a block, those the bound dropped among them. best and hits read only the pairs
-- scored.
stats AS (
  SELECT p.g, p.key, COUNT(*) AS sampled, MAX(s.points) AS best,
         COUNT(CASE WHEN s.points >= @search_floor THEN 1 END) AS hits
  FROM gate_pairs AS p LEFT JOIN gate_scored AS s USING (l, r) GROUP BY p.g, p.key
)
SELECT z.g, z.key, z.n AS records, pairs_of(z.n) AS pairs,
       COALESCE(s.sampled, 0) AS sampled, s.best, COALESCE(s.hits, 0) AS hits,
       CASE WHEN COALESCE(s.hits, 0) > 0 THEN 'listed' WHEN COALESCE(s.sampled, 0) = 0 THEN 'skipped: other keys list its sampled pairs'
            ELSE 'skipped: no sampled pair reaches the floor' END AS verdict
FROM (SELECT DISTINCT g, key, n FROM key_blocks WHERE n >= @oversized) AS z
LEFT JOIN stats AS s ON s.g = z.g AND s.key = z.key;


-- 5. The candidates. They are the pairs in listed, and every pair of a listed oversized block that touches the batch.
--    Each comes with the generators whose keys listed it.
CREATE OR REPLACE TABLE cands AS
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
--    with @keep_from points or more are kept, and so is every rule pair. named is true if a name was compared, the
--    person's or the company's. The batch's pairs are added to the run's scored. Each pair is scored once, in the
--    batch that brings its later record, and again in each job that makes one of its records again.
CREATE OR REPLACE TEMP TABLE batch_pairs AS  -- each of the batch's candidates and rule pairs appears once
WITH rule_hits AS (
  SELECT a.i AS rule_rank, rules.rule, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
  FROM rule_blocks AS a
  JOIN rule_blocks AS b ON a.i = b.i AND a.key = b.key AND a.id <> b.id AND (NOT b.in_batch OR a.id < b.id)
  -- A function given a row reads all of its columns, so x and y are rows of compared, which holds only the columns
  -- the comparisons read.
  JOIN compared AS x ON x.id = a.id JOIN compared AS y ON y.id = b.id
  JOIN rules ON rules.i = a.i
  WHERE a.in_batch AND a.n < @oversized
    AND CASE rules.rule  -- These are the fuzzy rules' tests. The exact rules (X1-X6) test their keys alone.
          WHEN 'F1_NAME~_ADDRCD_PHONE' THEN near_name(x, y)
          WHEN 'F2_NAME~_ADDRESS~_PHONE' THEN near_name(x, y) AND near_address(x, y)
          WHEN 'F3_NAME~_CIF' THEN near_name(x, y)
          WHEN 'F4_NAME_ADDRCD_PHONE~' THEN near_phone(x, y)
          WHEN 'F5_COMPANY~_PHONE_POSTAL' THEN near_company(x, y)
          WHEN 'F6_COMPANY~_ADDRCD_PHONE' THEN near_company(x, y)
          ELSE TRUE END
),
rule_pairs AS (  -- each pair a rule finds, with the first rule in order that finds it (the least rule_rank)
  SELECT l, r, MIN_BY(rule, rule_rank) AS rule FROM rule_hits GROUP BY l, r
)
SELECT l, r, c.generators, p.rule FROM cands AS c FULL JOIN rule_pairs AS p USING (l, r);

CREATE OR REPLACE TEMP TABLE batch_scored AS
WITH in_bound AS (  -- in_bound computes the names' Jaro–Winkler (s_name) once for each pair the bound keeps
  SELECT p.l, p.r, p.generators, p.rule, x, y, name_score(x, y) AS s_name
  FROM batch_pairs AS p JOIN compared AS x ON x.id = p.l JOIN compared AS y ON y.id = p.r CROSS JOIN level_bits AS w
  WHERE p.rule IS NOT NULL OR could_reach(bound_of(x, y, w), @keep_from)
),
levelled AS (
  SELECT l, r, generators, rule, name_level(x, y, s_name) AS gamma_name, gamma_company(x, y) AS gamma_company,
         gamma_address(x, y) AS gamma_address, gamma_phone(x, y) AS gamma_phone, gamma_cif(x, y) AS gamma_cif,
         gamma_birth(x, y) AS gamma_birth
  FROM in_bound
),
weighed AS (
  SELECT lv.*,
         points_of(gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth, w) AS points
  FROM levelled AS lv CROSS JOIN level_bits AS w
)
SELECT
  l AS id_l, r AS id_r, points,
  probability_of(points) AS match_probability,
  generators, rule, (gamma_name >= 0 OR gamma_company >= 0) AS named,
  gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth
FROM weighed
WHERE points >= @keep_from OR rule IS NOT NULL;

CREATE TABLE IF NOT EXISTS scored AS SELECT * FROM batch_scored WHERE FALSE;

-- The pairs a record made again had leave scored, as batch_scored holds them scored again. A pair that its keys or
-- rules no longer find, or that now scores under @keep_from, is not kept. On BigQuery this DELETE bills scored whole,
-- so only an update that finds a new placeholder runs it.
-- when: EXISTS (SELECT 1 FROM changed WHERE redone)
DELETE FROM scored
WHERE id_l IN (SELECT id FROM changed WHERE redone) OR id_r IN (SELECT id FROM changed WHERE redone);

INSERT INTO scored SELECT * FROM batch_scored;
