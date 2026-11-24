-- The functions nayose's SQL calls, each written once, and the comparisons' levels; every job runs this file first:
--
-- 1. The intake's: each value of the input as read, what loses nothing fixed: mapping.sql reads every column it reads
--    through read_value(value, numeric, @nulls). O(bytes). What is fixed, in order:
--      damaged       a value holding U+FFFD (bytes decoded wrong upstream, or bytes that aren't UTF-8): missing
--      lists         a value written as a list of plain items (["8700848"], ['大分市'], [0708612]): its first filled
--                    item, the rest dropped; none filled, missing
--      controls      control characters, zero-width characters and BOMs removed; tabs and line breaks one space
--      placeholders  a value written as a placeholder null ([input] nulls), or of spaces alone (any width): missing
--      numbers       in a column of numbers (numeric: the mapping says), a whole number a spreadsheet wrote as a float
--                    (12345.0) as its digits, and one cut short in E notation (1.23E+11: its digits are gone) missing
--    SP below is Python's whitespace (str.strip): \t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}.
--
-- 2. The model's comparisons (stage 2 and the scores): how two records compare, field by field, each given the two
--    records whole (l, r: records' rows). Each is a gamma, the level a pair lands in: -1 missing (a side empty), then
--    its levels from the highest down, 0 the else level. The cl_* functions compare by character (engines.py:
--    JavaScript in BigQuery; in DuckDB its own functions where both strings are a byte a character, else rapidfuzz);
--    a similarity passes at its threshold or above, a distance at its threshold or below. An edit distance is never
--    less than the two lengths' difference, nor than the distance of the strings' one_byte_hash copies (records.sql):
--    those are tested first, the same levels without the call where it can't pass. O(L²) a pair for a fuzzy level.
--
-- 3. The rules' fuzzy tests (score.sql): a name, a company, an address or a phone close enough.
--
-- 4. Each comparison's levels as 2. numbers them, with their labels and kinds: what fit.sql reads of a level.


-- ---------- 1. The intake ----------

-- A value of spaces alone (SP, any width), or empty.
CREATE OR REPLACE TEMP FUNCTION blank(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$'));

-- A value without the spaces it starts and ends with (SP: as Python's str.strip takes them).
CREATE OR REPLACE TEMP FUNCTION trimmed(v STRING) AS (REGEXP_REPLACE(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]+|[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]+$', ''));

-- A value written as a list: its first filled item; else the value (damaged, missing).
--   A list is plain when JSON reads it as a list of strings, numbers and nulls (["a", 1, null]), or Python as a list
--   of strings (['a', "b",]; shortcut: a Python string with a backslash in it is left as written, where Python would
--   read its escapes; none seen in a records file). An item is filled when it holds more than spaces (an escape counts
--   as filled). A string is read as JSON reads it (its escapes, \u5927, decoded); a number as written, a whole one
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

CREATE OR REPLACE TEMP FUNCTION unlisted(v STRING) RETURNS STRING AS (
  CASE
    WHEN v IS NULL OR v = '' OR REGEXP_CONTAINS(v, r'\x{fffd}') THEN NULL   -- damaged
    WHEN NOT REGEXP_CONTAINS(v, r'\[') THEN v                                   -- most values: no list
    -- a code with leading zeros, unquoted: [0708612]
    WHEN REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\p{Nd}+[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      THEN REGEXP_EXTRACT(v, r'(\p{Nd}+)')
    -- a plain list, as JSON reads one, or as Python reads a list of strings
    WHEN REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r]*(?:(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null)(?:[ \t\n\r]*,[ \t\n\r]*(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null))*)?[ \t\n\r]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      OR REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r\x{0c}]*(?:(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*")(?:[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*"))*(?:[ \t\n\r\x{0c}]*,)?)?[ \t\n\r\x{0c}]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      THEN item_read(listed_item(v))
    ELSE v
  END
);

-- Each value as read: unlisted, then controls removed (tabs and breaks a space), then a placeholder (nulls: an anchored
-- pattern of [input] nulls, or spaces alone) and, in a column of numbers, a number cut short marked (CHR(1), which no
-- value holds once its controls are gone) and made missing, and a whole one written 12345.0 read as its digits. Each
-- step reads the one before once: a function's argument is copied wherever it is read.
CREATE OR REPLACE TEMP FUNCTION read_value(v STRING, numeric BOOL, nulls STRING) RETURNS STRING AS (
  NULLIF(
    REGEXP_REPLACE(
      REGEXP_REPLACE(
        REGEXP_REPLACE(
          REGEXP_REPLACE(REGEXP_REPLACE(unlisted(v), r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\x{200b}-\x{200d}\x{2060}\x{feff}]', ''), r'[\t\r\n]+', ' '),
          nulls, CHR(1)),
        IF(numeric, r'^[ \x{3000}]*-?\p{Nd}(\.\p{Nd}+)?[eE]\+\p{Nd}+[ \x{3000}]*$', r'$^'), CHR(1)),
      IF(numeric, r'^[ \x{3000}]*(-?\p{Nd}+)\.0+[ \x{3000}]*$', r'($^)'), r'\1'),
    CHR(1))
);


-- ---------- 2. The comparisons ----------

-- Jaro–Winkler on the two strings' one-byte copies where both have one (records.sql), else on the strings: the same
-- score (it compares characters only for equality, and a copy keeps them apart), which DuckDB then finds natively.
CREATE OR REPLACE TEMP FUNCTION jaro_winkler_of(a STRING, b STRING, one_byte_a STRING, one_byte_b STRING, threshold FLOAT64) RETURNS FLOAT64 AS (
  IF(one_byte_a IS NOT NULL AND one_byte_b IS NOT NULL, cl_jaro_winkler_cut(one_byte_a, one_byte_b, threshold), cl_jaro_winkler_cut(a, b, threshold))
);


-- How many characters two strings start with alike, up to 4: the start Winkler raises a Jaro score by.
CREATE OR REPLACE TEMP FUNCTION common_start(a STRING, b STRING) AS (
  IF(LEFT(a, 1) = LEFT(b, 1), IF(LEFT(a, 2) = LEFT(b, 2), IF(LEFT(a, 3) = LEFT(b, 3), IF(LEFT(a, 4) = LEFT(b, 4), 4, 3), 2), 1), 0)
);

-- The most Jaro–Winkler two strings can score, from their lengths and common start alone: Jaro at most (2 + r)/3 (r the
-- shorter's length over the longer's: every character of the shorter matching, in order), raised by the common start
-- (up to 4 characters) as Winkler raises it. A threshold this misses, the score misses too.
CREATE OR REPLACE TEMP FUNCTION jaro_winkler_most(a STRING, b STRING) AS (
  (2 + LEAST(LENGTH(a), LENGTH(b)) / GREATEST(LENGTH(a), LENGTH(b), 1)) / 3 * (1 - CAST(0.1 AS FLOAT64) * common_start(a, b))
    + CAST(0.1 AS FLOAT64) * common_start(a, b)
);

-- The most two names' Jaro–Winkler can be: where both are katakana (one-byte copies), from the letters they share,
-- since Jaro's matches pair equal letters, so are at most the letters both hold, each as often as the name it is
-- rarer in holds it (the letters in both sets, plus the fewer of either name's repeats: its length less the letters
-- it holds), and its transpositions count for nothing; then raised by the common start as Winkler raises it,
-- 1 - (1 - jaro)(1 - 0.1 · start). Else jaro_winkler_most's, from the lengths. A threshold this misses, the score misses too.
CREATE OR REPLACE TEMP FUNCTION name_jw_most(l ANY TYPE, r ANY TYPE) AS (
  IF(l.person_name__kana_fold_one_byte IS NULL OR r.person_name__kana_fold_one_byte IS NULL,
     jaro_winkler_most(l.person_name__kana_fold, r.person_name__kana_fold),
     1 - (1 - (LEAST(BIT_COUNT(l.person_name__kana_fold_letters_lo & r.person_name__kana_fold_letters_lo) + BIT_COUNT(l.person_name__kana_fold_letters_hi & r.person_name__kana_fold_letters_hi)
                     + LEAST(LENGTH(l.person_name__kana_fold_one_byte) - BIT_COUNT(l.person_name__kana_fold_letters_lo) - BIT_COUNT(l.person_name__kana_fold_letters_hi),
                             LENGTH(r.person_name__kana_fold_one_byte) - BIT_COUNT(r.person_name__kana_fold_letters_lo) - BIT_COUNT(r.person_name__kana_fold_letters_hi)),
                     LENGTH(l.person_name__kana_fold_one_byte), LENGTH(r.person_name__kana_fold_one_byte))
               * (1 / LENGTH(l.person_name__kana_fold_one_byte) + 1 / LENGTH(r.person_name__kana_fold_one_byte)) + 1) / 3)
         * (1 - CAST(0.1 AS FLOAT64) * common_start(l.person_name__kana_fold, r.person_name__kana_fold)))
);

-- name: the person's name as written, folded (kana_fold), read alike (long_vowel), then near. Two functions, so the
-- Jaro–Winkler is called once a pair: name_score, the folded names' score from 0.75 up, else 0 (NULL where an
-- equality settles the level), computed once as a column (s_name); then name_level, the level from it.
CREATE OR REPLACE TEMP FUNCTION name_score(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.person_name IS NULL OR r.person_name IS NULL OR l.person_name = r.person_name
      OR l.person_name__kana_fold = r.person_name__kana_fold OR l.person_name__kana_fold_long_vowel = r.person_name__kana_fold_long_vowel THEN NULL
    WHEN name_jw_most(l, r) < CAST(0.749999 AS FLOAT64) THEN CAST(0 AS FLOAT64)  -- below 0.75 for sure: no call
    ELSE jaro_winkler_of(l.person_name__kana_fold, r.person_name__kana_fold, l.person_name__kana_fold_one_byte,
                         r.person_name__kana_fold_one_byte, CAST(0.75 AS FLOAT64))
  END
);

CREATE OR REPLACE TEMP FUNCTION name_level(l ANY TYPE, r ANY TYPE, s FLOAT64) AS (
  CASE
    WHEN l.person_name IS NULL OR r.person_name IS NULL THEN -1
    WHEN l.person_name = r.person_name THEN 6                                                -- exact
    WHEN l.person_name__kana_fold = r.person_name__kana_fold THEN 5                          -- fold exact
    WHEN l.person_name__kana_fold_long_vowel = r.person_name__kana_fold_long_vowel THEN 4    -- same reading
    WHEN s >= CAST(0.95 AS FLOAT64) THEN 3                                                   -- fold JW high
    WHEN l.given_name__kana_fold = r.given_name__kana_fold THEN 2                            -- given name
    WHEN s >= CAST(0.75 AS FLOAT64) THEN 1                                                   -- fold JW low
    ELSE 0
  END
);
-- the same levels where the score is the Jaro–Winkler itself, without name_score's bound: the gate's few sampled
-- pairs (score.sql), where the bound's two letter columns would be read of every record for a call or two saved
CREATE OR REPLACE TEMP FUNCTION gamma_name(l ANY TYPE, r ANY TYPE) AS (
  name_level(l, r, jaro_winkler_of(l.person_name__kana_fold, r.person_name__kana_fold, l.person_name__kana_fold_one_byte,
                                   r.person_name__kana_fold_one_byte, CAST(0.75 AS FLOAT64)))
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
    WHEN CASE  -- address close: the tests in order, the costliest last
           WHEN l.address__address IS NULL OR r.address__address IS NULL OR ABS(LENGTH(l.address__address) - LENGTH(r.address__address)) > 2 THEN FALSE
           WHEN l.address__address_one_byte_hash IS NULL OR r.address__address_one_byte_hash IS NULL
             THEN cl_levenshtein_cut(l.address__address, r.address__address, 2) <= 2
           WHEN cl_levenshtein_cut(l.address__address_one_byte_hash, r.address__address_one_byte_hash, 2) > 2 THEN FALSE
           ELSE cl_levenshtein_cut(l.address__address, r.address__address, 2) <= 2 END THEN 2
    WHEN l.postal_code = r.postal_code THEN 1                                                        -- same postal
    ELSE 0
  END
);

-- Two values one edit apart (a character changed, added, dropped, or two neighbours swapped) share their first or
-- their last h characters, h = ⌊(the shorter's length − 1)/2⌋: the edit leaves one side of it whole. A test of string
-- equalities alone, so an edit distance is called only on a pair that passes it (two 13-digit IDs at random rarely do).
CREATE OR REPLACE TEMP FUNCTION one_edit_may(a STRING, b STRING) AS (
  LEFT(a, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)) = LEFT(b, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2))
  OR RIGHT(a, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)) = RIGHT(b, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2))
);

-- phone, cif, birth: equal, or one digit off (Hamming pads the shorter value at its end; Damerau–Levenshtein also
-- counts two neighbours swapped as one edit). Each test a CASE's own branch: a CASE tries them in order, on both engines.
CREATE OR REPLACE TEMP FUNCTION gamma_phone(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.phone IS NULL OR r.phone IS NULL THEN -1
    WHEN l.phone = r.phone THEN 2                                                                      -- exact
    WHEN ABS(LENGTH(l.phone) - LENGTH(r.phone)) > 1 OR NOT one_edit_may(l.phone, r.phone) THEN 0
    WHEN cl_hamming_cut(l.phone, r.phone, 1) <= 1 THEN 1                                               -- one digit off
    ELSE 0
  END
);

CREATE OR REPLACE TEMP FUNCTION gamma_cif(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.customer_id IS NULL OR r.customer_id IS NULL THEN -1
    WHEN l.customer_id = r.customer_id THEN 2                                                          -- exact
    WHEN ABS(LENGTH(l.customer_id) - LENGTH(r.customer_id)) > 1 OR NOT one_edit_may(l.customer_id, r.customer_id) THEN 0
    WHEN cl_damerau_levenshtein_cut(l.customer_id, r.customer_id, 1) <= 1 THEN 1                      -- one digit off
    ELSE 0
  END
);

CREATE OR REPLACE TEMP FUNCTION gamma_birth(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.birth_date IS NULL OR r.birth_date IS NULL THEN -1
    WHEN l.birth_date = r.birth_date THEN 2                                                            -- exact
    WHEN ABS(LENGTH(l.birth_date) - LENGTH(r.birth_date)) > 1 OR NOT one_edit_may(l.birth_date, r.birth_date) THEN 0
    WHEN cl_damerau_levenshtein_cut(l.birth_date, r.birth_date, 1) <= 1 THEN 1                        -- one digit off
    ELSE 0
  END
);


-- ---------- 3. The rules' fuzzy tests (score.sql) ----------

-- a person's folded name within two edits (Damerau–Levenshtein), a company's within one (Levenshtein), an address close
-- (Jaro–Winkler 0.9), a phone one digit off (Hamming): each an equality first, then its length, then the function, on
-- one-byte copies where both have one; each test a CASE branch, so the function is called only where they pass
CREATE OR REPLACE TEMP FUNCTION near_name(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.person_name__kana_fold IS NULL OR r.person_name__kana_fold IS NULL THEN FALSE
    WHEN l.person_name__kana_fold = r.person_name__kana_fold THEN TRUE
    WHEN ABS(LENGTH(l.person_name__kana_fold) - LENGTH(r.person_name__kana_fold)) > 2 THEN FALSE
    ELSE IF(l.person_name__kana_fold_one_byte IS NOT NULL AND r.person_name__kana_fold_one_byte IS NOT NULL,
            cl_damerau_levenshtein_cut(l.person_name__kana_fold_one_byte, r.person_name__kana_fold_one_byte, 2),
            cl_damerau_levenshtein_cut(l.person_name__kana_fold, r.person_name__kana_fold, 2)) <= 2
  END
);

CREATE OR REPLACE TEMP FUNCTION near_company(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.company_name__nfkc_strip_legal_form_kana_fold IS NULL OR r.company_name__nfkc_strip_legal_form_kana_fold IS NULL THEN FALSE
    WHEN l.company_name__nfkc_strip_legal_form_kana_fold = r.company_name__nfkc_strip_legal_form_kana_fold THEN TRUE
    WHEN ABS(LENGTH(l.company_name__nfkc_strip_legal_form_kana_fold) - LENGTH(r.company_name__nfkc_strip_legal_form_kana_fold)) > 1 THEN FALSE
    ELSE IF(l.company_name__nfkc_strip_legal_form_kana_fold_one_byte IS NOT NULL AND r.company_name__nfkc_strip_legal_form_kana_fold_one_byte IS NOT NULL,
             cl_levenshtein_cut(l.company_name__nfkc_strip_legal_form_kana_fold_one_byte, r.company_name__nfkc_strip_legal_form_kana_fold_one_byte, 1),
            cl_levenshtein_cut(l.company_name__nfkc_strip_legal_form_kana_fold, r.company_name__nfkc_strip_legal_form_kana_fold, 1)) <= 1
  END
);

CREATE OR REPLACE TEMP FUNCTION near_address(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.address__address IS NULL OR r.address__address IS NULL THEN FALSE
    WHEN l.address__address = r.address__address THEN TRUE
    ELSE cl_jaro_winkler_cut(l.address__address, r.address__address, CAST(0.9 AS FLOAT64)) >= CAST(0.9 AS FLOAT64)
  END
);

CREATE OR REPLACE TEMP FUNCTION near_phone(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.phone IS NULL OR r.phone IS NULL THEN FALSE
    WHEN l.phone = r.phone THEN TRUE
    WHEN ABS(LENGTH(l.phone) - LENGTH(r.phone)) > 1 OR NOT one_edit_may(l.phone, r.phone) THEN FALSE
    ELSE cl_hamming_cut(l.phone, r.phone, 1) <= 1
  END
);


-- ---------- 4. The levels ----------

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
