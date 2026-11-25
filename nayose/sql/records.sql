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
-- Values: config.toml's [records], and the patterns that nayose builds from its lists (legal_pattern,
--   prefecture_pattern). With @lookup, the batch holds the records asked about (nayose.lookup). They are prepared
--   as the run's own records are, but none of their values becomes a placeholder, and every table is written as a
--   temporary table.
-- Writes:
--   set_aside, the batch's rows that are set aside, each with its reason;
--   placeholders, the run's placeholders and the new ones this batch brings;
--   records, one row per record with its fields, its kind, its copies and its batch.


-- 0. The run's records and placeholders start empty. This batch's number is one more than the last batch's, or 0 for
--    the run's first.
CREATE TABLE IF NOT EXISTS records (
  id STRING, given_name STRING, any_name STRING, address STRING, address_code STRING, postal_code STRING,
  prefecture STRING, town_code STRING, city STRING, phone STRING, customer_id STRING, birth_date STRING,
  kind INT64, kind_p FLOAT64, kind_by STRING, kind_flagged BOOL, full_name STRING, person_name STRING,
  company_name STRING, person_name__kana_fold STRING, company_name__nfkc_strip_legal_form_kana_fold STRING,
  address__address STRING, postal_code__first3 STRING, any_name__initial STRING, given_name__kana_fold STRING,
  address__address_first3 STRING,
  person_name__kana_fold_long_vowel STRING, person_name__kana_fold_one_byte STRING,
  company_name__nfkc_strip_legal_form_kana_fold_one_byte STRING, address__address_one_byte_hash STRING,
  person_name__kana_fold_long_vowel_last3 STRING, person_name__kana_fold_letters_lo INT64,
  person_name__kana_fold_letters_hi INT64, batch INT64
) CLUSTER BY id;  -- On BigQuery, a lookup by ID then reads only the blocks that hold those IDs.

CREATE TABLE IF NOT EXISTS placeholders (field STRING, value STRING, n INT64);

CREATE OR REPLACE TEMP TABLE this_batch AS SELECT COALESCE(MAX(batch) + 1, 0) AS batch FROM records;


-- 1. This section sets aside the rows that can't be resolved. Rows identical in every column count once (mapping.sql's
--    input_rows). A row is set aside if it has no ID, if its ID is already in the run, or if another row gives
--    its ID with different content. An ID that is empty or whitespace alone, as Python counts whitespace, is no ID.
--    Since an ID already in the run is set aside, a batch given twice adds nothing the second time. Every row of
--    an ID with different content is set aside, because the run can't tell which row is right.
--    The list of IDs held twice leaves out a missing ID, because a NULL in a NOT IN list fails the test for every row.

CREATE OR REPLACE TABLE set_aside AS
SELECT * EXCEPT (nayose_id),
  CASE WHEN nayose_id IS NULL OR blank(nayose_id) THEN 'no ID'
       WHEN nayose_id IN (SELECT id FROM records) THEN 'already in the run'
       ELSE 'the same ID with different content' END AS reason
FROM input_rows
WHERE nayose_id IS NULL
   OR blank(nayose_id)
   OR nayose_id IN (SELECT id FROM records)
   OR nayose_id IN (SELECT nayose_id FROM input_rows WHERE nayose_id IS NOT NULL
                    GROUP BY nayose_id HAVING COUNT(*) > 1);


-- 2. Each field is standardized by its chain of steps, in order. A value that its chain leaves empty is missing.
--    nfkc applies Unicode NFKC normalization.
--    katakana writes hiragana as katakana (@hiragana to @katakana).
--    strip_spaces removes every space, of any width.
--    strip_separators removes what people write between digits, as in 03-1234-5678 or (03) 1234-5678. These are
--    spaces, hyphens, dashes, minus signs, the long-vowel mark ー, slashes, dots, parentheses and 〒.
--    strip_legal_form removes a legal form (@legal_pattern).
--    kana_fold writes voiced kana as unvoiced, small kana as large, and ー as ウ (@kana_fold_from to @kana_fold_to).

CREATE OR REPLACE TEMP TABLE standardized AS
WITH kept AS (  -- Each record that isn't set aside is kept once.
  SELECT DISTINCT m.*
  FROM mapped AS m
  WHERE m.id IS NOT NULL
    AND NOT blank(m.id)
    AND m.id NOT IN (SELECT id FROM records)
    AND m.id NOT IN (SELECT nayose_id FROM input_rows WHERE nayose_id IS NOT NULL
                     GROUP BY nayose_id HAVING COUNT(*) > 1)
)
SELECT
  id,
  NULLIF(REGEXP_REPLACE(TRANSLATE(nfkc(full_name), @hiragana, @katakana), r'[\s\x{3000}]+', ''), '') AS full_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(nfkc(person_name), @hiragana, @katakana), r'[\s\x{3000}]+', ''), '') AS person_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(nfkc(given_name), @hiragana, @katakana), r'[\s\x{3000}]+', ''), '') AS given_name,
  NULLIF(REGEXP_REPLACE(TRANSLATE(nfkc(company_name), @hiragana, @katakana), r'[\s\x{3000}]+', ''), '') AS company_name,
  NULLIF(TRANSLATE(REGEXP_REPLACE(TRANSLATE(REGEXP_REPLACE(nfkc(any_name), r'[\s\x{3000}]+', ''), @hiragana, @katakana),
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
  any_name AS kind_name  -- Section 3 looks for a legal form in this name as written.
FROM kept;


-- sided holds each record once, with its kind (section 3) and its names in the fields of its side (section 4).
CREATE OR REPLACE TEMP TABLE sided AS
-- 3. Each record's kind is 2 for a company, 1 for a person, or 0 if neither the engine nor the file's flag decides.
--    A legal form written in the name makes the record a company.
--    Otherwise the name model decides if it is at least name_line sure either way. The model is a logistic regression
--    on the character n-grams of the name as any_name holds it, in lower case. A name that reads as a person's never
--    overrides a flag that says company.
--    Otherwise the file's flag (kind_flag) decides. A flag in flag_company says company, and any other says person.
--    With trust_flag, the flag decides every record.
--    A record's side is its kind, or, if its kind is 0, the kind it leans to (kind_p).
-- name_sums scores each distinct name once, since many records share a name: one row per distinct name. As in the
-- model's training, each n-gram counts once however often the name holds it, and an n-gram the model doesn't know
-- adds nothing.
WITH name_sums AS (
  SELECT g.t, SUM(w.w) AS s
  FROM (
    SELECT DISTINCT t, SUBSTR(t, i, n) AS term
    FROM (SELECT DISTINCT LOWER(any_name) AS t FROM standardized WHERE any_name IS NOT NULL),
      UNNEST(GENERATE_ARRAY(1, @ngram)) AS n,
      UNNEST(GENERATE_ARRAY(1, LENGTH(t) - n + 1)) AS i
  ) AS g
  JOIN name_weights AS w ON w.term = g.term
  GROUP BY g.t
),
-- judged and each CTE after it hold one row per record. written is TRUE if the name as written holds a legal form.
-- logit is the name model's log-odds that the name is a company's. flag is the file's flag as a kind: 2 company,
-- 1 person, or NULL if the file gives none.
judged AS (
  SELECT
    s.*,
    COALESCE(REGEXP_CONTAINS(NULLIF(TRANSLATE(REGEXP_REPLACE(nfkc(kind_name), r'[\s\x{3000}]+', ''), @hiragana, @katakana), ''),
                             @legal_pattern), FALSE) AS written,
    IF(s.any_name IS NULL, NULL, @intercept + COALESCE(n.s, CAST(0 AS FLOAT64))) AS logit,
    CASE WHEN s.kind_flag IS NULL THEN NULL
         WHEN trimmed(nfkc(s.kind_flag))
              IN UNNEST(@flag_company) THEN 2
         ELSE 1 END AS flag
  FROM standardized AS s
  LEFT JOIN name_sums AS n ON n.t = LOWER(s.any_name)
),
name_chance AS (  -- name_p is the chance that the name is a company's, or NULL if the model can read no name.
  -- The logistic takes two forms so that EXP never gets a large argument, which BigQuery refuses as an overflow.
  SELECT *, IF(written, CAST(1 AS FLOAT64),
               IF(logit >= 0, 1 / (1 + EXP(-logit)), EXP(logit) / (1 + EXP(logit)))) AS name_p
  FROM judged
),
sure AS (  -- sure_kind is the engine's kind if the engine is sure (2 company, 1 person), and 0 if it isn't.
  SELECT *,
    -- With @trust_flag the engine is never sure, so the file's flag decides every record.
    CASE WHEN kind_name IS NULL OR @trust_flag THEN 0
         WHEN (written OR name_p >= @name_line) THEN 2
         WHEN name_p <= 1 - @name_line AND flag = 2 THEN 0  -- A person's name never overrides a company flag.
         WHEN name_p <= 1 - @name_line THEN 1
         ELSE 0 END AS sure_kind
  FROM name_chance
),
-- The kind is the engine's if the engine is sure, and the file's flag if it isn't. kind_p is how far the record
-- leans to company, from 0 to 1, or NULL if the record has no name to judge.
decided AS (
  SELECT *,
    CAST(IF(sure_kind <> 0, sure_kind, COALESCE(flag, 0)) AS INT64) AS kind,
    IF(kind_name IS NULL, NULL, IF(@trust_flag, CAST(flag - 1 AS FLOAT64), name_p)) AS kind_p
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
    IF(@shared_name_column AND side <> 'person', NULL, full_name) AS full_name,
    IF(@shared_name_column AND side <> 'person', NULL, person_name) AS person_name,
    IF(@shared_name_column AND side <> 'company', NULL, company_name) AS company_name
  FROM told
),
same AS (
  SELECT *,
    COALESCE(NULLIF(TRANSLATE(full_name, @kana_fold_from, @kana_fold_to), '')
             = NULLIF(TRANSLATE(company_name, @kana_fold_from, @kana_fold_to), ''), FALSE) AS same_full,
    COALESCE(NULLIF(TRANSLATE(person_name, @kana_fold_from, @kana_fold_to), '')
             = NULLIF(TRANSLATE(company_name, @kana_fold_from, @kana_fold_to), ''), FALSE) AS same_person
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
--    the field's bar and at least @crowd customers hold it. The bar is @min_block records, or @spread times the
--    field's records per value if that is more. A crowded value is a placeholder if its own pairs outnumber the pairs
--    that all the field's uncrowded values make together.
--    A customer ID is a placeholder if it reaches its field's bar. Its customers and pairs aren't tested.
--    Blanking one field's placeholder changes no other field's record counts. A person_name placeholder also blanks
--    full_name, given_name and any_name, but those fields aren't counted. Blanking a customer ID would change the
--    customer counts, as a record without one is its own customer. So customers are counted by the customer ID as
--    this section reads it, before any new placeholder blanks it. Every field's placeholders are then found at once,
--    and section 6 blanks them as it writes the records.
--    The run's placeholders stay. The batch is first read with them as missing, and its values are then counted
--    together with the run's records. With @lookup, no placeholder is found.
-- known keeps the run's placeholders from before this batch, since placeholders is replaced below.
CREATE OR REPLACE TEMP TABLE known AS SELECT * FROM placeholders;

CREATE OR REPLACE TEMP TABLE found AS
-- counted holds the run's records and the batch's. The run's records were written with the run's placeholders
-- already blanked, and the batch's values are read here with them as missing.
WITH counted AS (
  SELECT id, person_name, company_name, address_code, address, phone, birth_date, customer_id
  FROM records WHERE NOT @lookup
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
-- field_values lists each record's value of each field, with its customer. A record's customer is its customer ID,
-- or the record's own ID if it has no customer ID.
field_values AS (
  SELECT 'person_name' AS field, person_name AS value, COALESCE(customer_id, id) AS customer FROM counted
  UNION ALL SELECT 'company_name', company_name, COALESCE(customer_id, id) FROM counted
  UNION ALL SELECT 'address_code', address_code, COALESCE(customer_id, id) FROM counted
  UNION ALL SELECT 'address', address, COALESCE(customer_id, id) FROM counted
  UNION ALL SELECT 'phone', phone, COALESCE(customer_id, id) FROM counted
  UNION ALL SELECT 'birth_date', birth_date, COALESCE(customer_id, id) FROM counted
  UNION ALL SELECT 'customer_id', customer_id, NULL FROM counted
),
value_counts AS (  -- Each value's records (n) and customers are counted.
  SELECT field, value, COUNT(*) AS n, COUNT(DISTINCT customer) AS customers
  FROM field_values WHERE value IS NOT NULL GROUP BY field, value
),
-- Each field gets its bar (at_least), and the number of pairs that all its values make together (all_pairs). A value
-- held by n records makes n(n-1)/2 pairs.
field_bars AS (
  SELECT field, GREATEST(@min_block, CAST(CEIL(@spread * SUM(n) / GREATEST(COUNT(*), 1)) AS INT64)) AS at_least,
         SUM(pairs_of(n)) AS all_pairs
  FROM value_counts GROUP BY field
),
crowded AS (  -- A customer ID needs only the bar, as its customers aren't counted.
  SELECT v.field, v.value, v.n FROM value_counts AS v JOIN field_bars AS b USING (field)
  WHERE v.n >= b.at_least AND (v.field = 'customer_id' OR v.customers >= @crowd)
),
crowded_pairs AS (SELECT field, SUM(pairs_of(n)) AS pairs FROM crowded GROUP BY field)
-- A crowded value is a placeholder if its own pairs outnumber those of all the field's values that aren't crowded.
SELECT c.field, c.value, c.n FROM crowded AS c JOIN field_bars AS b USING (field) JOIN crowded_pairs AS p USING (field)
WHERE NOT @lookup AND (c.field = 'customer_id' OR pairs_of(c.n) > b.all_pairs - p.pairs);

CREATE OR REPLACE TABLE placeholders AS
SELECT * FROM known UNION ALL SELECT * FROM found;

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
-- when: EXISTS (SELECT 1 FROM found)
CREATE OR REPLACE TEMP TABLE redone AS
SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
       birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
       company_name, batch
FROM records
WHERE person_name IN (SELECT value FROM found WHERE field = 'person_name')
   OR company_name IN (SELECT value FROM found WHERE field = 'company_name')
   OR address_code IN (SELECT value FROM found WHERE field = 'address_code')
   OR address IN (SELECT value FROM found WHERE field = 'address')
   OR phone IN (SELECT value FROM found WHERE field = 'phone')
   OR birth_date IN (SELECT value FROM found WHERE field = 'birth_date')
   OR customer_id IN (SELECT value FROM found WHERE field = 'customer_id');

-- If the batch found no placeholder, redone is empty, with the same columns, and no record is made again.
-- when: NOT EXISTS (SELECT 1 FROM found)
CREATE OR REPLACE TEMP TABLE redone AS
SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
       birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
       company_name, batch
FROM records WHERE FALSE;

-- The records made again leave the table here, and the INSERT below writes them anew.
-- when: EXISTS (SELECT 1 FROM redone)
DELETE FROM records WHERE id IN (SELECT id FROM redone);

INSERT INTO records
-- made holds the batch's records and the run's records made again, with their fields but not yet their copies.
WITH made AS (
  SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
         birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
         company_name, (SELECT batch FROM this_batch) AS batch
  FROM sided
  UNION ALL
  SELECT id, given_name, any_name, address, address_code, postal_code, prefecture, town_code, city, phone, customer_id,
         birth_date, kind, kind_p, kind_by, kind_flagged, full_name, person_name,
         company_name, batch
  FROM redone
),
-- marked holds the records of made, person_placeholder TRUE if a record's person_name is a placeholder and
-- company_placeholder TRUE if its company_name is.
marked AS (
  SELECT *,
    person_name IN (SELECT value FROM placeholders WHERE field = 'person_name') AS person_placeholder,
    company_name IN (SELECT value FROM placeholders WHERE field = 'company_name') AS company_placeholder
  FROM made
),
-- Every placeholder is read as missing. A person_name placeholder also blanks full_name, given_name and any_name,
-- and a company_name placeholder also blanks any_name, since those fields come from the same columns.
blanked AS (
  SELECT * EXCEPT (person_placeholder, company_placeholder) REPLACE (
    IF(person_placeholder, NULL, full_name) AS full_name,
    IF(person_placeholder, NULL, given_name) AS given_name,
    IF(person_placeholder OR company_placeholder, NULL, any_name) AS any_name,
    IF(person_placeholder, NULL, person_name) AS person_name,
    IF(company_placeholder, NULL, company_name) AS company_name,
    IF(address_code IN (SELECT value FROM placeholders WHERE field = 'address_code'), NULL, address_code) AS address_code,
    IF(address IN (SELECT value FROM placeholders WHERE field = 'address'), NULL, address) AS address,
    IF(phone IN (SELECT value FROM placeholders WHERE field = 'phone'), NULL, phone) AS phone,
    IF(birth_date IN (SELECT value FROM placeholders WHERE field = 'birth_date'), NULL, birth_date) AS birth_date,
    IF(customer_id IN (SELECT value FROM placeholders WHERE field = 'customer_id'), NULL, customer_id) AS customer_id)
  FROM marked
),
copies AS (
  SELECT
    *,
    NULLIF(TRANSLATE(person_name, @kana_fold_from, @kana_fold_to), '') AS person_name__kana_fold,
    NULLIF(TRANSLATE(REGEXP_REPLACE(nfkc(company_name), @legal_pattern, ''), @kana_fold_from, @kana_fold_to), '')
      AS company_name__nfkc_strip_legal_form_kana_fold,
    NULLIF(REGEXP_REPLACE(REPLACE(up_to_street_number(trimmed(numbers_dashed(nfkc(address)))), ' ', ''),
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
    NULLIF(REGEXP_REPLACE(REGEXP_REPLACE(person_name__kana_fold, r'([オコソトノホモヨロ])[ウオ]', r'\1ウ'),
                          r'([エケセテネヘメレ])[イエ]', r'\1イ'), '') AS person_name__kana_fold_long_vowel,
    -- one_byte is the copy that a similarity reads. It is NULL unless the value is katakana alone. Each katakana
    -- becomes a one-byte character of its own (@one_byte), so DuckDB's own similarity functions, which count bytes,
    -- compare it character by character. BigQuery's JavaScript functions give the copy the same scores.
    IF(REGEXP_CONTAINS(person_name__kana_fold, r'^[\x{30a0}-\x{30ff}]+$'), TRANSLATE(person_name__kana_fold, @katakana_block, @one_byte), NULL)
      AS person_name__kana_fold_one_byte,
    IF(REGEXP_CONTAINS(company_name__nfkc_strip_legal_form_kana_fold, r'^[\x{30a0}-\x{30ff}]+$'),
       TRANSLATE(company_name__nfkc_strip_legal_form_kana_fold, @katakana_block, @one_byte), NULL)
      AS company_name__nfkc_strip_legal_form_kana_fold_one_byte,
    -- one_byte_hash is the copy that an edit distance reads. It is NULL if the value is ASCII alone, which needs no
    -- copy. Each character becomes one byte, chosen by its code point, and two characters may share a byte. So the
    -- copies are never farther apart than the values, and their distance, which DuckDB computes natively, is a cheap
    -- lower bound on the values' distance (functions.sql).
    IF(REGEXP_CONTAINS(address__address, r'[^\x00-\x7f]'), one_byte_hash(address__address), NULL) AS address__address_one_byte_hash
  FROM copies
),
lettered AS (
  -- letters is the set of katakana a name holds, as two bit masks over its one-byte copy's codes. lo covers codes
  -- 1–63, and hi covers codes 64–96. One pass over the name makes both. name_jw_most (functions.sql) bounds the
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
  batch
FROM lettered;
