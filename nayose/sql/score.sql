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
--   gated                     each oversized block that touches the batch, its sample, and whether it was kept
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

-- The generators and the rules are listed by name, in order. A generator's position (g) is its bit in the pairs'
-- bits, which cands turns into sources. A rule's position (i) is its rank: if several rules find a pair, the first
-- one names it. config.toml says which ones this run uses, and a name it gives that isn't listed here is refused.
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
SELECT i, k, id FROM (
  SELECT 0 AS i, customer_id || CHR(31) || full_name AS k, id FROM remade             -- X1_CIF_PERSON_NAME
  UNION ALL SELECT 1, customer_id || CHR(31) || company_name, id FROM remade          -- X2_CIF_COMPANY_NAME
  UNION ALL SELECT 2, customer_id || CHR(31) || phone, id FROM remade                 -- X3_CIF_PHONE
  UNION ALL SELECT 3, full_name || CHR(31) || address_code || CHR(31) || phone, id     -- X4_PERSON_NAME_ADDRCD_PHONE
    FROM remade
  UNION ALL SELECT 4, company_name || CHR(31) || address_code || CHR(31) || phone, id  -- X5_COMPANY_NAME_ADDRCD_PHONE
    FROM remade
  UNION ALL SELECT 5, address_code || CHR(31) || phone, id FROM remade                -- F1_NAME~_ADDRCD_PHONE
  UNION ALL SELECT 6, phone || CHR(31) || address__address_first3, id FROM remade     -- F2_NAME~_ADDRESS~_PHONE
  UNION ALL SELECT 7, customer_id, id FROM remade                                     -- F3_NAME~_CIF
  UNION ALL SELECT 8, person_name || CHR(31) || address_code, id FROM remade          -- F4_NAME_ADDRCD_PHONE~
  UNION ALL SELECT 9, phone || CHR(31) || postal_code, id FROM remade                 -- F5_COMPANY~_PHONE_POSTAL
  UNION ALL SELECT 10, address_code || CHR(31) || phone, id FROM remade               -- F6_COMPANY~_ADDRCD_PHONE
  UNION ALL SELECT 11, given_name || CHR(31) || address_code || CHR(31) || phone, id   -- F7_GIVEN_ADDRCD_PHONE
    FROM remade
) WHERE k IS NOT NULL AND i IN (SELECT i FROM rules WHERE used);

-- rule_keys holds every record's rule keys. The records made again leave it, and the changed records' keys join it.
CREATE TABLE IF NOT EXISTS rule_keys CLUSTER BY k AS SELECT i, k, id FROM made_rule_keys WHERE FALSE;

-- when: EXISTS (SELECT 1 FROM changed WHERE again)
DELETE FROM rule_keys WHERE id IN (SELECT id FROM changed WHERE again);

INSERT INTO rule_keys SELECT i, k, id FROM made_rule_keys;

-- rule_blocks holds every record of each rule key the batch holds. new is TRUE for the batch's records, and n is the
-- number of records that hold the key.
-- In the run's first batch (batch 0) every record is the batch's, so every rule key is. A lookup's batch is never
-- the first, so that it keeps its record's blocks of one.
-- when: NOT @lookup AND (SELECT batch FROM this_batch) = 0
CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, k, id, TRUE AS new, COUNT(*) OVER (PARTITION BY i, k) AS n FROM rule_keys;

-- when: @lookup OR (SELECT batch FROM this_batch) > 0
CREATE OR REPLACE TEMP TABLE rule_blocks AS
SELECT i, k, id, id IN (SELECT id FROM fresh) AS new, COUNT(*) OVER (PARTITION BY i, k) AS n
FROM rule_keys JOIN (SELECT DISTINCT i, k FROM made_rule_keys WHERE id IN (SELECT id FROM fresh)) USING (i, k);

CREATE OR REPLACE TEMP TABLE batch_rule_pairs AS
WITH found AS (
  SELECT a.i, LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r
  FROM rule_blocks AS a JOIN rule_blocks AS b ON a.i = b.i AND a.k = b.k AND a.id <> b.id AND (NOT b.new OR a.id < b.id)
  -- A function given a row reads all of its columns, so x and y are rows of compared, which holds only the columns
  -- the comparisons read.
  JOIN compared AS x ON x.id = a.id JOIN compared AS y ON y.id = b.id
  WHERE a.new AND a.n < @oversized
    AND CASE a.i  -- These are the fuzzy rules' tests. The exact rules (X1-X5) and F7 test their keys alone.
          WHEN 5 THEN near_name(x, y)                         -- F1_NAME~_ADDRCD_PHONE
          WHEN 6 THEN near_name(x, y) AND near_address(x, y)  -- F2_NAME~_ADDRESS~_PHONE
          WHEN 7 THEN near_name(x, y)                         -- F3_NAME~_CIF
          WHEN 8 THEN near_phone(x, y)                        -- F4_NAME_ADDRCD_PHONE~
          WHEN 9 THEN near_company(x, y)                      -- F5_COMPANY~_PHONE_POSTAL
          WHEN 10 THEN near_company(x, y)                     -- F6_COMPANY~_ADDRCD_PHONE
          ELSE TRUE END
)
SELECT f.l, f.r, rules.rule
FROM (SELECT l, r, MIN(i) AS i FROM found GROUP BY l, r) AS f JOIN rules USING (i);


-- 2. The keys. Each generator makes a key for each record from one or more of its fields, joined by CHR(31). The
--    records with the same key form a block. A deletion generator makes several keys for a record. They are its value
--    with each character deleted in turn, and the value whole, each joined to the generator's other fields. Deleting
--    any character of a run of equal characters gives the same value, so a run gives its key once.
CREATE OR REPLACE TEMP TABLE made_keys AS  -- the keys of the records in changed
WITH remade AS (SELECT * FROM records WHERE id IN (SELECT id FROM changed))
SELECT g, k, id FROM (
  SELECT 0 AS g, customer_id AS k, id FROM remade                                        -- cif
  UNION ALL SELECT 1, phone || CHR(31) || prefecture, id FROM remade                     -- phone_prefecture
  UNION ALL SELECT 2, phone || CHR(31) || postal_code__first3, id FROM remade            -- phone_postal_area
  UNION ALL SELECT 3, phone || CHR(31) || any_name__initial, id FROM remade              -- phone_name_initial
  UNION ALL SELECT 4, person_name__kana_fold, id FROM remade                             -- person_name
  UNION ALL SELECT 5, company_name__nfkc_strip_legal_form_kana_fold, id FROM remade      -- company_name
  UNION ALL SELECT 6, SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id                         -- company_name_deletions
    FROM (SELECT company_name__nfkc_strip_legal_form_kana_fold AS x, id FROM remade
          WHERE company_name__nfkc_strip_legal_form_kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 7, w || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id  -- person_name_deletions_postal_area
    FROM (SELECT person_name__kana_fold AS x, postal_code__first3 AS w, id FROM remade
          WHERE person_name__kana_fold IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 8, given_name__kana_fold || CHR(31) || postal_code, id FROM remade    -- given_name_postal
  UNION ALL SELECT 9, address__address || CHR(31) || phone, id FROM remade               -- address_phone
  UNION ALL SELECT 10, address_code || CHR(31) || phone, id FROM remade                  -- address_code_phone
  UNION ALL SELECT 11, address__address || CHR(31) || any_name__initial, id FROM remade  -- address_name_initial
  UNION ALL SELECT 12, address_code || CHR(31) || any_name__initial, id FROM remade      -- address_code_name_initial
  UNION ALL SELECT 13, given_name__kana_fold || CHR(31) || address_code, id FROM remade  -- given_name_address_code
  UNION ALL SELECT 14, SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id                        -- cif_deletions
    FROM (SELECT customer_id AS x, id FROM remade WHERE customer_id IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 15, birth_date, id FROM remade                                        -- birth_date
  UNION ALL SELECT 16, given_name__kana_fold || CHR(31) || phone, id FROM remade         -- given_name_phone
  UNION ALL SELECT 17, w || CHR(31) || SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1), id  -- birth_date_deletions_prefecture
    FROM (SELECT birth_date AS x, prefecture AS w, id FROM remade WHERE birth_date IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, LENGTH(x) + 1)) AS i
    WHERE i = 1 OR i > LENGTH(x) OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1)
  UNION ALL SELECT 18, person_name__kana_fold_long_vowel, id FROM remade                 -- name_reading
  UNION ALL SELECT 19, phone || CHR(31)                                                   -- phone_given_tail
                       || person_name__kana_fold_long_vowel_last3, id FROM remade
  UNION ALL SELECT 20, postal_code || CHR(31)                                             -- postal_given_tail
                       || person_name__kana_fold_long_vowel_last3, id FROM remade
  UNION ALL SELECT 21, postal_code__first3 || CHR(31)                                     -- postal_area_given_tail
                       || person_name__kana_fold_long_vowel_last3, id FROM remade
) WHERE k IS NOT NULL AND g IN (SELECT g FROM generators WHERE used);

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
WHERE (t.held > 1 OR @lookup) AND (COALESCE(u.n, t.held) > 1 OR t.id IN (SELECT id FROM fresh));

-- listed holds every pair that touches the batch and shares a block of fewer than @oversized records. bits has one
-- bit set for each generator whose keys list the pair.
CREATE OR REPLACE TEMP TABLE listed AS
SELECT LEAST(a.id, b.id) AS l, GREATEST(a.id, b.id) AS r, BIT_OR(1 << a.g) AS bits
FROM key_blocks AS a JOIN key_blocks AS b ON a.g = b.g AND a.k = b.k AND a.id <> b.id AND (NOT b.new OR a.id < b.id)
WHERE a.new AND a.n < @oversized
GROUP BY 1, 2;


-- 3. The model's bits, as a score reads them. weights holds the prior and, for each comparison, an array of its
--    levels' bits. Level γ's bits are at OFFSET(γ + 1), so the missing level, -1, is at OFFSET(0) and weighs 0.
--    weight_of gives a pair's points, the prior plus its levels' bits, added in the model's order. bound_of gives an
--    upper bound of a pair's points from cheap tests alone.
CREATE OR REPLACE TEMP TABLE weights AS
WITH size AS (SELECT COUNT(*) + @outside AS n FROM records),  -- @outside counts the run's records a lookup didn't read
lam AS (  -- λ is a per-pair rate, so it is rescaled to the run's size, as em.fitted rescales it
  SELECT LEAST(f.probability * (f.fit_rows - 1) / GREATEST(n.n - 1, 1), 1 - CAST(0.000000001 AS FLOAT64)) AS lam
  FROM fit AS f, size AS n
),
prior AS (  -- the prior is fit's own if the run has as many records as when fit ran, else the rescaled λ's bits
  SELECT IF(f.records = n.n, f.prior_bits, LOG(l.lam / (1 - l.lam), 2)) AS bits FROM fit AS f, size AS n, lam AS l
)
SELECT
  (SELECT bits FROM prior) AS prior,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'name' ORDER BY gamma)) AS name,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'company' ORDER BY gamma)) AS company,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'address' ORDER BY gamma)) AS address,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'phone' ORDER BY gamma)) AS phone,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'cif' ORDER BY gamma)) AS cif,
  ARRAY_CONCAT([CAST(0 AS FLOAT64)], ARRAY(SELECT bits FROM model WHERE comparison = 'birth' ORDER BY gamma)) AS birth,
  -- Each *_after is the most bits a fuzzy comparison can still earn once its leading equalities fail.
  (SELECT MAX(bits) FROM model WHERE comparison = 'name' AND gamma <= 3) AS name_after,
  (SELECT MAX(bits) FROM model WHERE comparison = 'company' AND gamma <= 1) AS company_after;

-- weight_of's level parameters are g_name, g_company and so on, not the names of w's fields, because DuckDB would
-- substitute a parameter into a field of the same name too.
CREATE OR REPLACE TEMP FUNCTION weight_of(g_name INT64, g_company INT64, g_address INT64, g_phone INT64, g_cif INT64,
                                          g_birth INT64, w ANY TYPE) AS (
  w.prior + w.name[OFFSET(g_name + 1)] + w.company[OFFSET(g_company + 1)] + w.address[OFFSET(g_address + 1)]
  + w.phone[OFFSET(g_phone + 1)] + w.cif[OFFSET(g_cif + 1)] + w.birth[OFFSET(g_birth + 1)]
);

-- bound_of returns an upper bound of a pair's points from cheap tests alone: equalities, lengths, the names' letters
-- and the cheap comparisons' own levels. If a leading equality
-- settles a fuzzy comparison's level, the bound takes that level. Otherwise it takes the best level the comparison can
-- still reach. A Jaro–Winkler level counts only if name_jw_most or jaro_winkler_most, the most the score can be,
-- reaches its threshold. The given name's level counts only if the given names are equal, "address close" only if the
-- two addresses' lengths differ by two characters or less, and "same postal" only if the postal codes are equal. The
-- cheap comparisons (phone, cif and birth) take their own level. No pair that the bound rules out could reach the
-- floor it is tested against, so the costly comparisons run only on the pairs it keeps.
-- w.<comparison>[OFFSET(γ + 1)] is level γ's bits, as functions.sql numbers the levels, and OFFSET(0) is a missing
-- side's 0 bits. Each level's name stands on the line that reads it. Each Jaro–Winkler threshold sits a hair under
-- its level's (0.75, 0.95, 0.8), as in the cl_* cuts, because rapidfuzz's scores are float32.
CREATE OR REPLACE TEMP FUNCTION bound_of(l ANY TYPE, r ANY TYPE, w ANY TYPE) AS (
  w.prior
  + CASE WHEN l.person_name IS NULL OR r.person_name IS NULL THEN CAST(0 AS FLOAT64)
         WHEN l.person_name = r.person_name THEN w.name[OFFSET(7)]  -- exact
         WHEN l.person_name__kana_fold = r.person_name__kana_fold THEN w.name[OFFSET(6)]  -- fold exact
         WHEN l.person_name__kana_fold_long_vowel = r.person_name__kana_fold_long_vowel
           THEN w.name[OFFSET(5)]  -- same reading
         WHEN l.person_name__kana_fold IS NULL OR r.person_name__kana_fold IS NULL THEN w.name_after
         -- This takes the given name's level if the given names are equal (else the else level), or the best
         -- Jaro–Winkler level that the names' letters still allow, whichever is higher.
         ELSE GREATEST(IF(l.given_name__kana_fold = r.given_name__kana_fold, w.name[OFFSET(3)], w.name[OFFSET(1)]),
                       CASE WHEN name_jw_most(l, r) < CAST(0.749999 AS FLOAT64)
                              THEN w.name[OFFSET(1)]  -- most pairs stop here, so name_jw_most runs once for them
                            WHEN name_jw_most(l, r) < CAST(0.949999 AS FLOAT64)
                              THEN GREATEST(w.name[OFFSET(1)], w.name[OFFSET(2)])  -- else, fold JW low
                            ELSE GREATEST(w.name[OFFSET(1)], w.name[OFFSET(2)], w.name[OFFSET(4)])  -- and JW high
                       END) END
  + CASE WHEN l.company_name IS NULL OR r.company_name IS NULL THEN CAST(0 AS FLOAT64)
         WHEN l.company_name__nfkc_strip_legal_form_kana_fold = r.company_name__nfkc_strip_legal_form_kana_fold
           THEN w.company[OFFSET(3)]  -- exact
         WHEN l.company_name__nfkc_strip_legal_form_kana_fold IS NULL
              OR r.company_name__nfkc_strip_legal_form_kana_fold IS NULL
           THEN w.company_after
         WHEN jaro_winkler_most(l.company_name__nfkc_strip_legal_form_kana_fold,
                                r.company_name__nfkc_strip_legal_form_kana_fold)
              >= CAST(0.799999 AS FLOAT64) THEN w.company_after
         ELSE w.company[OFFSET(1)] END  -- else
  + CASE WHEN (l.address_code IS NULL OR r.address_code IS NULL) AND (l.address IS NULL OR r.address IS NULL)
              AND (l.postal_code IS NULL OR r.postal_code IS NULL) THEN CAST(0 AS FLOAT64)
         WHEN l.address_code = r.address_code OR l.address__address = r.address__address
           THEN w.address[OFFSET(4)]  -- same address
         ELSE GREATEST(w.address[OFFSET(1)],  -- else
                       IF(l.address__address IS NOT NULL AND r.address__address IS NOT NULL
                          AND ABS(LENGTH(l.address__address) - LENGTH(r.address__address)) <= 2,
                          w.address[OFFSET(3)], w.address[OFFSET(1)]),  -- address close, within two characters' length
                       IF(l.postal_code = r.postal_code, w.address[OFFSET(2)], w.address[OFFSET(1)]))  -- same postal
         END
  + w.phone[OFFSET(gamma_phone(l, r) + 1)] + w.cif[OFFSET(gamma_cif(l, r) + 1)] + w.birth[OFFSET(gamma_birth(l, r) + 1)]
);


-- 4. The gate. A block of @oversized records or more is joined only if a sample of its pairs holds a pair with
--    @search_floor points or more. The sample pairs the block's first @oversized batch records, by hash, with its
--    first @oversized records. It leaves out the pairs another block already listed, and it is scored as the run
--    scores. A big block holds few true matches, and a placeholder's block (a dummy phone, say) holds none.
CREATE OR REPLACE TEMP TABLE gate_pairs AS
WITH ranked AS (
  SELECT b.g, b.k, b.id, b.new,
         ROW_NUMBER() OVER (PARTITION BY b.g, b.k ORDER BY er_hash(b.id)) AS rank,
         IF(b.new, ROW_NUMBER() OVER (PARTITION BY b.g, b.k, b.new ORDER BY er_hash(b.id)), NULL) AS new_rank
  FROM key_blocks AS b WHERE b.n >= @oversized
)
SELECT DISTINCT a.g, a.k, LEAST(a.id, c.id) AS l, GREATEST(a.id, c.id) AS r
FROM ranked AS a JOIN ranked AS c ON a.g = c.g AND a.k = c.k AND a.id <> c.id
WHERE a.new_rank <= @oversized AND c.rank <= @oversized
  AND NOT EXISTS (SELECT 1 FROM listed AS x WHERE x.l = LEAST(a.id, c.id) AND x.r = GREATEST(a.id, c.id));

CREATE OR REPLACE TABLE gated AS
WITH scored_sample AS (
  SELECT p.l, p.r,
         weight_of(gamma_name(x, y), gamma_company(x, y), gamma_address(x, y), gamma_phone(x, y), gamma_cif(x, y),
                   gamma_birth(x, y), w) AS w
  FROM (SELECT DISTINCT l, r FROM gate_pairs) AS p JOIN compared AS x ON x.id = p.l JOIN compared AS y ON y.id = p.r
  CROSS JOIN weights AS w
  -- The bound adds the same bits as the score, in another order, so rounding can leave an exact bound a hair under
  -- the score. The margin keeps such a pair.
  WHERE bound_of(x, y, w) >= @search_floor - CAST(0.000000001 AS FLOAT64)
),
stats AS (
  SELECT p.g, p.k, COUNT(*) AS sampled, MAX(s.w) AS best, COUNT(CASE WHEN s.w >= @search_floor THEN 1 END) AS hits
  FROM gate_pairs AS p LEFT JOIN scored_sample AS s USING (l, r) GROUP BY p.g, p.k
)
SELECT z.g, z.k AS value, z.n AS records, DIV(z.n * (z.n - 1), 2) AS pairs,
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
SELECT l, r, c.sources, p.rule FROM cands AS c FULL JOIN batch_rule_pairs AS p USING (l, r);

CREATE OR REPLACE TEMP TABLE batch_scored AS
WITH kept AS (  -- kept computes the names' Jaro–Winkler (s_name) once for each pair the bound keeps
  SELECT p.l, p.r, p.sources, p.rule, x, y, name_score(x, y) AS s_name
  FROM batch_pairs AS p JOIN compared AS x ON x.id = p.l JOIN compared AS y ON y.id = p.r CROSS JOIN weights AS w
  -- The margin keeps a pair whose bound rounds a hair under its score, as the gate's does.
  WHERE p.rule IS NOT NULL OR bound_of(x, y, w) >= @keep_from - CAST(0.000000001 AS FLOAT64)
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
  CASE WHEN match_weight >= 0 THEN CAST(1 AS FLOAT64) / (CAST(1 AS FLOAT64) + POWER(CAST(2 AS FLOAT64), -match_weight))
       ELSE POWER(CAST(2 AS FLOAT64), match_weight) / (CAST(1 AS FLOAT64) + POWER(CAST(2 AS FLOAT64), match_weight))
  END AS match_probability,
  sources, rule, (gamma_name >= 0 OR gamma_company >= 0) AS named,
  gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth
FROM weighed
WHERE match_weight >= @keep_from OR rule IS NOT NULL;

CREATE TABLE IF NOT EXISTS scored AS SELECT * FROM batch_scored WHERE FALSE;

INSERT INTO scored SELECT * FROM batch_scored;
