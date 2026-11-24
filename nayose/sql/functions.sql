-- The functions nayose's SQL calls, each written once; every job runs this file first. Two kinds:
--
-- 1. The intake's (stage 1's first step): each value of the input files as read, what loses nothing fixed and counted,
--    never a value. nayose.read applies them to every column of the file (its columns are its own, so that statement
--    is written for each file): raw (the files, every column as text) → input (each value read) and intake (what was
--    fixed: how many values, never one). O(bytes). What is fixed, in order:
--      damaged       a value holding U+FFFD (bytes decoded wrong upstream, or bytes that aren't UTF-8): missing
--      lists         a value written as a list of plain items (["8700848"], ['大分市'], [0708612], a Parquet list
--                    column): its first filled item; none filled, missing
--      first of several   the same, when it lists several: the rest dropped
--      controls      control characters, zero-width characters and BOMs removed; tabs and line breaks one space
--      placeholders  a value written as a placeholder null ([input] nulls), or of spaces alone (any width): missing
--      numbers       in a column of numbers, a whole number a spreadsheet wrote as a float (12345.0) as its digits, and
--                    one cut short in E notation (1.23E+11: its digits are gone) missing
--    SP below is Python's whitespace (str.strip): \t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}.
--
-- 2. The model's comparisons (stage 2 and the scores): how two records compare, field by field, each given the two
--    records whole (l, r: records' rows). Each is a gamma, the level a pair lands in: -1 missing (a side empty), then
--    its levels from the highest down, 0 the else level. The cl_* functions compare by character (engines.py:
--    JavaScript in BigQuery; in DuckDB its own functions where both strings are a byte a character, else rapidfuzz);
--    a similarity passes at its threshold or above, a distance at its threshold or below. An edit distance is never
--    less than the two lengths' difference, nor than the distance of the strings' one_byte_hash copies (records.sql):
--    those are tested first, the same levels without the call where it can't pass. O(L²) a pair for a fuzzy level.


-- ---------- 1. The intake ----------

-- A column of numbers: half its filled values digits, a point, an exponent's E+ and a leading minus aside. Each value:
-- NULL not filled, 1 a number, 0 not one.
CREATE OR REPLACE TEMP FUNCTION numberlike(v STRING) RETURNS INT64 AS (
  CASE
    WHEN v IS NULL OR REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$') THEN NULL
    WHEN REGEXP_CONTAINS(v, r'[^\x00-\x7f]') THEN 0
    WHEN REGEXP_CONTAINS(
      LTRIM(REPLACE(REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(v, r'^[\t-\r\x{1c}-\x{20}]+|[\t-\r\x{1c}-\x{20}]+$', ''), r'^([^.]*)\.', r'\1'), 'E+', ''), 'e+', ''), '-'),
      r'^[0-9]+$') THEN 1
    ELSE 0
  END
);


-- Damaged, then a value written as a list: (the value, what was fixed).
--   A list is plain when JSON reads it as a list of strings, numbers and nulls (["a", 1, null]), or Python as a list
--   of strings (['a', "b",]; shortcut: a Python string with a backslash in it is left as written, where Python would
--   read its escapes; none seen in a records file). An item is filled when it holds more than spaces (an escape counts
--   as filled). A string is read as JSON reads it (its escapes, 大, decoded); a number as written, a whole one
--   written 12345.0 as its digits, one cut short like 1.23E+11 missing, as a bare one is.
--   The patterns, in pieces: a JSON string "(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"; a JSON number
--   -?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?; a Python string '…' or "…" ('' is \x{27}); a blank item
--   "SP*", 'SP*' or null.
CREATE OR REPLACE TEMP FUNCTION listed_item(v STRING) RETURNS STRING AS (
  -- the first filled item, as written (quotes and all): NULL when no item is filled
  REGEXP_EXTRACT(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r\x{0c}]*(?:(?:"[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*"|\x{27}[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\x{27}|null)[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*)*("(?:[^"\\]|\\.)*(?:[^"\\\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]|\\.)(?:[^"\\]|\\.)*"|\x{27}[^\x{27}\\\r\n]*[^\x{27}\\\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}][^\x{27}\\\r\n]*\x{27}|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
);

CREATE OR REPLACE TEMP FUNCTION item_read(item STRING) RETURNS STRING AS (
  CASE
    WHEN item IS NULL THEN NULL
    WHEN NOT (STARTS_WITH(item, '"') OR STARTS_WITH(item, "'")) THEN  -- a number
      CASE WHEN REGEXP_CONTAINS(item, r'^-?\p{Nd}(\.\p{Nd}+)?[eE]\+\p{Nd}+$') THEN NULL
           WHEN REGEXP_CONTAINS(item, r'^-?\p{Nd}+\.0+$') THEN REGEXP_EXTRACT(item, r'^(-?\p{Nd}+)\.0+$')
           ELSE item END
    WHEN STRPOS(item, '\\') > 0 THEN JSON_VALUE(item)  -- its escapes decoded
    ELSE SUBSTR(item, 2, LENGTH(item) - 2)
  END
);

CREATE OR REPLACE TEMP FUNCTION listed(v STRING) RETURNS STRUCT<v STRING, fixed STRING> AS (
  CASE
    WHEN v IS NULL OR v = '' THEN STRUCT(CAST(NULL AS STRING) AS v, CAST(NULL AS STRING) AS fixed)
    WHEN REGEXP_CONTAINS(v, r'\x{fffd}') THEN STRUCT(CAST(NULL AS STRING) AS v, 'damaged' AS fixed)
    -- a code with leading zeros, unquoted: [0708612]
    WHEN REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\p{Nd}+[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      THEN STRUCT(REGEXP_EXTRACT(v, r'(\p{Nd}+)') AS v, 'lists' AS fixed)
    -- a plain list, as JSON reads one, or as Python reads a list of strings
    WHEN REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r]*(?:(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null)(?:[ \t\n\r]*,[ \t\n\r]*(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null))*)?[ \t\n\r]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      OR REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r\x{0c}]*(?:(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*")(?:[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*"))*(?:[ \t\n\r\x{0c}]*,)?)?[ \t\n\r\x{0c}]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      THEN STRUCT(
        item_read(listed_item(v)) AS v,
        -- several: a filled item after the first
        IF(listed_item(v) IS NULL OR REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r\x{0c}]*(?:(?:"[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*"|\x{27}[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\x{27}|null)[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*)*(?:"(?:[^"\\]|\\.)*(?:[^"\\\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]|\\.)(?:[^"\\]|\\.)*"|\x{27}[^\x{27}\\\r\n]*[^\x{27}\\\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}][^\x{27}\\\r\n]*\x{27}|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)(?:[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*(?:"[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*"|\x{27}[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\x{27}|null))*(?:[ \t\n\r\x{0c}]*,)?[ \t\n\r\x{0c}]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$'),
           'lists', 'first of several') AS fixed)
    ELSE STRUCT(v AS v, CAST(NULL AS STRING) AS fixed)
  END
);


-- Then controls, placeholders and numbers, on a value `listed` gave: (the value, what was fixed). `numeric`: whether
-- its column holds numbers (numberlike); `nulls`: [input] nulls. A value holding no control character or break is
-- read as it is (most are: the test is one scan, where removing them is two).
CREATE OR REPLACE TEMP FUNCTION settled(v STRING, fixed STRING, numeric BOOL, nulls ARRAY<STRING>) RETURNS STRUCT<v STRING, fixed STRING> AS (
  CASE
    WHEN REGEXP_REPLACE(v, r'^[ \x{3000}]+|[ \x{3000}]+$', '') IN UNNEST(nulls)
      OR REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      THEN STRUCT(CAST(NULL AS STRING) AS v, 'placeholders' AS fixed)
    WHEN numeric AND REGEXP_CONTAINS(REGEXP_REPLACE(v, r'^[ \x{3000}]+|[ \x{3000}]+$', ''), r'^-?\p{Nd}+\.0+$')
      THEN STRUCT(REGEXP_EXTRACT(REGEXP_REPLACE(v, r'^[ \x{3000}]+|[ \x{3000}]+$', ''), r'^(-?\p{Nd}+)\.0+$') AS v, 'numbers' AS fixed)
    WHEN numeric AND REGEXP_CONTAINS(REGEXP_REPLACE(v, r'^[ \x{3000}]+|[ \x{3000}]+$', ''), r'^-?\p{Nd}(\.\p{Nd}+)?[eE]\+\p{Nd}+$')
      THEN STRUCT(CAST(NULL AS STRING) AS v, 'numbers' AS fixed)
    ELSE STRUCT(v AS v, fixed AS fixed)
  END
);

CREATE OR REPLACE TEMP FUNCTION tidied(v STRING, fixed STRING, numeric BOOL, nulls ARRAY<STRING>) RETURNS STRUCT<v STRING, fixed STRING> AS (
  CASE
    WHEN v IS NULL THEN STRUCT(CAST(NULL AS STRING) AS v, fixed AS fixed)
    WHEN REGEXP_CONTAINS(v, r'[\x00-\x1f\x7f-\x9f\x{200b}-\x{200d}\x{2060}\x{feff}]')  -- controls, tabs and breaks: removed, a space
      THEN settled(REGEXP_REPLACE(REGEXP_REPLACE(v, r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\x{200b}-\x{200d}\x{2060}\x{feff}]', ''), r'[\t\r\n]+', ' '),
                   'controls', numeric, nulls)
    ELSE settled(v, fixed, numeric, nulls)
  END
);


-- ---------- 2. The comparisons ----------

-- Jaro–Winkler on the two strings' one-byte copies where both have one (records.sql), else on the strings: the same
-- score (it compares characters only for equality, and a copy keeps them apart), which DuckDB then finds natively.
CREATE OR REPLACE TEMP FUNCTION jaro_winkler_of(a STRING, b STRING, one_byte_a STRING, one_byte_b STRING, threshold FLOAT64) RETURNS FLOAT64 AS (
  IF(one_byte_a IS NOT NULL AND one_byte_b IS NOT NULL, cl_jaro_winkler_cut(one_byte_a, one_byte_b, threshold), cl_jaro_winkler_cut(a, b, threshold))
);

-- name: the person's name as written, folded (kana_fold), read alike (long_vowel), then near
CREATE OR REPLACE TEMP FUNCTION gamma_name(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.person_name IS NULL OR r.person_name IS NULL THEN -1
    WHEN l.person_name = r.person_name THEN 6                                                          -- exact
    WHEN l.person_name__kana_fold = r.person_name__kana_fold THEN 5                                    -- fold exact
    WHEN l.person_name__kana_fold_long_vowel = r.person_name__kana_fold_long_vowel THEN 4              -- same reading
    WHEN jaro_winkler_of(l.person_name__kana_fold, r.person_name__kana_fold, l.person_name__kana_fold_one_byte, r.person_name__kana_fold_one_byte,
                         CAST(0.95 AS FLOAT64)) >= CAST(0.95 AS FLOAT64) THEN 3                           -- fold JW high
    WHEN l.given_name__kana_fold = r.given_name__kana_fold THEN 2                                      -- given name
    WHEN jaro_winkler_of(l.person_name__kana_fold, r.person_name__kana_fold, l.person_name__kana_fold_one_byte, r.person_name__kana_fold_one_byte,
                         CAST(0.75 AS FLOAT64)) >= CAST(0.75 AS FLOAT64) THEN 1                           -- fold JW low
    ELSE 0
  END
);

-- company: the company's name, its legal form gone and folded (company_name__nfkc_strip_legal_form_kana_fold)
CREATE OR REPLACE TEMP FUNCTION gamma_company(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.company_name IS NULL OR r.company_name IS NULL THEN -1
    WHEN l.company_name__nfkc_strip_legal_form_kana_fold = r.company_name__nfkc_strip_legal_form_kana_fold THEN 2  -- exact
    WHEN jaro_winkler_of(l.company_name__nfkc_strip_legal_form_kana_fold, r.company_name__nfkc_strip_legal_form_kana_fold,
                         l.company_name__nfkc_strip_legal_form_kana_fold_one_byte, r.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                         CAST(0.8 AS FLOAT64)) >= CAST(0.8 AS FLOAT64) THEN 1                             -- JW low
    ELSE 0
  END
);

-- address: missing only when the address code, the address and the postal code are all missing on a side
CREATE OR REPLACE TEMP FUNCTION gamma_address(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN (l.address_code IS NULL OR r.address_code IS NULL) AND (l.address IS NULL OR r.address IS NULL)
      AND (l.postal_code IS NULL OR r.postal_code IS NULL) THEN -1
    WHEN l.address_code = r.address_code OR l.address__address = r.address__address THEN 3          -- same address
    WHEN ABS(LENGTH(l.address__address) - LENGTH(r.address__address)) <= 2
      AND (l.address__address_one_byte_hash IS NULL OR r.address__address_one_byte_hash IS NULL
           OR cl_levenshtein_cut(l.address__address_one_byte_hash, r.address__address_one_byte_hash, 2) <= 2)
      AND cl_levenshtein_cut(l.address__address, r.address__address, 2) <= 2 THEN 2                -- address close
    WHEN l.postal_code = r.postal_code THEN 1                                                        -- same postal
    ELSE 0
  END
);

-- phone, cif, birth: equal, or one digit off (Hamming pads the shorter value at its end; Damerau–Levenshtein also
-- counts two neighbours swapped as one edit)
CREATE OR REPLACE TEMP FUNCTION gamma_phone(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.phone IS NULL OR r.phone IS NULL THEN -1
    WHEN l.phone = r.phone THEN 2                                                                      -- exact
    WHEN ABS(LENGTH(l.phone) - LENGTH(r.phone)) <= 1 AND cl_hamming_cut(l.phone, r.phone, 1) <= 1 THEN 1  -- one digit off
    ELSE 0
  END
);

CREATE OR REPLACE TEMP FUNCTION gamma_cif(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.customer_id IS NULL OR r.customer_id IS NULL THEN -1
    WHEN l.customer_id = r.customer_id THEN 2                                                          -- exact
    WHEN ABS(LENGTH(l.customer_id) - LENGTH(r.customer_id)) <= 1
      AND cl_damerau_levenshtein_cut(l.customer_id, r.customer_id, 1) <= 1 THEN 1                     -- one digit off
    ELSE 0
  END
);

CREATE OR REPLACE TEMP FUNCTION gamma_birth(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.birth_date IS NULL OR r.birth_date IS NULL THEN -1
    WHEN l.birth_date = r.birth_date THEN 2                                                            -- exact
    WHEN ABS(LENGTH(l.birth_date) - LENGTH(r.birth_date)) <= 1
      AND cl_damerau_levenshtein_cut(l.birth_date, r.birth_date, 1) <= 1 THEN 1                       -- one digit off
    ELSE 0
  END
);


-- Each comparison's levels, as the functions above number them: what the fit and the report read of a level.
-- kind: exact (equality alone), near (a distance or a similarity), else. position: the comparison's place in the model.
CREATE OR REPLACE TEMP TABLE levels AS
SELECT * FROM UNNEST([
  STRUCT(1 AS position, 'name' AS comparison, 6 AS gamma, 'exact' AS label, 'exact' AS kind),
  STRUCT(1, 'name', 5, 'fold exact', 'exact'),
  STRUCT(1, 'name', 4, 'same reading', 'exact'),
  STRUCT(1, 'name', 3, 'fold JW high', 'near'),
  STRUCT(1, 'name', 2, 'given name', 'exact'),
  STRUCT(1, 'name', 1, 'fold JW low', 'near'),
  STRUCT(1, 'name', 0, 'else', 'else'),
  STRUCT(2, 'company', 2, 'exact', 'exact'),
  STRUCT(2, 'company', 1, 'JW low', 'near'),
  STRUCT(2, 'company', 0, 'else', 'else'),
  STRUCT(3, 'address', 3, 'same address', 'exact'),
  STRUCT(3, 'address', 2, 'address close', 'near'),
  STRUCT(3, 'address', 1, 'same postal', 'exact'),
  STRUCT(3, 'address', 0, 'else', 'else'),
  STRUCT(4, 'phone', 2, 'exact', 'exact'),
  STRUCT(4, 'phone', 1, 'one digit off', 'near'),
  STRUCT(4, 'phone', 0, 'else', 'else'),
  STRUCT(5, 'cif', 2, 'exact', 'exact'),
  STRUCT(5, 'cif', 1, 'one digit off', 'near'),
  STRUCT(5, 'cif', 0, 'else', 'else'),
  STRUCT(6, 'birth', 2, 'exact', 'exact'),
  STRUCT(6, 'birth', 1, 'one digit off', 'near'),
  STRUCT(6, 'birth', 0, 'else', 'else')
]);
