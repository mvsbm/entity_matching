-- Stage 3, score. This stage finds the pairs worth scoring and scores them. It pairs the records of the run's latest
-- batch with all the run's records. In a build, every record is new.
-- The pairs come from the rules and from the keys. Every pair that a key lists is a candidate. If a key's block holds
-- @oversized records or more, the stage first scores a sample of the block's pairs, and joins the block only if the
-- sample holds a pair at @search_floor points or more. Each pair gets its level of each comparison (functions.sql)
-- and its points from the model. The points are the prior plus each level's bits, added in the model's order, so
-- that the sum is Splink's to the last bit. The stage keeps every pair with @keep_from points or more, and every
-- rule pair. These are the pairs a match run can offer people. Nothing merges here.
-- A pair's two records are x and y. l and r are the pair's IDs, and they can't name its records too, because a
-- WHERE clause reads a name l differently on the two engines: DuckDB as the SELECT's column l, BigQuery as the table l.
-- O(Δ·b) for the batch's pairs, plus O(Δ·L) to make the changed records' keys (Δ counts the records made again
-- too), and a scan of the index for the blocks the batch's keys name.
--
-- Reads: records, this_batch and redone (records.sql), compared (fit.sql), model (each level's bits) and fit (the
-- prior's bits at the file's size); block_size, a lookup's blocks read in part (nayose.lookup).
-- Values:
--   @keys, @rules   the names of the generators and the rules this run uses (config.toml [score])
--   @keep_from      a scored pair with this many points or more is kept
--   @search_floor   a sampled pair with this many points or more keeps its block
--   @oversized      a block of this many records or more is checked first on a sample of as many of its records
--   @lookup         true if the batch is a record asked about. Each of its keys is then kept, even in a block of
--                   one, so that lookup.sql can report it.
--   @outside        how many of the run's records the records table doesn't hold. A lookup's records table holds
--                   only its record's blocks (nayose.lookup). In any other job, it is 0.
-- Writes:
--   rule_keys and every_key   each record's keys, which are the index a lookup reads by key
--   cands                     the pairs the batch's keys list, each with the keys that listed it (sources)
--   scored                    every pair kept
-- scored holds every batch's pairs. Each batch adds the pairs that touch its records, a rule's pair with its rule.

-- 0. The batch's records, the generators and the rules.
CREATE OR REPLACE TEMP TABLE fresh AS SELECT id FROM records WHERE batch = (SELECT batch FROM this_batch);

-- changed holds the records whose keys this job makes: the batch's, and the run's records that records.sql made again
-- (redone), marked again. Every other record's keys are as the last job left them, since a record's keys change only
-- when the record does.
-- when: NOT @lookup
CREATE OR REPLACE TEMP TABLE changed AS SELECT id, FALSE AS again FROM fresh UNION ALL SELECT id, TRUE FROM redone;

-- A lookup's records table holds only the records the lookup read, and its index starts empty, so it makes the keys
-- of every record it holds.
-- when: @lookup
CREATE OR REPLACE TEMP TABLE changed AS SELECT id, FALSE AS again FROM records;

-- The generators and the rules are listed by name, in order. The statements below name each one, and read its
-- position from these lists. A generator's position (g) is its bit in the pairs' bits, which cands turns into
-- sources. A rule's position (i) is its rank: if several rules find a pair, the first one names it. config.toml says
-- which ones this run uses, and a name it gives that isn't listed here is refused.
CREATE OR REPLACE TEMP TABLE generators AS
SELECT g, name, name IN UNNEST(@keys) AS used FROM UNNEST([
  'cif', 'phone_prefecture', 'phone_postal_area', 'phone_name_initial', 'person_name', 'company_name', 'company_name_deletions',
  'person_name_deletions_postal_area', 'given_name_postal', 'address_phone', 'address_code_phone', 'address_name_initial',
  'address_code_name_initial', 'given_name_address_code', 'cif_deletions', 'birth_date', 'given_name_phone',
  'birth_date_deletions_prefecture', 'name_reading', 'phone_given_tail', 'postal_given_tail', 'postal_area_given_tail'
]) AS name WITH OFFSET AS g;

CREATE OR REPLACE TEMP TABLE rules AS
SELECT i, rule, rule IN UNNEST(@rules) AS used FROM UNNEST([
  'X1_CIF_PERSON_NAME', 'X2_CIF_COMPANY_NAME', 'X3_CIF_PHONE', 'X4_PERSON_NAME_ADDRCD_PHONE',
  'X5_COMPANY_NAME_ADDRCD_PHONE', 'F1_NAME~_ADDRCD_PHONE', 'F2_NAME~_ADDRESS~_PHONE', 'F3_NAME~_CIF',
  'F4_NAME_ADDRCD_PHONE~', 'F5_COMPANY~_PHONE_POSTAL', 'F6_COMPANY~_ADDRCD_PHONE', 'F7_GIVEN_ADDRCD_PHONE'
]) AS rule WITH OFFSET AS i;

SELECT IF(COUNT(*) > 0, ERROR(CONCAT('config.toml [score]: no generator or rule is named ', STRING_AGG(x, ', '),
                                     '; name those score.sql lists')), 0)
FROM (SELECT x FROM UNNEST(@keys) AS x WHERE x NOT IN (SELECT name FROM generators)
      UNION ALL SELECT x FROM UNNEST(@rules) AS x WHERE x NOT IN (SELECT rule FROM rules));


-- 1. The rules. Each rule joins the records on its key, then applies its fuzzy tests to the pairs that join. If a key
--    value is held by @oversized records or more, it can't be one customer's, so the rule leaves it out. The model
--    can still match those records. The batch's records are paired with all the run's records, each pair once, with
--    the lower ID first.
CREATE OR REPLACE TEMP TABLE made_rule_keys AS  -- the rule keys of the records in changed
WITH remade AS (SELECT * FROM records WHERE id IN (SELECT id FROM changed))
SELECT rules.i, k, id FROM (
  SELECT 'X1_CIF_PERSON_NAME' AS rule, customer_id || CHR(31) || full_name AS k, id FROM remade
  UNION ALL SELECT 'X2_CIF_COMPANY_NAME', customer_id || CHR(31) || company_name, id FROM remade
  UNION ALL SELECT 'X3_CIF_PHONE', customer_id || CHR(31) || phone, id FROM remade
  UNION ALL SELECT 'X4_PERSON_NAME_ADDRCD_PHONE', full_name || CHR(31) || address_code || CHR(31) || phone, id
    FROM remade
  UNION ALL SELECT 'X5_COMPANY_NAME_ADDRCD_PHONE', company_name || CHR(31) || address_code || CHR(31) || phone, id
    FROM remade
  UNION ALL SELECT 'F1_NAME~_ADDRCD_PHONE', address_code || CHR(31) || phone, id FROM remade
  UNION ALL SELECT 'F2_NAME~_ADDRESS~_PHONE', phone || CHR(31) || address__address_first3, id FROM remade
  UNION ALL SELECT 'F3_NAME~_CIF', customer_id, id FROM remade
  UNION ALL SELECT 'F4_NAME_ADDRCD_PHONE~', person_name || CHR(31) || address_code, id FROM remade
  UNION ALL SELECT 'F5_COMPANY~_PHONE_POSTAL', phone || CHR(31) || postal_code, id FROM remade
  UNION ALL SELECT 'F6_COMPANY~_ADDRCD_PHONE', address_code || CHR(31) || phone, id FROM remade
  UNION ALL SELECT 'F7_GIVEN_ADDRCD_PHONE', given_name || CHR(31) || address_code || CHR(31) || phone, id FROM remade
) JOIN rules USING (rule)
WHERE k IS NOT NULL AND rules.used;

-- rule_keys holds every record's rule keys. The records made again leave it, and the changed records' keys join it.
CREATE TABLE IF NOT EXISTS rule_keys CLUSTER BY k AS SELECT i, k, id FROM made_rule_keys WHERE FALSE;

-- when: EXISTS (SELECT 1 FROM changed WHERE again)
DELETE FROM rule_keys WHERE id IN (SELECT id FROM changed WHERE again);

INSERT INTO rule_keys SELECT i, k, id FROM made_rule_keys;

-- rule_blocks holds every record of each rule key the batch holds. new is TRUE for the batch's records, and n is the
-- number of records that hold the key.
-- In the run's first batch (batch 0) every record is the batch's, so every rule key is. A lookup takes the second
-- form whatever its batch, so that only the record it looks up counts as new.
-- when: NOT @lookup AND (SELECT batch FROM this_batch) = 0
CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, k, id, TRUE AS new, COUNT(*) OVER (PARTITION BY i, k) AS n FROM rule_keys;

-- when: @lookup OR (SELECT batch FROM this_batch) > 0
CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, k, id, id IN (SELECT id FROM fresh) AS new, COUNT(*) OVER (PARTITION BY i, k) AS n
FROM rule_keys JOIN (SELECT DISTINCT i, k FROM made_rule_keys WHERE id IN (SELECT id FROM fresh)) USING (i, k);


-- 2. The keys. Each generator makes a key for each record from one or more of its fields, joined by CHR(31). The
--    records with the same key form a block. A deletion generator makes several keys for a record. They are its value
--    with each character deleted in turn, and the value whole, each joined to the generator's other fields. Deleting
--    any character of a run of equal characters gives the same value, so a run gives its key once.
CREATE OR REPLACE TEMP TABLE made_keys AS  -- the keys of the records in changed
WITH remade AS (SELECT * FROM records WHERE id IN (SELECT id FROM changed))
SELECT generators.g, k, id FROM (
  SELECT 'cif' AS name, customer_id AS k, id FROM remade
  UNION ALL SELECT 'phone_prefecture', phone || CHR(31) || prefecture, id FROM remade
  UNION ALL SELECT 'phone_postal_area', phone || CHR(31) || postal_code__first3, id FROM remade
  UNION ALL SELECT 'phone_name_initial', phone || CHR(31) || any_name__initial, id FROM remade
  UNION ALL SELECT 'person_name', person_name__kana_fold, id FROM remade
  UNION ALL SELECT 'company_name', company_name__nfkc_strip_legal_form_kana_fold, id FROM remade
  UNION ALL SELECT 'company_name_deletions', SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT company_name__nfkc_strip_legal_form_kana_fold AS x, id FROM remade
          WHERE company_name__nfkc_strip_legal_form_kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'person_name_deletions_postal_area', w || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT person_name__kana_fold AS x, postal_code__first3 AS w, id FROM remade
          WHERE person_name__kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'given_name_postal', given_name__kana_fold || CHR(31) || postal_code, id FROM remade
  UNION ALL SELECT 'address_phone', address__address || CHR(31) || phone, id FROM remade
  UNION ALL SELECT 'address_code_phone', address_code || CHR(31) || phone, id FROM remade
  UNION ALL SELECT 'address_name_initial', address__address || CHR(31) || any_name__initial, id FROM remade
  UNION ALL SELECT 'address_code_name_initial', address_code || CHR(31) || any_name__initial, id FROM remade
  UNION ALL SELECT 'given_name_address_code', given_name__kana_fold || CHR(31) || address_code, id FROM remade
  UNION ALL SELECT 'cif_deletions', SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT customer_id AS x, id FROM remade WHERE customer_id IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'birth_date', birth_date, id FROM remade
  UNION ALL SELECT 'given_name_phone', given_name__kana_fold || CHR(31) || phone, id FROM remade
  UNION ALL SELECT 'birth_date_deletions_prefecture', w || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id
    FROM (SELECT birth_date AS x, prefecture AS w, id FROM remade WHERE birth_date IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 'name_reading', person_name__kana_fold_long_vowel, id FROM remade
  UNION ALL SELECT 'phone_given_tail', phone || CHR(31) || person_name__kana_fold_long_vowel_last3, id FROM remade
  UNION ALL SELECT 'postal_given_tail', postal_code || CHR(31) || person_name__kana_fold_long_vowel_last3, id FROM remade
  UNION ALL SELECT 'postal_area_given_tail', postal_code__first3 || CHR(31) || person_name__kana_fold_long_vowel_last3, id
    FROM remade
) JOIN generators USING (name)
WHERE k IS NOT NULL AND generators.used;

-- every_key holds every record's keys, which are the index a lookup reads by key. The records made again leave it,
-- and the changed records' keys join it.
CREATE TABLE IF NOT EXISTS every_key CLUSTER BY k AS SELECT g, k, id FROM made_keys WHERE FALSE;

-- when: EXISTS (SELECT 1 FROM changed WHERE again)
DELETE FROM every_key WHERE id IN (SELECT id FROM changed WHERE again);

INSERT INTO every_key SELECT g, k, id FROM made_keys;

-- block_size gives a block's whole size if records holds only part of it. A lookup makes the table first, with the
-- blocks it read in part. In any other job, this statement makes it empty.
CREATE TEMP TABLE IF NOT EXISTS block_size (g INT64, k STRING, n INT64);

-- key_blocks gives each key its block's size n among all the run's records. It keeps only the blocks that touch the
-- batch and hold two records or more, since only those can make a pair. A lookup also keeps its record's blocks of
-- one, so that lookup.sql can report every key.
-- In the run's first batch every record is the batch's, so every block is.
-- when: NOT @lookup AND (SELECT batch FROM this_batch) = 0
CREATE OR REPLACE TEMP TABLE key_blocks AS
SELECT g, k, id, TRUE AS new, n FROM (SELECT g, k, id, COUNT(*) OVER (PARTITION BY g, k) AS n FROM every_key)
WHERE n > 1;

-- when: @lookup OR (SELECT batch FROM this_batch) > 0
CREATE OR REPLACE TEMP TABLE key_blocks AS
-- touched holds every record of each block that a key of the batch names. held is the number of records the run
-- holds in the block.
WITH touched AS (
  SELECT e.g, e.k, e.id, COUNT(*) OVER (PARTITION BY e.g, e.k) AS held
  FROM every_key AS e JOIN (SELECT DISTINCT g, k FROM made_keys WHERE id IN (SELECT id FROM fresh)) USING (g, k)
)
SELECT t.g, t.k, t.id, t.id IN (SELECT id FROM fresh) AS new, COALESCE(u.n, t.held) AS n
FROM touched AS t LEFT JOIN block_size AS u USING (g, k)
WHERE (t.held > 1 OR @lookup)  -- records holds two of the block's records or more, or the job is a lookup
  -- and the block at its whole size (block_size) holds two records or more, or the record is the batch's. So a lookup
  -- keeps a block of one only for the record it looks up.
  AND (COALESCE(u.n, t.held) > 1 OR t.id IN (SELECT id FROM fresh));

-- listed holds every pair that touches the batch and shares a block of fewer than @oversized records. bits has one
-- bit set for each generator whose keys list the pair.
CREATE OR REPLACE TEMP TABLE listed AS
SELECT LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r, BIT_OR(1 << a.g) AS bits
FROM key_blocks AS a JOIN key_blocks AS b ON a.g = b.g AND a.k = b.k AND a.id <> b.id AND (NOT b.new OR a.id < b.id)
WHERE a.new AND a.n < @oversized
GROUP BY l, r;


-- 3. The model's bits, as a score reads them. weights holds the prior and, for each comparison, an array of its
--    levels' bits. Level γ's bits are at OFFSET(γ + 1), so the missing level, -1, is at OFFSET(0) and weighs 0.
--    weight_of gives a pair's points, the prior plus its levels' bits, added in the model's order. bound_of gives an
--    upper bound of a pair's points from cheap tests alone.
CREATE OR REPLACE TEMP TABLE weights AS
-- run_records counts the run's records. @outside counts those a lookup didn't read.
WITH size AS (SELECT COUNT(*) + @outside AS run_records FROM records),
rate AS (  -- λ is a per-pair rate, so it is rescaled to the run's size, as em.fitted rescales it
  -- It is capped a hair under 1, so that its log-odds below stay finite.
  SELECT LEAST(f.probability * (f.fit_rows - 1) / GREATEST(size.run_records - 1, 1), 1 - CAST(0.000000001 AS FLOAT64))
           AS rate
  FROM fit AS f, size
),
prior_bits AS (  -- the prior is fit's own if the run has as many records as when fit ran, else the rescaled λ's bits
  SELECT IF(f.records = size.run_records, f.prior_bits, LOG(rate.rate / (1 - rate.rate), 2)) AS prior_bits
  FROM fit AS f, size, rate
)
SELECT
  (SELECT prior_bits FROM prior_bits) AS prior_bits,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'name' ORDER BY gamma)) AS name,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'company' ORDER BY gamma)) AS company,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'address' ORDER BY gamma)) AS address,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'phone' ORDER BY gamma)) AS phone,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'cif' ORDER BY gamma)) AS cif,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'birth' ORDER BY gamma)) AS birth,
  -- Each *_after is the most bits a fuzzy comparison can still earn once its leading equalities fail.
  (SELECT MAX(bits) FROM model WHERE comparison = 'name' AND gamma <= 3) AS name_after,
  (SELECT MAX(bits) FROM model WHERE comparison = 'company' AND gamma <= 1) AS company_after;

-- bits_at returns level gamma's bits from one of weights' arrays, as functions.sql numbers the levels. A missing side
-- (level -1) is at OFFSET(0) and weighs 0. gamma is ANY TYPE, as is could_reach's bound, because DuckDB binds a typed
-- parameter's argument twice, and these arguments are whole comparisons.
CREATE OR REPLACE TEMP FUNCTION bits_at(levels ANY TYPE, gamma ANY TYPE) AS (levels[OFFSET(gamma + 1)]);

-- weight_of's level parameters are g_name, g_company and so on, not the names of w's fields, because DuckDB would
-- substitute a parameter into a field of the same name too.
CREATE OR REPLACE TEMP FUNCTION weight_of(g_name INT64, g_company INT64, g_address INT64, g_phone INT64, g_cif INT64,
                                          g_birth INT64, w ANY TYPE) AS (
  w.prior_bits + bits_at(w.name, g_name) + bits_at(w.company, g_company) + bits_at(w.address, g_address)
  + bits_at(w.phone, g_phone) + bits_at(w.cif, g_cif) + bits_at(w.birth, g_birth)
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
CREATE OR REPLACE TEMP FUNCTION name_bound(l ANY TYPE, r ANY TYPE, w ANY TYPE) AS (
  CASE WHEN l.person_name IS NULL OR r.person_name IS NULL THEN bits_at(w.name, -1)
       WHEN l.person_name = r.person_name THEN bits_at(w.name, 6)                                     -- exact
       WHEN l.person_name__kana_fold = r.person_name__kana_fold THEN bits_at(w.name, 5)               -- fold exact
       WHEN l.person_name__kana_fold_long_vowel = r.person_name__kana_fold_long_vowel
         THEN bits_at(w.name, 4)                                                                      -- same reading
       WHEN l.person_name__kana_fold IS NULL OR r.person_name__kana_fold IS NULL THEN w.name_after
       ELSE GREATEST(IF(l.given_name__kana_fold = r.given_name__kana_fold, bits_at(w.name, 2), bits_at(w.name, 0)),
                     CASE WHEN name_jw_most(l, r) < cut_from(CAST(0.75 AS FLOAT64))
                            THEN bits_at(w.name, 0)  -- most pairs stop here, so name_jw_most runs once for them
                          WHEN name_jw_most(l, r) < cut_from(CAST(0.95 AS FLOAT64))
                            THEN GREATEST(bits_at(w.name, 0), bits_at(w.name, 1))  -- else, fold JW low
                          ELSE GREATEST(bits_at(w.name, 0), bits_at(w.name, 1), bits_at(w.name, 3))  -- and JW high
                     END)
  END
);

-- company_bound takes the company's JW low level only if jaro_winkler_most allows it.
CREATE OR REPLACE TEMP FUNCTION company_bound(l ANY TYPE, r ANY TYPE, w ANY TYPE) AS (
  CASE WHEN l.company_name IS NULL OR r.company_name IS NULL THEN bits_at(w.company, -1)
       WHEN l.company_name__nfkc_strip_legal_form_kana_fold = r.company_name__nfkc_strip_legal_form_kana_fold
         THEN bits_at(w.company, 2)                                                                   -- exact
       WHEN l.company_name__nfkc_strip_legal_form_kana_fold IS NULL
            OR r.company_name__nfkc_strip_legal_form_kana_fold IS NULL
         THEN w.company_after
       WHEN jaro_winkler_most(l.company_name__nfkc_strip_legal_form_kana_fold,
                              r.company_name__nfkc_strip_legal_form_kana_fold)
            >= cut_from(CAST(0.8 AS FLOAT64)) THEN w.company_after
       ELSE bits_at(w.company, 0)                                                                     -- else
  END
);

-- address_bound takes "address close" only if the two addresses' lengths differ by two characters or less, and "same
-- postal" only if the postal codes are equal.
CREATE OR REPLACE TEMP FUNCTION address_bound(l ANY TYPE, r ANY TYPE, w ANY TYPE) AS (
  CASE WHEN (l.address_code IS NULL OR r.address_code IS NULL) AND (l.address IS NULL OR r.address IS NULL)
            AND (l.postal_code IS NULL OR r.postal_code IS NULL) THEN bits_at(w.address, -1)
       WHEN l.address_code = r.address_code OR l.address__address = r.address__address
         THEN bits_at(w.address, 3)                                                                   -- same address
       ELSE GREATEST(bits_at(w.address, 0),                                                           -- else
                     IF(l.address__address IS NOT NULL AND r.address__address IS NOT NULL
                        AND ABS(LENGTH(l.address__address) - LENGTH(r.address__address)) <= 2,
                        bits_at(w.address, 2), bits_at(w.address, 0)),                                -- address close
                     IF(l.postal_code = r.postal_code, bits_at(w.address, 1), bits_at(w.address, 0)))  -- same postal
  END
);

-- bound_of adds the prior and each comparison's bound in the model's order, as weight_of adds a pair's points. The
-- cheap comparisons (phone, cif and birth) take their own level.
CREATE OR REPLACE TEMP FUNCTION bound_of(l ANY TYPE, r ANY TYPE, w ANY TYPE) AS (
  w.prior_bits + name_bound(l, r, w) + company_bound(l, r, w) + address_bound(l, r, w)
  + bits_at(w.phone, gamma_phone(l, r)) + bits_at(w.cif, gamma_cif(l, r)) + bits_at(w.birth, gamma_birth(l, r))
);

-- could_reach is TRUE if a pair whose points are at most bound could reach floor. bound_of adds its bits in
-- weight_of's order, each at least the pair's own level's, so rounding never leaves a pair's bound under its points.
-- The margin of 1e-9 under the floor keeps the test safe should the two orders ever part.
CREATE OR REPLACE TEMP FUNCTION could_reach(bound ANY TYPE, floor ANY TYPE) AS (
  bound >= floor - CAST(0.000000001 AS FLOAT64)
);


-- 4. The gate. A block of @oversized records or more is joined only if a sample of its pairs holds a pair with
--    @search_floor points or more. The sample pairs the block's first @oversized batch records, by hash, with its
--    first @oversized records. It leaves out the pairs another block already listed, and it is scored as the run
--    scores. A big block holds few true matches, and a placeholder's block (a dummy phone, say) holds none.
CREATE OR REPLACE TEMP TABLE gate_pairs AS
WITH ranked AS (  -- nth_in_block is a record's place in its block by hash, and nth_in_batch its place among the batch's
  SELECT g, k, id, new,
         ROW_NUMBER() OVER (PARTITION BY g, k ORDER BY er_hash(id)) AS nth_in_block,
         IF(new, ROW_NUMBER() OVER (PARTITION BY g, k, new ORDER BY er_hash(id)), NULL) AS nth_in_batch
  FROM key_blocks WHERE n >= @oversized
)
SELECT DISTINCT a.g, a.k, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
FROM ranked AS a JOIN ranked AS b ON a.g = b.g AND a.k = b.k AND a.id <> b.id
WHERE a.nth_in_batch <= @oversized AND b.nth_in_block <= @oversized
  AND NOT EXISTS (SELECT 1 FROM listed AS seen WHERE seen.l = LEAST(a.id, b.id) AND seen.r = GREATEST(a.id, b.id));

CREATE OR REPLACE TEMP TABLE gated AS
-- scored_sample holds each sampled pair that the bound keeps, with its points. name_score is name_level's argument,
-- so BigQuery computes it once a pair, as a function's arguments are computed before its body. A subquery that
-- computed it first, as batch_scored does, would carry x and y whole, and read compared's full_name too.
WITH scored_sample AS (
  SELECT p.l, p.r,
         weight_of(name_level(x, y, name_score(x, y)), gamma_company(x, y), gamma_address(x, y), gamma_phone(x, y),
                   gamma_cif(x, y), gamma_birth(x, y), w) AS w
  FROM (SELECT DISTINCT l, r FROM gate_pairs) AS p JOIN compared AS x ON x.id = p.l JOIN compared AS y ON y.id = p.r
  CROSS JOIN weights AS w
  WHERE could_reach(bound_of(x, y, w), @search_floor)
),
-- sampled counts every sampled pair of a block, those the bound dropped among them. best and hits read only the pairs
-- scored.
stats AS (
  SELECT p.g, p.k, COUNT(*) AS sampled, MAX(s.w) AS best, COUNT(CASE WHEN s.w >= @search_floor THEN 1 END) AS hits
  FROM gate_pairs AS p LEFT JOIN scored_sample AS s USING (l, r) GROUP BY p.g, p.k
)
SELECT z.g, z.k AS value, z.n AS records, pairs_of(z.n) AS pairs,
       COALESCE(s.sampled, 0) AS sampled, s.best, COALESCE(s.hits, 0) AS hits,
       CASE WHEN COALESCE(s.hits, 0) > 0 THEN 'kept' WHEN COALESCE(s.sampled, 0) = 0 THEN 'skipped: other keys list its sampled pairs'
            ELSE 'skipped: no sampled pair reaches the floor' END AS decision
FROM (SELECT DISTINCT g, k, n FROM key_blocks WHERE n >= @oversized) AS z
LEFT JOIN stats AS s ON s.g = z.g AND s.k = z.k;


-- 5. The candidates. They are the pairs in listed, and every pair of a kept block that touches the batch. Each comes
--    with the keys that listed it, as sources.
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
named AS (  -- each set of bits becomes the generators' names, in their order, joined by +
  SELECT bits, ARRAY_TO_STRING(ARRAY(SELECT name FROM generators WHERE (bits >> g) & 1 = 1 ORDER BY g), '+') AS sources
  FROM (SELECT DISTINCT bits FROM pairs)
)
SELECT pairs.l, pairs.r, named.sources FROM pairs JOIN named USING (bits);


-- 6. The scores. Each candidate that the bound keeps, and every rule pair, gets its levels and its points. The pairs
--    with @keep_from points or more are kept, and so is every rule pair. named is true if a name was compared, the
--    person's or the company's. The batch's pairs are added to the run's scored. Each pair is scored once, in the
--    batch that brings its later record.
CREATE OR REPLACE TEMP TABLE batch_pairs AS  -- each of the batch's candidates and rule pairs appears once
WITH found AS (
  SELECT a.i, rules.rule, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
  FROM rule_blocks AS a JOIN rule_blocks AS b ON a.i = b.i AND a.k = b.k AND a.id <> b.id AND (NOT b.new OR a.id < b.id)
  -- A function given a row reads all of its columns, so x and y are rows of compared, which holds only the columns
  -- the comparisons read.
  JOIN compared AS x ON x.id = a.id JOIN compared AS y ON y.id = b.id
  JOIN rules ON rules.i = a.i
  WHERE a.new AND a.n < @oversized
    AND CASE rules.rule  -- These are the fuzzy rules' tests. The exact rules (X1-X5) and F7 test their keys alone.
          WHEN 'F1_NAME~_ADDRCD_PHONE' THEN near_name(x, y)
          WHEN 'F2_NAME~_ADDRESS~_PHONE' THEN near_name(x, y) AND near_address(x, y)
          WHEN 'F3_NAME~_CIF' THEN near_name(x, y)
          WHEN 'F4_NAME_ADDRCD_PHONE~' THEN near_phone(x, y)
          WHEN 'F5_COMPANY~_PHONE_POSTAL' THEN near_company(x, y)
          WHEN 'F6_COMPANY~_ADDRCD_PHONE' THEN near_company(x, y)
          ELSE TRUE END
),
rule_pairs AS (  -- each pair a rule finds, with the first rule in order that finds it (the least i)
  SELECT l, r, MIN_BY(rule, i) AS rule FROM found GROUP BY l, r
)
SELECT l, r, c.sources, p.rule FROM cands AS c FULL JOIN rule_pairs AS p USING (l, r);

CREATE OR REPLACE TEMP TABLE batch_scored AS
WITH kept AS (  -- kept computes the names' Jaro–Winkler (s_name) once for each pair the bound keeps
  SELECT p.l, p.r, p.sources, p.rule, x, y, name_score(x, y) AS s_name
  FROM batch_pairs AS p JOIN compared AS x ON x.id = p.l JOIN compared AS y ON y.id = p.r CROSS JOIN weights AS w
  WHERE p.rule IS NOT NULL OR could_reach(bound_of(x, y, w), @keep_from)
),
levelled AS (
  SELECT l, r, sources, rule, name_level(x, y, s_name) AS gamma_name, gamma_company(x, y) AS gamma_company,
         gamma_address(x, y) AS gamma_address, gamma_phone(x, y) AS gamma_phone, gamma_cif(x, y) AS gamma_cif,
         gamma_birth(x, y) AS gamma_birth
  FROM kept
),
weighed AS (
  SELECT x.*,
         weight_of(gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth, w) AS match_weight
  FROM levelled AS x CROSS JOIN weights AS w
)
SELECT
  l AS id_l, r AS id_r, match_weight,
  probability_of(match_weight) AS match_probability,
  sources, rule, (gamma_name >= 0 OR gamma_company >= 0) AS named,
  gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth
FROM weighed
WHERE match_weight >= @keep_from OR rule IS NOT NULL;

CREATE TABLE IF NOT EXISTS scored AS SELECT * FROM batch_scored WHERE FALSE;

INSERT INTO scored SELECT * FROM batch_scored;
