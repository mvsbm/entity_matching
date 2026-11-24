-- Stage 1, records: the input's records, set aside where they can't be resolved, each field standardized, each
-- record's kind told, placeholders read as missing, and the copies the keys and comparisons read. O(N·L).
--
-- Reads: input_rows and mapped (mapping.sql), name_weights (the name model, config/kind_names.npz).
-- Writes: set_aside (the rows set aside, with the reason), placeholders (each field's values read as missing),
-- records (a record a row: its fields, its kind, the copies).
-- Values: config.toml [records], and the patterns nayose builds from its lists (legal_pattern, prefecture_pattern).


-- 1. Set aside what can't be resolved. Rows identical in every column are kept once. A record without an ID (blank:
--    whitespace alone, as Python counts it), and every record of an ID holding different content, are set aside.

CREATE OR REPLACE TEMP TABLE distinct_rows AS
SELECT DISTINCT * FROM input_rows;

CREATE OR REPLACE TABLE set_aside AS
SELECT * EXCEPT (nayose_id),
  CASE WHEN nayose_id IS NULL OR REGEXP_CONTAINS(nayose_id, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
       THEN 'no ID' ELSE 'the same ID with different content' END AS reason
FROM distinct_rows
WHERE nayose_id IS NULL
   OR REGEXP_CONTAINS(nayose_id, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
   OR nayose_id IN (SELECT nayose_id FROM distinct_rows GROUP BY nayose_id HAVING COUNT(*) > 1);

CREATE OR REPLACE TEMP TABLE kept AS
SELECT DISTINCT m.*
FROM mapped AS m
WHERE m.id IS NOT NULL
  AND NOT REGEXP_CONTAINS(m.id, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
  AND m.id NOT IN (SELECT nayose_id FROM distinct_rows GROUP BY nayose_id HAVING COUNT(*) > 1);


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

CREATE OR REPLACE TEMP TABLE name_sums AS
SELECT g.id, SUM(w.w) AS s
FROM (
  SELECT DISTINCT id, SUBSTR(t, i, n) AS term
  FROM (SELECT id, LOWER(any_name) AS t FROM standardized WHERE any_name IS NOT NULL),
    UNNEST(GENERATE_ARRAY(1, @ngram)) AS n,
    UNNEST(GENERATE_ARRAY(1, LENGTH(t) - n + 1)) AS i
) AS g
JOIN name_weights AS w ON w.term = g.term
GROUP BY g.id;

CREATE OR REPLACE TEMP TABLE told AS
WITH judged AS (
  SELECT
    s.*,
    COALESCE(REGEXP_CONTAINS(NULLIF(TRANSLATE(nfkc(REGEXP_REPLACE(kind_name, r'[\s\x{3000}]+', '')), @hiragana, @katakana), ''),
                             @legal_pattern), FALSE) AS written,
    IF(s.any_name IS NULL, NULL, @intercept + COALESCE(n.s, CAST(0 AS FLOAT64))) AS logit,
    CASE WHEN s.kind_flag IS NULL THEN NULL
         WHEN REGEXP_REPLACE(nfkc(s.kind_flag), r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]+|[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]+$', '')
              IN UNNEST(@flag_company) THEN 2
         ELSE 1 END AS flag
  FROM standardized AS s
  LEFT JOIN name_sums AS n USING (id)
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
--    by fewer. The customer ID's, if held by `at` records. Field by field, in this order: blanking one changes the
--    counts of the next. A field blanked blanks the fields built from the same columns (a name read into person_name,
--    full_name, given_name and any_name).

CREATE OR REPLACE TEMP TABLE held_person_name AS
WITH c AS (SELECT person_name AS v, COUNT(*) AS n, COUNT(DISTINCT COALESCE(customer_id, id)) AS who FROM sided WHERE person_name IS NOT NULL GROUP BY person_name),
     s AS (SELECT SUM(n) AS filled, COUNT(*) AS values_, SUM(DIV(n * (n - 1), 2)) AS every FROM c),
     t AS (SELECT GREATEST(@min_block, CAST(CEIL(@spread * filled / GREATEST(values_, 1)) AS INT64)) AS at_least FROM s),
     held AS (SELECT v, n FROM c, t WHERE n >= at_least AND who >= @crowd)
SELECT 'person_name' AS field, v AS value, n FROM held, s WHERE DIV(n * (n - 1), 2) > every - (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM held);

UPDATE sided SET person_name = NULL, full_name = NULL, given_name = NULL, any_name = NULL
WHERE person_name IN (SELECT value FROM held_person_name);

CREATE OR REPLACE TEMP TABLE held_company_name AS
WITH c AS (SELECT company_name AS v, COUNT(*) AS n, COUNT(DISTINCT COALESCE(customer_id, id)) AS who FROM sided WHERE company_name IS NOT NULL GROUP BY company_name),
     s AS (SELECT SUM(n) AS filled, COUNT(*) AS values_, SUM(DIV(n * (n - 1), 2)) AS every FROM c),
     t AS (SELECT GREATEST(@min_block, CAST(CEIL(@spread * filled / GREATEST(values_, 1)) AS INT64)) AS at_least FROM s),
     held AS (SELECT v, n FROM c, t WHERE n >= at_least AND who >= @crowd)
SELECT 'company_name' AS field, v AS value, n FROM held, s WHERE DIV(n * (n - 1), 2) > every - (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM held);

UPDATE sided SET company_name = NULL, any_name = NULL
WHERE company_name IN (SELECT value FROM held_company_name);

CREATE OR REPLACE TEMP TABLE held_address_code AS
WITH c AS (SELECT address_code AS v, COUNT(*) AS n, COUNT(DISTINCT COALESCE(customer_id, id)) AS who FROM sided WHERE address_code IS NOT NULL GROUP BY address_code),
     s AS (SELECT SUM(n) AS filled, COUNT(*) AS values_, SUM(DIV(n * (n - 1), 2)) AS every FROM c),
     t AS (SELECT GREATEST(@min_block, CAST(CEIL(@spread * filled / GREATEST(values_, 1)) AS INT64)) AS at_least FROM s),
     held AS (SELECT v, n FROM c, t WHERE n >= at_least AND who >= @crowd)
SELECT 'address_code' AS field, v AS value, n FROM held, s WHERE DIV(n * (n - 1), 2) > every - (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM held);

UPDATE sided SET address_code = NULL
WHERE address_code IN (SELECT value FROM held_address_code);

CREATE OR REPLACE TEMP TABLE held_address AS
WITH c AS (SELECT address AS v, COUNT(*) AS n, COUNT(DISTINCT COALESCE(customer_id, id)) AS who FROM sided WHERE address IS NOT NULL GROUP BY address),
     s AS (SELECT SUM(n) AS filled, COUNT(*) AS values_, SUM(DIV(n * (n - 1), 2)) AS every FROM c),
     t AS (SELECT GREATEST(@min_block, CAST(CEIL(@spread * filled / GREATEST(values_, 1)) AS INT64)) AS at_least FROM s),
     held AS (SELECT v, n FROM c, t WHERE n >= at_least AND who >= @crowd)
SELECT 'address' AS field, v AS value, n FROM held, s WHERE DIV(n * (n - 1), 2) > every - (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM held);

UPDATE sided SET address = NULL
WHERE address IN (SELECT value FROM held_address);

CREATE OR REPLACE TEMP TABLE held_phone AS
WITH c AS (SELECT phone AS v, COUNT(*) AS n, COUNT(DISTINCT COALESCE(customer_id, id)) AS who FROM sided WHERE phone IS NOT NULL GROUP BY phone),
     s AS (SELECT SUM(n) AS filled, COUNT(*) AS values_, SUM(DIV(n * (n - 1), 2)) AS every FROM c),
     t AS (SELECT GREATEST(@min_block, CAST(CEIL(@spread * filled / GREATEST(values_, 1)) AS INT64)) AS at_least FROM s),
     held AS (SELECT v, n FROM c, t WHERE n >= at_least AND who >= @crowd)
SELECT 'phone' AS field, v AS value, n FROM held, s WHERE DIV(n * (n - 1), 2) > every - (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM held);

UPDATE sided SET phone = NULL
WHERE phone IN (SELECT value FROM held_phone);

CREATE OR REPLACE TEMP TABLE held_birth_date AS
WITH c AS (SELECT birth_date AS v, COUNT(*) AS n, COUNT(DISTINCT COALESCE(customer_id, id)) AS who FROM sided WHERE birth_date IS NOT NULL GROUP BY birth_date),
     s AS (SELECT SUM(n) AS filled, COUNT(*) AS values_, SUM(DIV(n * (n - 1), 2)) AS every FROM c),
     t AS (SELECT GREATEST(@min_block, CAST(CEIL(@spread * filled / GREATEST(values_, 1)) AS INT64)) AS at_least FROM s),
     held AS (SELECT v, n FROM c, t WHERE n >= at_least AND who >= @crowd)
SELECT 'birth_date' AS field, v AS value, n FROM held, s WHERE DIV(n * (n - 1), 2) > every - (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM held);

UPDATE sided SET birth_date = NULL
WHERE birth_date IN (SELECT value FROM held_birth_date);

-- the customer ID last: one customer's records' copies still share it while the others are counted
CREATE OR REPLACE TEMP TABLE held_customer_id AS
WITH c AS (SELECT customer_id AS v, COUNT(*) AS n FROM sided WHERE customer_id IS NOT NULL GROUP BY customer_id),
     s AS (SELECT SUM(n) AS filled, COUNT(*) AS values_ FROM c),
     t AS (SELECT GREATEST(@min_block, CAST(CEIL(@spread * filled / GREATEST(values_, 1)) AS INT64)) AS at_least FROM s)
SELECT 'customer_id' AS field, v AS value, n FROM c, t WHERE n >= at_least;

UPDATE sided SET customer_id = NULL
WHERE customer_id IN (SELECT value FROM held_customer_id);

CREATE OR REPLACE TABLE placeholders AS
SELECT field, value, n FROM held_person_name
UNION ALL SELECT field, value, n FROM held_company_name
UNION ALL SELECT field, value, n FROM held_address_code
UNION ALL SELECT field, value, n FROM held_address
UNION ALL SELECT field, value, n FROM held_phone
UNION ALL SELECT field, value, n FROM held_birth_date
UNION ALL SELECT field, value, n FROM held_customer_id;


-- 6. The copies the keys and comparisons read, each a chain of steps from a field, and the records.
--    address: NFKC; 丁目, 番地 and 号 as dashes; the building and room after the first space past the street number
--    gone, then every space; the address's own prefecture off its start. first3, initial, last3: a key's start or
--    end. long_vowel: a long vowel written either way (サトウ, サトオ, サトー) as one reading.

CREATE OR REPLACE TABLE records AS
WITH copies AS (
  SELECT
    *,
    NULLIF(TRANSLATE(person_name, @kana_fold_from, @kana_fold_to), '') AS person_name__kana_fold,
    NULLIF(TRANSLATE(REGEXP_REPLACE(nfkc(company_name), @legal_pattern, ''), @kana_fold_from, @kana_fold_to), '') AS company_name__nfkc_strip_legal_form_kana_fold,
    NULLIF(REGEXP_REPLACE(
      REPLACE(
        REGEXP_REPLACE(
          REGEXP_REPLACE(
            REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(nfkc(address), r'(\d+)丁目', r'\1-'), r'(\d+)番地?', r'\1-'), r'(\d+)号', r'\1'),
            r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]+|[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]+$', ''),
          r'^(.*?[0-9][^ ]*) .*$', r'\1'),
        ' ', ''),
      @prefecture_pattern, ''), '') AS address__address,
    NULLIF(SUBSTR(postal_code, 1, 3), '') AS postal_code__first3,
    NULLIF(SUBSTR(any_name, 1, 1), '') AS any_name__initial,
    NULLIF(TRANSLATE(given_name, @kana_fold_from, @kana_fold_to), '') AS given_name__kana_fold
  FROM sided
),
readings AS (
  SELECT
    *,
    NULLIF(SUBSTR(address__address, 1, 3), '') AS address__address_first3,
    NULLIF(REGEXP_REPLACE(REGEXP_REPLACE(person_name__kana_fold, r'([オコソトノホモヨロ])[ウオ]', r'\1ウ'), r'([エケセテネヘメレ])[イエ]', r'\1イ'), '') AS person_name__kana_fold_long_vowel
  FROM copies
)
SELECT
  * EXCEPT (side),
  NULLIF(SUBSTR(person_name__kana_fold_long_vowel, -3), '') AS person_name__kana_fold_long_vowel_last3
FROM readings;
