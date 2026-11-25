-- The functions that nayose's SQL calls, each written once, and the comparisons' levels. Every job runs this file
-- first. It has four sections.
--
-- 1. The intake. mapping.sql reads every input column through read_value(value, numeric, @nulls), which fixes what
--    can be fixed without losing anything. O(bytes). It applies these fixes in order:
--    - Damaged values. A value that holds U+FFFD is missing. U+FFFD means that bytes were decoded wrongly upstream,
--      or weren't UTF-8.
--    - Lists. A value written as a list of plain items (["8700848"], ['大分市'], [0708612]) becomes its first filled
--      item, and the other items are dropped. If no item is filled, the value is missing.
--    - Controls. Control characters, zero-width characters and BOMs are removed. Each run of tabs and line breaks
--      becomes one space.
--    - Null tokens. A value written as a null token ([input] nulls), or made of spaces alone (any width), is missing.
--    - Numbers. These fixes apply only in a column of numbers (numeric is TRUE; the mapping says which). A whole
--      number that a spreadsheet wrote as a float (12345.0) becomes its digits. A number cut short in E notation
--      (1.23E+11) is missing, because its digits are gone.
--    In the comments below, SP stands for Python's whitespace (the characters str.strip removes). The patterns spell
--    it as [\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}].
--
-- 2. The model's comparisons, which the fit (stage 2) and the scores call. Each compares two records on its fields,
--    and takes both records whole, as rows (l and r). Each returns a gamma, the level the pair lands in. The level is
--    -1 if either side is missing. The other levels count down from the highest to 0, the else level.
--    The cl_* functions compare by character (engines.py). In BigQuery they run as JavaScript, or as BigQuery's own
--    EDIT_DISTANCE for Levenshtein. In DuckDB they run as DuckDB's own functions if both strings take one byte a
--    character, and as rapidfuzz otherwise. A similarity passes at its threshold or above, and a distance passes at
--    its threshold or below. A cl_*_cut function returns the same score if the score passes its threshold. If the
--    score fails, it may return another failing score, so that it can stop early.
--    An edit distance is never less than the difference of the two lengths. Nor is it less than the distance between
--    the strings' one_byte_hash copies (records.sql). So the functions test those first, and skip the call if it
--    can't pass. The levels come out the same. A fuzzy level costs O(L²) a pair, for strings of L characters.
--
-- 3. The rules' fuzzy tests, which score.sql calls. Each says whether two names, companies, addresses or phones are
--    close enough.
--
-- 4. The table levels. It lists each comparison's levels as section 2 numbers them, with their labels and kinds.
--    fit.sql reads it.
--
-- Writes: levels (a temporary table).


-- ---------- 1. The intake ----------

-- blank(v) is TRUE if v is empty or holds only spaces (SP, of any width).
CREATE OR REPLACE TEMP FUNCTION blank(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$'));

-- trimmed(v) returns v without its leading and trailing spaces (SP), as Python's str.strip removes them.
CREATE OR REPLACE TEMP FUNCTION trimmed(v STRING) AS (REGEXP_REPLACE(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]+|[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]+$', ''));

-- The next three functions read a value written as a list. unlisted, which read_value calls, returns a plain list's
-- first filled item. It returns any other value as it is, except that an empty or damaged value is missing.
--   A list is plain if JSON reads it as a list of strings, numbers and nulls (["a", 1, null]), or if Python reads it
--   as a list of strings (['a', "b",]). An item is filled if it holds more than spaces, and an escape counts as
--   filled.
--   shortcut: a list that JSON can't read is left as written if a string in it holds a backslash, although Python
--   would decode the escapes. Decode them if a records file ever holds such a list.
--   The patterns are made of these pieces. A JSON string is "(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*". A JSON
--   number is -?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?. A Python string is '…' or "…" without a
--   backslash or a line break, and the patterns write ' as \x{27}. A blank item is "SP*", 'SP*' or null.
CREATE OR REPLACE TEMP FUNCTION listed_item(v STRING) RETURNS STRING AS (
  -- It returns the first filled item as written, quotes and all, or NULL if no item is filled.
  REGEXP_EXTRACT(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r\x{0c}]*(?:(?:"[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*"|\x{27}[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\x{27}|null)[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*)*("(?:[^"\\]|\\.)*(?:[^"\\\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]|\\.)(?:[^"\\]|\\.)*"|\x{27}[^\x{27}\\\r\n]*[^\x{27}\\\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}][^\x{27}\\\r\n]*\x{27}|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
);

-- item_read returns the value of an item that listed_item found. A string loses its quotes, and if it holds a
-- backslash, JSON_VALUE decodes its escapes (\u5927 becomes 大). A number is read as read_value reads one in a column of
-- numbers. So 12345.0 becomes 12345, a number cut short like 1.23E+11 is missing, and any other stays as written.
CREATE OR REPLACE TEMP FUNCTION item_read(item STRING) RETURNS STRING AS (
  CASE
    WHEN item IS NULL THEN NULL
    WHEN NOT (STARTS_WITH(item, '"') OR STARTS_WITH(item, "'")) THEN  -- the item is a number
      CASE WHEN REGEXP_CONTAINS(item, r'^-?\p{Nd}(\.\p{Nd}+)?[eE]\+\p{Nd}+$') THEN NULL
           WHEN REGEXP_CONTAINS(item, r'^-?\p{Nd}+\.0+$') THEN REGEXP_EXTRACT(item, r'^(-?\p{Nd}+)\.0+$')
           ELSE item END
    WHEN STRPOS(item, '\\') > 0 THEN JSON_VALUE(item)  -- JSON_VALUE decodes the escapes
    ELSE SUBSTR(item, 2, LENGTH(item) - 2)
  END
);

-- unlisted returns v, or its first filled item if v is a plain list. The comment above listed_item says more.
CREATE OR REPLACE TEMP FUNCTION unlisted(v STRING) RETURNS STRING AS (
  CASE
    WHEN v IS NULL OR v = '' OR REGEXP_CONTAINS(v, r'\x{fffd}') THEN NULL  -- an empty or damaged value is missing
    WHEN NOT REGEXP_CONTAINS(v, r'\[') THEN v                              -- most values hold no list
    -- An unquoted code with leading zeros, such as [0708612], isn't JSON. Its digits are kept as written.
    WHEN REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\p{Nd}+[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      THEN REGEXP_EXTRACT(v, r'(\p{Nd}+)')
    -- The value is a plain list that JSON reads, or that Python reads as a list of strings.
    WHEN REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r]*(?:(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null)(?:[ \t\n\r]*,[ \t\n\r]*(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null))*)?[ \t\n\r]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      OR REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r\x{0c}]*(?:(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*")(?:[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*"))*(?:[ \t\n\r\x{0c}]*,)?)?[ \t\n\r\x{0c}]*\][\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$')
      THEN item_read(listed_item(v))
    ELSE v
  END
);

-- read_value returns a value as read, with section 1's fixes in order. First, unlisted reads a list. Next, control
-- characters are removed, and each run of tabs and line breaks becomes one space. Then a null token becomes CHR(1), and
-- so does a number cut short if numeric is TRUE. If numeric is TRUE, a whole number written 12345.0 then becomes its
-- digits. Last, NULLIF makes CHR(1) missing. No other value holds CHR(1) by then, because it is a control character.
-- nulls is the pattern that nayose.nulls_pattern makes of [input] nulls, and it also matches a value of spaces alone.
-- If numeric is FALSE, the number steps use the pattern $^ and change nothing. Each step reads the step before it only
-- once, because a function's argument is copied into every place its body reads it.
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

-- jaro_winkler_of returns the Jaro–Winkler score of a and b, exact at the threshold or above: below it, the score may
-- be returned as 0 instead. It scores their one-byte copies (records.sql) if both have
-- one. The score is the same, because Jaro–Winkler tests characters only for equality, and a copy keeps different
-- characters different. On the copies, DuckDB computes the score with its own function.
CREATE OR REPLACE TEMP FUNCTION jaro_winkler_of(a STRING, b STRING, one_byte_a STRING, one_byte_b STRING,
                                                threshold FLOAT64) RETURNS FLOAT64 AS (
  IF(one_byte_a IS NOT NULL AND one_byte_b IS NOT NULL, cl_jaro_winkler_cut(one_byte_a, one_byte_b, threshold),
     cl_jaro_winkler_cut(a, b, threshold))
);

-- common_start returns the number of leading characters that two strings share, up to 4. Winkler raises a Jaro score by
-- this common start.
CREATE OR REPLACE TEMP FUNCTION common_start(a STRING, b STRING) AS (
  IF(LEFT(a, 1) = LEFT(b, 1),
     IF(LEFT(a, 2) = LEFT(b, 2), IF(LEFT(a, 3) = LEFT(b, 3), IF(LEFT(a, 4) = LEFT(b, 4), 4, 3), 2), 1),
     0)
);

-- jaro_winkler_most returns an upper bound of two strings' Jaro–Winkler score, from their lengths and common start
-- alone. Jaro is at most (2 + r)/3, with r the shorter length divided by the longer. Jaro reaches that bound if every
-- character of the shorter string matches, in order. Winkler then raises the bound by the common start (up to 4
-- characters). If this bound is below a threshold, so is the score.
CREATE OR REPLACE TEMP FUNCTION jaro_winkler_most(a STRING, b STRING) AS (
  (2 + LEAST(LENGTH(a), LENGTH(b)) / GREATEST(LENGTH(a), LENGTH(b), 1)) / 3
    * (1 - CAST(0.1 AS FLOAT64) * common_start(a, b))
    + CAST(0.1 AS FLOAT64) * common_start(a, b)
);

-- name_jw_most returns an upper bound of two names' Jaro–Winkler score. If both names are katakana (both have one-byte
-- copies), the bound comes from the letters they share, and is tighter than jaro_winkler_most's. Jaro's matches pair
-- equal letters, so a pair has no more matches than the letters both names hold, each counted as often as the name that
-- holds it fewer times. The bound counts the distinct letters both names hold (the bits set in both names' letters
-- columns). It adds the smaller of the two names' repeats. A name's repeats are its length less its distinct letters.
-- The bound counts no transpositions. Winkler then raises the bound by the common start, as
-- 1 - (1 - jaro)(1 - 0.1 · start). If either name isn't katakana, the bound is jaro_winkler_most's, from the lengths
-- alone. If the bound is below a threshold, so is the score.
CREATE OR REPLACE TEMP FUNCTION name_jw_most(l ANY TYPE, r ANY TYPE) AS (
  IF(l.person_name__kana_fold_one_byte IS NULL OR r.person_name__kana_fold_one_byte IS NULL,
     jaro_winkler_most(l.person_name__kana_fold, r.person_name__kana_fold),
     1 - (1 - (LEAST(BIT_COUNT(l.person_name__kana_fold_letters_lo & r.person_name__kana_fold_letters_lo)
                     + BIT_COUNT(l.person_name__kana_fold_letters_hi & r.person_name__kana_fold_letters_hi)
                     + LEAST(LENGTH(l.person_name__kana_fold_one_byte) - BIT_COUNT(l.person_name__kana_fold_letters_lo)
                               - BIT_COUNT(l.person_name__kana_fold_letters_hi),
                             LENGTH(r.person_name__kana_fold_one_byte) - BIT_COUNT(r.person_name__kana_fold_letters_lo)
                               - BIT_COUNT(r.person_name__kana_fold_letters_hi)),
                     LENGTH(l.person_name__kana_fold_one_byte), LENGTH(r.person_name__kana_fold_one_byte))
               * (1 / LENGTH(l.person_name__kana_fold_one_byte) + 1 / LENGTH(r.person_name__kana_fold_one_byte))
               + 1) / 3)
         * (1 - CAST(0.1 AS FLOAT64) * common_start(l.person_name__kana_fold, r.person_name__kana_fold)))
);

-- The comparison name tests the person's names as written, then folded (kana_fold), then as read (long_vowel), and last
-- by the folded names' Jaro–Winkler score. It takes two functions, so that Jaro–Winkler is called once a pair.
-- name_score returns the folded names' score, exact from 0.75 up. Below 0.75 it may return 0 instead. It returns NULL
-- if an equality settles the level. The caller computes it once, as the column s_name, and name_level then reads the
-- level from it. name_jw_most's bound is tested against 0.749999, a hair under 0.75, as the cl_* cut tests a score
-- against its threshold, because rapidfuzz's scores are float32.
CREATE OR REPLACE TEMP FUNCTION name_score(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.person_name IS NULL OR r.person_name IS NULL OR l.person_name = r.person_name
      OR l.person_name__kana_fold = r.person_name__kana_fold
      OR l.person_name__kana_fold_long_vowel = r.person_name__kana_fold_long_vowel THEN NULL
    WHEN name_jw_most(l, r) < CAST(0.749999 AS FLOAT64) THEN CAST(0 AS FLOAT64)  -- the bound rules out 0.75
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

-- gamma_name gives the same levels as name_level from the pair alone, with each Jaro–Winkler call in its own CASE
-- branch. The gate (score.sql) calls it on the pairs it samples.
CREATE OR REPLACE TEMP FUNCTION gamma_name(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.person_name IS NULL OR r.person_name IS NULL THEN -1
    WHEN l.person_name = r.person_name THEN 6
    WHEN l.person_name__kana_fold = r.person_name__kana_fold THEN 5
    WHEN l.person_name__kana_fold_long_vowel = r.person_name__kana_fold_long_vowel THEN 4
    WHEN jaro_winkler_of(l.person_name__kana_fold, r.person_name__kana_fold,
                         l.person_name__kana_fold_one_byte, r.person_name__kana_fold_one_byte,
                         CAST(0.95 AS FLOAT64)) >= CAST(0.95 AS FLOAT64) THEN 3
    WHEN l.given_name__kana_fold = r.given_name__kana_fold THEN 2
    WHEN jaro_winkler_of(l.person_name__kana_fold, r.person_name__kana_fold,
                         l.person_name__kana_fold_one_byte, r.person_name__kana_fold_one_byte,
                         CAST(0.75 AS FLOAT64)) >= CAST(0.75 AS FLOAT64) THEN 1
    ELSE 0
  END
);

-- The comparison company tests the companies' names in NFKC form, with their legal forms removed, and folded (the
-- column company_name__nfkc_strip_legal_form_kana_fold).
CREATE OR REPLACE TEMP FUNCTION gamma_company(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN l.company_name IS NULL OR r.company_name IS NULL THEN -1
    WHEN l.company_name__nfkc_strip_legal_form_kana_fold = r.company_name__nfkc_strip_legal_form_kana_fold
      THEN 2  -- exact
    WHEN jaro_winkler_of(l.company_name__nfkc_strip_legal_form_kana_fold,
                         r.company_name__nfkc_strip_legal_form_kana_fold,
                         l.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                         r.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                         CAST(0.8 AS FLOAT64)) >= CAST(0.8 AS FLOAT64) THEN 1  -- JW low
    ELSE 0
  END
);

-- The comparison address is missing only if the address code, the address and the postal code are each missing on
-- one side or both.
CREATE OR REPLACE TEMP FUNCTION gamma_address(l ANY TYPE, r ANY TYPE) AS (
  CASE
    WHEN (l.address_code IS NULL OR r.address_code IS NULL) AND (l.address IS NULL OR r.address IS NULL)
      AND (l.postal_code IS NULL OR r.postal_code IS NULL) THEN -1
    WHEN l.address_code = r.address_code OR l.address__address = r.address__address THEN 3          -- same address
    WHEN CASE  -- address close (two edits at most). The costliest test runs last.
           WHEN l.address__address IS NULL OR r.address__address IS NULL
             OR ABS(LENGTH(l.address__address) - LENGTH(r.address__address)) > 2 THEN FALSE
           WHEN l.address__address_one_byte_hash IS NULL OR r.address__address_one_byte_hash IS NULL
             THEN cl_levenshtein_cut(l.address__address, r.address__address, 2) <= 2
           WHEN cl_levenshtein_cut(l.address__address_one_byte_hash, r.address__address_one_byte_hash, 2) > 2 THEN FALSE
           ELSE cl_levenshtein_cut(l.address__address, r.address__address, 2) <= 2 END THEN 2
    WHEN l.postal_code = r.postal_code THEN 1                                                        -- same postal
    ELSE 0
  END
);

-- one_edit_may is TRUE if a and b may be one edit apart. One edit (a character changed, added or dropped, or two
-- neighbours swapped) leaves whole either the first h characters or the last h, with h = ⌊(the shorter length − 1)/2⌋.
-- So two values one edit apart share their first h characters or their last h. The test uses string equalities alone,
-- so an edit distance is computed only for a pair that passes it. Two random 13-digit IDs rarely pass.
CREATE OR REPLACE TEMP FUNCTION one_edit_may(a STRING, b STRING) AS (
  LEFT(a, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)) = LEFT(b, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2))
  OR RIGHT(a, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)) = RIGHT(b, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2))
);

-- The comparisons phone, cif and birth are exact, or one digit off. phone measures that by Hamming distance, which
-- pads the shorter value at its end. cif and birth use Damerau–Levenshtein, which also counts two swapped neighbours
-- as one edit. Each test has its own CASE branch, because both engines try a CASE's branches in order. So the
-- distance is computed only if the cheaper tests don't settle the level.
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

-- near_name is TRUE if two persons' folded names are at most two edits apart (Damerau–Levenshtein). near_company is
-- TRUE if two companies' names are at most one edit apart (Levenshtein). near_address is TRUE if two addresses score
-- 0.9 or more by Jaro–Winkler, and near_phone if two phones are one digit off (Hamming). Each tests equality first,
-- then the lengths (near_address skips them), and calls the distance last. near_name and near_company compare the
-- one-byte copies if both values have one. Each test has its own CASE branch, so the distance is computed only if the
-- cheaper tests don't settle the answer.
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
    WHEN l.company_name__nfkc_strip_legal_form_kana_fold IS NULL
      OR r.company_name__nfkc_strip_legal_form_kana_fold IS NULL THEN FALSE
    WHEN l.company_name__nfkc_strip_legal_form_kana_fold = r.company_name__nfkc_strip_legal_form_kana_fold THEN TRUE
    WHEN ABS(LENGTH(l.company_name__nfkc_strip_legal_form_kana_fold)
             - LENGTH(r.company_name__nfkc_strip_legal_form_kana_fold)) > 1 THEN FALSE
    ELSE IF(l.company_name__nfkc_strip_legal_form_kana_fold_one_byte IS NOT NULL
              AND r.company_name__nfkc_strip_legal_form_kana_fold_one_byte IS NOT NULL,
            cl_levenshtein_cut(l.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                               r.company_name__nfkc_strip_legal_form_kana_fold_one_byte, 1),
            cl_levenshtein_cut(l.company_name__nfkc_strip_legal_form_kana_fold,
                               r.company_name__nfkc_strip_legal_form_kana_fold, 1)) <= 1
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

-- The table levels lists each comparison's levels, numbered as the functions above number them, with what the fit and
-- the report read of a level. kind is exact (an equality alone), near (a distance or a similarity) or else. position is
-- the comparison's place in the model.
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
