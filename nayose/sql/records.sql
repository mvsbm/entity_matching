-- Stage 1, records: a batch of input records added to the run's, set aside where they can't be resolved, each field
-- standardized, each record's kind told, placeholders read as missing, and the copies the keys and comparisons read.
-- A build is a run's first batch. O(Δ·L) for a batch of Δ, plus O(N) to count placeholders over all the run's records.
--
-- Reads: input_rows and mapped (mapping.sql: the batch), name_weights (the name model, config/kind_names.npz), the
-- run's records and placeholders (none before its first batch).
-- Writes: this_batch (its number), set_aside (the batch's rows set aside, with the reason), placeholders (each
-- field's values read as missing: the run's, and those the batch's records bring past the line), records (a record a
-- row: its fields, its kind, the copies, its batch). @lookup: the batch is records asked about, prepared as the run
-- prepares its own, and nothing it holds is a placeholder of the run's (nayose.lookup, in temporary tables).
-- Values: config.toml [records], and the patterns nayose builds from its lists (legal_pattern, prefecture_pattern).


-- 0. The run's records and placeholders: none before its first batch. This batch's number: one past the last.
CREATE TABLE IF NOT EXISTS records (
  id STRING, given_name STRING, any_name STRING, address STRING, address_code STRING, postal_code STRING, prefecture STRING,
  town_code STRING, city STRING, phone STRING, customer_id STRING, birth_date STRING, kind_flag STRING, kind_name STRING,
  kind INT64, kind_p FLOAT64, kind_by STRING, name_p FLOAT64, kind_flagged BOOL, full_name STRING, person_name STRING,
  company_name STRING, person_name__kana_fold STRING, company_name__nfkc_strip_legal_form_kana_fold STRING,
  address__address STRING, postal_code__first3 STRING, any_name__initial STRING, given_name__kana_fold STRING,
  address__address_first3 STRING, person_name__kana_fold_long_vowel STRING, person_name__kana_fold_one_byte STRING,
  company_name__nfkc_strip_legal_form_kana_fold_one_byte STRING, address__address_one_byte_hash STRING,
  person_name__kana_fold_long_vowel_last3 STRING, person_name__kana_fold_letters_lo INT64, person_name__kana_fold_letters_hi INT64,
  batch INT64
) CLUSTER BY id;  -- a lookup reads its records by ID: on BigQuery, only the blocks that hold them

CREATE TABLE IF NOT EXISTS placeholders (field STRING, value STRING, n INT64);

CREATE OR REPLACE TABLE this_batch AS SELECT COALESCE(MAX(batch) + 1, 0) AS batch FROM records;


-- 1. Set aside what can't be resolved. Rows identical in every column are kept once (mapping.sql's input_rows). A
--    record without an ID (blank: whitespace alone, as Python counts it), a record already in the run (a batch given
--    twice adds nothing twice), and every record of an ID holding different content, are set aside.

CREATE OR REPLACE TABLE set_aside AS
SELECT * EXCEPT (nayose_id),
  CASE WHEN nayose_id IS NULL OR blank(nayose_id) THEN 'no ID'
       WHEN nayose_id IN (SELECT id FROM records) THEN 'already in the run'
       ELSE 'the same ID with different content' END AS reason
FROM input_rows
WHERE nayose_id IS NULL
   OR blank(nayose_id)
   OR nayose_id IN (SELECT id FROM records)
   OR nayose_id IN (SELECT nayose_id FROM input_rows GROUP BY nayose_id HAVING COUNT(*) > 1);

CREATE OR REPLACE TEMP TABLE kept AS
SELECT DISTINCT m.*
FROM mapped AS m
WHERE m.id IS NOT NULL
  AND NOT blank(m.id)
  AND m.id NOT IN (SELECT id FROM records)
  AND m.id NOT IN (SELECT nayose_id FROM input_rows GROUP BY nayose_id HAVING COUNT(*) > 1);


-- 2. Each field standardized by its chain of steps, in order; a value the chain leaves empty is missing.
--    nfkc: Unicode NFKC. katakana: hiragana as katakana. strip_spaces: every space gone (any width).
--    strip_separators: what people write between digits (03-1234-5678, 1993/05/25). strip_legal_form: a legal form
--    gone. kana_fold: voiced → unvoiced, small → large.

CREATE OR REPLACE TEMP TABLE standardized AS
SELECT
  id,
  NULLIF(REGEXP_REPLACE(TRANSLATE(nfkc(full_name), @hiragana, @katakana), r'[\s\x{3000}]+', ''), '') AS full_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(nfkc(person_name), @hiragana, @katakana), r'[\s\x{3000}]+', ''), '') AS person_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(nfkc(given_name), @hiragana, @katakana), r'[\s\x{3000}]+', ''), '') AS given_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(nfkc(company_name), @hiragana, @katakana), r'[\s\x{3000}]+', ''), '') AS company_name,
  NULLIF(TRANSLATE(REGEXP_REPLACE(TRANSLATE(nfkc(REGEXP_REPLACE(any_name, r'[\s\x{3000}]+', '')), @hiragana, @katakana),
                                  @legal_pattern, ''), @kana_fold_from, @kana_fold_to), '') AS any_name,
  NULLIF(address, '') AS address,
  NULLIF(address_code, '') AS address_code,
  NULLIF(REGEXP_REPLACE(nfkc(postal_code), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '') AS postal_code,
  NULLIF(prefecture, '') AS prefecture,
  NULLIF(town_code, '') AS town_code,
  NULLIF(city, '') AS city,
  NULLIF(REGEXP_REPLACE(nfkc(phone), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '') AS phone,
  NULLIF(REGEXP_REPLACE(nfkc(customer_id), r'[\s\x{3000}\-\x{2010}-\x{2015}\x{2212}\x{30fc}/.()〒]', ''), '') AS customer_id,
  NULLIF(birth_date, '') AS birth_date,
  NULLIF(kind_flag, '') AS kind_flag,
  any_name AS kind_name  -- the name as written, its legal form still in it: what kind is told from
FROM kept;


-- 3. Each record's kind: 2 company, 1 person, 0 not sure.
--    A written legal form says company. Else the name model (logistic regression on the name's character n-grams,
--    the name as any_name reads it, lower case) is sure past name_line either way, but a person's name never
--    overrides a company flag. Else the file's flag (kind_flag; flag_company's values say company). With
--    trust_flag, the flag decides every record.

CREATE OR REPLACE TEMP TABLE name_sums AS  -- each distinct name once: many records share one
SELECT g.t, SUM(w.w) AS s
FROM (
  SELECT DISTINCT t, SUBSTR(t, i, n) AS term
  FROM (SELECT DISTINCT LOWER(any_name) AS t FROM standardized WHERE any_name IS NOT NULL),
    UNNEST(GENERATE_ARRAY(1, @ngram)) AS n,
    UNNEST(GENERATE_ARRAY(1, LENGTH(t) - n + 1)) AS i
) AS g
JOIN name_weights AS w ON w.term = g.term
GROUP BY g.t;

CREATE OR REPLACE TEMP TABLE told AS
WITH judged AS (
  SELECT
    s.*,
    COALESCE(REGEXP_CONTAINS(NULLIF(TRANSLATE(nfkc(REGEXP_REPLACE(kind_name, r'[\s\x{3000}]+', '')), @hiragana, @katakana), ''),
                             @legal_pattern), FALSE) AS written,
    IF(s.any_name IS NULL, NULL, @intercept + COALESCE(n.s, CAST(0 AS FLOAT64))) AS logit,
    CASE WHEN s.kind_flag IS NULL THEN NULL
         WHEN trimmed(nfkc(s.kind_flag))
              IN UNNEST(@flag_company) THEN 2
         ELSE 1 END AS flag
  FROM standardized AS s
  LEFT JOIN name_sums AS n ON n.t = LOWER(s.any_name)
),
scored AS (
  SELECT *, IF(written, CAST(1 AS FLOAT64), 1 / (1 + EXP(-logit))) AS name_p  -- NULL: no name the model can read
  FROM judged
),
sure AS (
  SELECT *,
    CASE WHEN kind_name IS NULL OR @trust_flag THEN 0
         WHEN (written OR name_p >= @name_line) THEN 2
         WHEN name_p <= 1 - @name_line AND flag = 2 THEN 0  -- a person's name never overrides a company flag
         WHEN name_p <= 1 - @name_line THEN 1
         ELSE 0 END AS sure_kind
  FROM scored
)
SELECT
  * EXCEPT (written, logit, flag, name_p, sure_kind),
  CAST(IF(sure_kind <> 0, sure_kind, COALESCE(flag, 0)) AS INT64) AS kind,
  IF(kind_name IS NULL, NULL, IF(@trust_flag, CAST(flag - 1 AS FLOAT64), name_p)) AS kind_p,  -- NULL: no name to judge
  IF(sure_kind = 0 AND flag IS NOT NULL, 'flag', 'engine') AS kind_by,
  name_p,
  (sure_kind <> 0 AND flag IS NOT NULL AND sure_kind <> flag) AS kind_flagged,
  -- the side a name goes to: its kind; not sure, where it leans
  CASE WHEN IF(sure_kind <> 0, sure_kind, COALESCE(flag, 0)) = 2 THEN 'company'
       WHEN IF(sure_kind <> 0, sure_kind, COALESCE(flag, 0)) = 1 THEN 'person'
       WHEN IF(@trust_flag, CAST(flag - 1 AS FLOAT64), name_p) >= CAST(0.5 AS FLOAT64) THEN 'company'
       ELSE 'person' END AS side
FROM sure;


-- 4. One name, two fields: a column holding every name, mapped to a person field and the company field alike, is
--    one piece of evidence, kept on its kind's side only. With shared_name_column, a person field keeps a name only
--    where the record leans person, the company field only where it leans company.

CREATE OR REPLACE TEMP TABLE sided AS
WITH routed AS (
  SELECT
    * EXCEPT (full_name, person_name, company_name),
    IF(@shared_name_column AND side <> 'person', NULL, full_name) AS full_name,
    IF(@shared_name_column AND side <> 'person', NULL, person_name) AS person_name,
    IF(@shared_name_column AND side <> 'company', NULL, company_name) AS company_name
  FROM told
),
same AS (
  SELECT *,
    COALESCE(NULLIF(TRANSLATE(full_name, @kana_fold_from, @kana_fold_to), '') = NULLIF(TRANSLATE(company_name, @kana_fold_from, @kana_fold_to), ''), FALSE) AS same_full,
    COALESCE(NULLIF(TRANSLATE(person_name, @kana_fold_from, @kana_fold_to), '') = NULLIF(TRANSLATE(company_name, @kana_fold_from, @kana_fold_to), ''), FALSE) AS same_person
  FROM routed
)
SELECT
  * EXCEPT (full_name, person_name, company_name, same_full, same_person),
  IF(same_full AND side = 'company', NULL, full_name) AS full_name,
  IF(same_person AND side = 'company', NULL, person_name) AS person_name,
  IF((same_full OR same_person) AND side = 'person', NULL, company_name) AS company_name
FROM same;


-- 5. Placeholders: a value held by so many records that it can't be one entity's, or evidence, read as missing.
--    A compared field's value is one if it is held by at least `at` records (min_block, or spread times the field's
--    records per value if more) and by at least `crowd` customers, and its pairs outnumber those of every value held
--    by fewer. The customer ID's, if held by `at` records. No field's blanking changes another's counts (a name blanked
--    blanks only the fields built from its columns, and customers are counted by the customer ID, blanked as the
--    others are read), so all are found at once, and blanked as the records are written (6). The run's placeholders
--    stay, read as missing in the batch first; the counts are of the run's records and the batch's together.
CREATE OR REPLACE TEMP TABLE known AS SELECT * FROM placeholders;

CREATE OR REPLACE TEMP TABLE found AS
WITH every AS (
  SELECT id, person_name, company_name, address_code, address, phone, birth_date, customer_id FROM records WHERE NOT @lookup
  UNION ALL
  SELECT id,
    IF(person_name IN (SELECT value FROM known WHERE field = 'person_name'), NULL, person_name),
    IF(company_name IN (SELECT value FROM known WHERE field = 'company_name'), NULL, company_name),
    IF(address_code IN (SELECT value FROM known WHERE field = 'address_code'), NULL, address_code),
    IF(address IN (SELECT value FROM known WHERE field = 'address'), NULL, address),
    IF(phone IN (SELECT value FROM known WHERE field = 'phone'), NULL, phone),
    IF(birth_date IN (SELECT value FROM known WHERE field = 'birth_date'), NULL, birth_date),
    IF(customer_id IN (SELECT value FROM known WHERE field = 'customer_id'), NULL, customer_id)
  FROM sided
),
v AS (
  SELECT 'person_name' AS field, person_name AS value, COALESCE(customer_id, id) AS who FROM every
  UNION ALL SELECT 'company_name', company_name, COALESCE(customer_id, id) FROM every
  UNION ALL SELECT 'address_code', address_code, COALESCE(customer_id, id) FROM every
  UNION ALL SELECT 'address', address, COALESCE(customer_id, id) FROM every
  UNION ALL SELECT 'phone', phone, COALESCE(customer_id, id) FROM every
  UNION ALL SELECT 'birth_date', birth_date, COALESCE(customer_id, id) FROM every
  UNION ALL SELECT 'customer_id', customer_id, NULL FROM every
),
c AS (SELECT field, value, COUNT(*) AS n, COUNT(DISTINCT who) AS who FROM v WHERE value IS NOT NULL GROUP BY field, value),
s AS (SELECT field, GREATEST(@min_block, CAST(CEIL(@spread * SUM(n) / GREATEST(COUNT(*), 1)) AS INT64)) AS at_least,
             SUM(DIV(n * (n - 1), 2)) AS every FROM c GROUP BY field),
held AS (SELECT c.field, c.value, c.n FROM c JOIN s USING (field) WHERE c.n >= s.at_least AND (c.field = 'customer_id' OR c.who >= @crowd)),
held_pairs AS (SELECT field, SUM(DIV(n * (n - 1), 2)) AS pairs FROM held GROUP BY field)
SELECT h.field, h.value, h.n FROM held AS h JOIN s USING (field) JOIN held_pairs AS p USING (field)
WHERE NOT @lookup AND (h.field = 'customer_id' OR DIV(h.n * (h.n - 1), 2) > s.every - p.pairs);

CREATE OR REPLACE TABLE placeholders AS
SELECT * FROM known UNION ALL SELECT * FROM found;

-- 6. The copies the keys and comparisons read, each a chain of steps from a field, and the records: the run's, and the
--    batch's. A run's record holding a placeholder the batch found is made again with it read as missing, its copies too.
--    address: NFKC; 丁目, 番地 and 号 as dashes; the building and room after the first space past the street number
--    gone, then every space; the address's own prefecture off its start. first3, initial, last3: a key's start or
--    end. long_vowel: a long vowel written either way (サトウ, サトオ, サトー) as one reading.

-- when: EXISTS (SELECT 1 FROM found)
CREATE OR REPLACE TEMP TABLE redone AS  -- the run's records a placeholder the batch found is held by
SELECT id FROM records
WHERE person_name IN (SELECT value FROM found WHERE field = 'person_name')
   OR company_name IN (SELECT value FROM found WHERE field = 'company_name')
   OR address_code IN (SELECT value FROM found WHERE field = 'address_code')
   OR address IN (SELECT value FROM found WHERE field = 'address')
   OR phone IN (SELECT value FROM found WHERE field = 'phone')
   OR birth_date IN (SELECT value FROM found WHERE field = 'birth_date')
   OR customer_id IN (SELECT value FROM found WHERE field = 'customer_id');

-- when: NOT EXISTS (SELECT 1 FROM found)
CREATE OR REPLACE TEMP TABLE redone AS SELECT id FROM records WHERE FALSE;  -- no placeholder found: no record made again, none read

-- when: EXISTS (SELECT 1 FROM redone)
CREATE OR REPLACE TEMP TABLE redone_fields AS  -- their fields, before the copies: made again with the batch's, below
SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
       birth_date, kind_flag, kind_name, kind, kind_p, kind_by, name_p, kind_flagged, full_name, person_name, company_name, batch
FROM records WHERE id IN (SELECT id FROM redone);

-- when: NOT EXISTS (SELECT 1 FROM redone)
CREATE OR REPLACE TEMP TABLE redone_fields AS  -- the same columns, none read
SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
       birth_date, kind_flag, kind_name, kind, kind_p, kind_by, name_p, kind_flagged, full_name, person_name, company_name, batch
FROM records WHERE FALSE;

-- when: EXISTS (SELECT 1 FROM redone)
DELETE FROM records WHERE id IN (SELECT id FROM redone);

INSERT INTO records
WITH made AS (  -- the batch's records, and the run's made again: their fields, before the copies
  SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
         birth_date, kind_flag, kind_name, kind, kind_p, kind_by, name_p, kind_flagged, full_name, person_name, company_name,
         (SELECT batch FROM this_batch) AS batch
  FROM sided
  UNION ALL
  SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
         birth_date, kind_flag, kind_name, kind, kind_p, kind_by, name_p, kind_flagged, full_name, person_name, company_name, batch
  FROM redone_fields
),
blanked AS (  -- the placeholders read as missing: a name in person_name with full_name, given_name and any_name
  SELECT * REPLACE (
    IF(person_name IN (SELECT value FROM placeholders WHERE field = 'person_name'), NULL, full_name) AS full_name,
    IF(person_name IN (SELECT value FROM placeholders WHERE field = 'person_name'), NULL, given_name) AS given_name,
    IF(person_name IN (SELECT value FROM placeholders WHERE field = 'person_name')
       OR company_name IN (SELECT value FROM placeholders WHERE field = 'company_name'), NULL, any_name) AS any_name,
    IF(person_name IN (SELECT value FROM placeholders WHERE field = 'person_name'), NULL, person_name) AS person_name,
    IF(company_name IN (SELECT value FROM placeholders WHERE field = 'company_name'), NULL, company_name) AS company_name,
    IF(address_code IN (SELECT value FROM placeholders WHERE field = 'address_code'), NULL, address_code) AS address_code,
    IF(address IN (SELECT value FROM placeholders WHERE field = 'address'), NULL, address) AS address,
    IF(phone IN (SELECT value FROM placeholders WHERE field = 'phone'), NULL, phone) AS phone,
    IF(birth_date IN (SELECT value FROM placeholders WHERE field = 'birth_date'), NULL, birth_date) AS birth_date,
    IF(customer_id IN (SELECT value FROM placeholders WHERE field = 'customer_id'), NULL, customer_id) AS customer_id)
  FROM made
),
copies AS (
  SELECT
    *,
    NULLIF(TRANSLATE(person_name, @kana_fold_from, @kana_fold_to), '') AS person_name__kana_fold,
    NULLIF(TRANSLATE(REGEXP_REPLACE(nfkc(company_name), @legal_pattern, ''), @kana_fold_from, @kana_fold_to), '') AS company_name__nfkc_strip_legal_form_kana_fold,
    NULLIF(REGEXP_REPLACE(
      REPLACE(
        REGEXP_REPLACE(
          trimmed(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(nfkc(address), r'(\d+)丁目', r'\1-'), r'(\d+)番地?', r'\1-'), r'(\d+)号', r'\1')),
          r'^(.*?[0-9][^ ]*) .*$', r'\1'),
        ' ', ''),
      @prefecture_pattern, ''), '') AS address__address,
    NULLIF(SUBSTR(postal_code, 1, 3), '') AS postal_code__first3,
    NULLIF(SUBSTR(any_name, 1, 1), '') AS any_name__initial,
    NULLIF(TRANSLATE(given_name, @kana_fold_from, @kana_fold_to), '') AS given_name__kana_fold
  FROM blanked
),
readings AS (
  SELECT
    *,
    NULLIF(SUBSTR(address__address, 1, 3), '') AS address__address_first3,
    NULLIF(REGEXP_REPLACE(REGEXP_REPLACE(person_name__kana_fold, r'([オコソトノホモヨロ])[ウオ]', r'\1ウ'), r'([エケセテネヘメレ])[イエ]', r'\1イ'), '') AS person_name__kana_fold_long_vowel,
    -- one_byte: a copy a similarity reads, when it is katakana alone: each character one byte of its own (@one_byte), so
    -- DuckDB's own similarity, which counts bytes, compares it as characters; JavaScript's scores it alike. Else none.
    IF(REGEXP_CONTAINS(person_name__kana_fold, r'^[\x{30a0}-\x{30ff}]+$'), TRANSLATE(person_name__kana_fold, @katakana_block, @one_byte), NULL)
      AS person_name__kana_fold_one_byte,
    IF(REGEXP_CONTAINS(company_name__nfkc_strip_legal_form_kana_fold, r'^[\x{30a0}-\x{30ff}]+$'),
       TRANSLATE(company_name__nfkc_strip_legal_form_kana_fold, @katakana_block, @one_byte), NULL) AS company_name__nfkc_strip_legal_form_kana_fold_one_byte,
    -- one_byte_hash: a copy an edit distance reads, when it isn't ASCII: each character a byte by its code point (two
    -- may share one), so the copies are never farther apart than the strings, and DuckDB finds that natively. Else none.
    IF(REGEXP_CONTAINS(address__address, r'[^\x00-\x7f]'), one_byte_hash(address__address), NULL) AS address__address_one_byte_hash
  FROM copies
),
lettered AS (
  -- letters: the katakana a name holds, as bits of its one-byte copy's codes (1–63, 64–96), read in one pass: what
  -- name_jw_most (functions.sql) bounds its Jaro–Winkler by
  SELECT *, (SELECT STRUCT(COALESCE(BIT_OR(IF(UNICODE(c) < 64, CAST(1 AS INT64) << (UNICODE(c) - 1), 0)), 0) AS lo,
                           COALESCE(BIT_OR(IF(UNICODE(c) >= 64, CAST(1 AS INT64) << (UNICODE(c) - 64), 0)), 0) AS hi)
             FROM UNNEST(SPLIT(person_name__kana_fold_one_byte, '')) AS c) AS letters
  FROM readings
)
SELECT
  id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id, birth_date,
  kind_flag, kind_name, kind, kind_p, kind_by, name_p, kind_flagged, full_name, person_name, company_name, person_name__kana_fold,
  company_name__nfkc_strip_legal_form_kana_fold, address__address, postal_code__first3, any_name__initial, given_name__kana_fold,
  address__address_first3, person_name__kana_fold_long_vowel, person_name__kana_fold_one_byte,
  company_name__nfkc_strip_legal_form_kana_fold_one_byte, address__address_one_byte_hash,
  NULLIF(SUBSTR(person_name__kana_fold_long_vowel, -3), '') AS person_name__kana_fold_long_vowel_last3,
  IF(person_name__kana_fold_one_byte IS NULL, NULL, letters.lo) AS person_name__kana_fold_letters_lo,
  IF(person_name__kana_fold_one_byte IS NULL, NULL, letters.hi) AS person_name__kana_fold_letters_hi,
  batch
FROM lettered;
