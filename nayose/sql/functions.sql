-- The functions that nayose's SQL calls, each written once, and the comparisons' levels. Every job runs this file
-- first. It has five sections.
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
--    In the comments below, SP stands for Python's whitespace (the characters str.strip removes). The regexes spell
--    it as [\t-\r\x{1c}-\x{1f}\x{85}\p{Z}], \p{Z} being Unicode's space, line and paragraph separators.
--
-- 2. The model's comparisons, which the fit (stage 2) and the scores call. Each compares two records on its fields,
--    and takes both records whole, as rows (x and y). Each returns a gamma, the level the pair lands in. The level is
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
-- 4. The table levels. It lists each comparison's levels as section 2 numbers them, with their labels and agreements.
--    fit.sql reads it.
--
-- 5. The steps that the stages share: pairs_of, which counts the pairs a block's records make, and the steps of the
--    address copy (records.sql).
--
-- Writes: levels (a temporary table).


-- ---------- 1. The intake ----------

-- blank(v) is TRUE if v is empty or holds only spaces (SP, of any width).
CREATE OR REPLACE TEMP FUNCTION blank(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*$'));

-- trimmed(v) returns v without its leading and trailing spaces (SP), as Python's str.strip removes them.
CREATE OR REPLACE TEMP FUNCTION trimmed(v STRING) AS (REGEXP_REPLACE(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]+|[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]+$', ''));

-- The next four functions are read_value's steps after unlisted, in the order it applies them. Each reads its
-- argument once, because a function's argument is copied into every place its body reads it. Their parameters are
-- ANY TYPE because DuckDB binds a typed parameter's argument twice, so each step nested in the next would double the
-- time read_value takes to plan. A step that finds a value missing writes CHR(1) in its place, and read_value makes
-- CHR(1) missing at the end. No other value holds CHR(1) by then, because without_controls removes it.
-- without_controls removes control characters, zero-width characters and BOMs, and makes each run of tabs and line
-- breaks one space.
CREATE OR REPLACE TEMP FUNCTION without_controls(v ANY TYPE) AS (
  REGEXP_REPLACE(REGEXP_REPLACE(v, r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\x{200b}-\x{200d}\x{2060}\x{feff}]', ''),
                 r'[\t\r\n]+', ' ')
);

-- null_token_marked writes CHR(1) for a null token. null_regex is the regex that nayose.null_regex makes of
-- [input] nulls, and it also matches a value of spaces alone. The parameter isn't named nulls, a word BigQuery
-- reserves.
CREATE OR REPLACE TEMP FUNCTION null_token_marked(v ANY TYPE, null_regex ANY TYPE) AS (
  REGEXP_REPLACE(v, null_regex, CHR(1))
);

-- The two number steps change a value only if numeric is TRUE. cut_short_marked writes CHR(1) for a number cut short
-- in E notation (1.23E+11), whose digits are gone, and whole_number writes a whole number written as a float
-- (12345.0) as its digits. If numeric is FALSE, a step's regex is $^, which matches no value it is given (an empty
-- value is CHR(1) by then). whole_number's is ($^), which holds the group that its replacement \1 reads.
CREATE OR REPLACE TEMP FUNCTION cut_short_marked(v ANY TYPE, numeric ANY TYPE) AS (
  REGEXP_REPLACE(v, IF(numeric, r'^[ \x{3000}]*-?\p{Nd}(\.\p{Nd}+)?[eE]\+\p{Nd}+[ \x{3000}]*$', r'$^'), CHR(1))
);

CREATE OR REPLACE TEMP FUNCTION whole_number(v ANY TYPE, numeric ANY TYPE) AS (
  REGEXP_REPLACE(v, IF(numeric, r'^[ \x{3000}]*(-?\p{Nd}+)\.0+[ \x{3000}]*$', r'($^)'), r'\1')
);

-- The next six functions read a value written as a list. unlisted, which read_value calls, returns a plain list's
-- first filled item. It returns any other value as it is, except that an empty or damaged value is missing.
--   A list is plain if JSON reads it as a list of strings, numbers and nulls (["a", 1, null]), or if Python reads it
--   as a list of strings (['a', "b",]). An item is filled if it holds more than spaces, and an escape counts as
--   filled.
--   shortcut: a list that JSON can't read is left as written if a string in it holds a backslash, although Python
--   would decode the escapes. Decode them if a records file ever holds such a list.
--   The regexes are made of these pieces. A JSON string is "(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*". A JSON
--   number is -?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?. A Python string is '…' or "…" without a
--   backslash or a line break, and the regexes write ' as \x{27}. A blank item is "SP*", 'SP*' or null. ws is the
--   space, a tab or a line break, and in a Python list also a form feed. The three plain lists read:
--     code list     SP* [ SP* digits SP* ] SP*
--     JSON list     SP* [ ws (item (ws , ws item)*)? ws ] SP*, each item a JSON string, a JSON number or null
--     Python list   SP* [ ws (string (ws , ws string)* (ws ,)?)? ws ] SP*, each string a Python string
CREATE OR REPLACE TEMP FUNCTION listed_item(v STRING) RETURNS STRING AS (
  -- It returns the first filled item as written, quotes and all, or NULL if no item is filled.
  REGEXP_EXTRACT(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\[[ \t\n\r\x{0c}]*(?:(?:"[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*"|\x{27}[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\x{27}|null)[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*)*("(?:[^"\\]|\\.)*(?:[^"\\\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]|\\.)(?:[^"\\]|\\.)*"|\x{27}[^\x{27}\\\r\n]*[^\x{27}\\\t-\r\x{1c}-\x{1f}\x{85}\p{Z}][^\x{27}\\\r\n]*\x{27}|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
);

-- item_read returns the value of an item that listed_item found. A string loses its quotes, and if it holds a
-- backslash, JSON_VALUE decodes its escapes (\u5927 becomes 大). A number goes through read_value's two number steps,
-- as in a column of numbers. So 12345.0 becomes 12345, a number cut short like 1.23E+11 is missing, and any other
-- stays as written.
CREATE OR REPLACE TEMP FUNCTION item_read(item STRING) RETURNS STRING AS (
  CASE
    WHEN item IS NULL THEN NULL
    WHEN NOT (STARTS_WITH(item, '"') OR STARTS_WITH(item, "'")) THEN  -- the item is a number
      NULLIF(whole_number(cut_short_marked(item, TRUE), TRUE), CHR(1))
    WHEN STRPOS(item, '\\') > 0 THEN JSON_VALUE(item)  -- JSON_VALUE decodes the escapes
    ELSE SUBSTR(item, 2, LENGTH(item) - 2)
  END
);

-- is_code_list, is_json_list and is_python_list are TRUE if v is written as a code list, a JSON list or a Python
-- list, as the comment above listed_item spells them. A code with leading zeros, such as [0708612], isn't JSON.
CREATE OR REPLACE TEMP FUNCTION is_code_list(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\[[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\p{Nd}+[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\][\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*$'));

CREATE OR REPLACE TEMP FUNCTION is_json_list(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\[[ \t\n\r]*(?:(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null)(?:[ \t\n\r]*,[ \t\n\r]*(?:"(?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|null))*)?[ \t\n\r]*\][\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*$'));

CREATE OR REPLACE TEMP FUNCTION is_python_list(v STRING) AS (REGEXP_CONTAINS(v, r'^[\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*\[[ \t\n\r\x{0c}]*(?:(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*")(?:[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*(?:\x{27}[^\x{27}\\\r\n]*\x{27}|"[^"\\\r\n]*"))*(?:[ \t\n\r\x{0c}]*,)?)?[ \t\n\r\x{0c}]*\][\t-\r\x{1c}-\x{1f}\x{85}\p{Z}]*$'));

-- unlisted returns v, or its first filled item if v is a plain list. A code list keeps its digits as written.
CREATE OR REPLACE TEMP FUNCTION unlisted(v STRING) RETURNS STRING AS (
  CASE
    WHEN v IS NULL OR v = '' OR REGEXP_CONTAINS(v, r'\x{fffd}') THEN NULL  -- an empty or damaged value is missing
    WHEN NOT REGEXP_CONTAINS(v, r'\[') THEN v                              -- most values hold no list
    WHEN is_code_list(v) THEN REGEXP_EXTRACT(v, r'(\p{Nd}+)')
    WHEN is_json_list(v) OR is_python_list(v) THEN item_read(listed_item(v))
    ELSE v
  END
);

-- read_value returns a value as read, with section 1's fixes in order: unlisted, then the four steps above. Last,
-- NULLIF makes CHR(1) missing.
CREATE OR REPLACE TEMP FUNCTION read_value(v STRING, numeric BOOL, null_regex STRING) RETURNS STRING AS (
  NULLIF(whole_number(cut_short_marked(null_token_marked(without_controls(unlisted(v)), null_regex), numeric), numeric),
         CHR(1))
);


-- ---------- 2. The comparisons ----------

-- cut_from(t) is a hair under a similarity's threshold t, where a cl_*_cut keeps a score (engines.py's cut twin): a
-- bound tested against it keeps every score that passes t, as rapidfuzz's scores are float32.
CREATE OR REPLACE TEMP FUNCTION cut_from(t FLOAT64) AS (t - CAST(0.000001 AS FLOAT64));

-- jaro_winkler_of returns the Jaro–Winkler score of a and b, exact at the threshold or above: below it, the score may
-- be returned as 0 instead. It scores their one-byte copies (records.sql) if both have one. The score is the same,
-- because Jaro–Winkler tests characters only for equality, and a copy keeps different characters different. On the
-- copies, DuckDB computes the score with its own function.
CREATE OR REPLACE TEMP FUNCTION jaro_winkler_of(a STRING, b STRING, one_byte_a STRING, one_byte_b STRING,
                                                threshold FLOAT64) RETURNS FLOAT64 AS (
  IF(one_byte_a IS NOT NULL AND one_byte_b IS NOT NULL, cl_jaro_winkler_cut(one_byte_a, one_byte_b, threshold),
     cl_jaro_winkler_cut(a, b, threshold))
);

-- The next eight functions bound a Jaro–Winkler score from above: if a bound is below a threshold, so is the score.
-- winkler's and jaro_most's parameters are ANY TYPE, as read_value's steps' are, because their arguments nest.
-- common_start returns the number of leading characters that two strings share, up to 4.
CREATE OR REPLACE TEMP FUNCTION common_start(a STRING, b STRING) AS (
  IF(LEFT(a, 1) = LEFT(b, 1),
     IF(LEFT(a, 2) = LEFT(b, 2), IF(LEFT(a, 3) = LEFT(b, 3), IF(LEFT(a, 4) = LEFT(b, 4), 4, 3), 2), 1),
     0)
);

-- winkler raises a Jaro score by a common start of up to 4 characters, as 1 - (1 - jaro)(1 - 0.1 · start).
CREATE OR REPLACE TEMP FUNCTION winkler(jaro ANY TYPE, start ANY TYPE) AS (
  1 - (1 - jaro) * (1 - CAST(0.1 AS FLOAT64) * start)
);

-- jaro_most returns the Jaro score of two strings of lengths a and b if `matches` of their characters match and none
-- is transposed: (matches/a + matches/b + 1)/3.
CREATE OR REPLACE TEMP FUNCTION jaro_most(matches ANY TYPE, a ANY TYPE, b ANY TYPE) AS (
  (matches * (1 / a + 1 / b) + 1) / 3
);

-- jaro_winkler_most returns an upper bound of two strings' Jaro–Winkler score, from their lengths and common start
-- alone. Jaro is at most (2 + r)/3, with r the shorter length divided by the longer. Jaro reaches that bound if every
-- character of the shorter string matches, in order.
CREATE OR REPLACE TEMP FUNCTION jaro_winkler_most(a STRING, b STRING) AS (
  winkler((2 + LEAST(LENGTH(a), LENGTH(b)) / GREATEST(LENGTH(a), LENGTH(b), 1)) / 3, common_start(a, b))
);

-- letter_count returns how many distinct katakana a name holds: the 1s in its letters columns' masks (records.sql).
CREATE OR REPLACE TEMP FUNCTION letter_count(x ANY TYPE) AS (
  BIT_COUNT(x.person_name__kana_fold_letters_lo) + BIT_COUNT(x.person_name__kana_fold_letters_hi)
);

-- letters_shared returns how many distinct katakana both names hold: the 1s both names' letters masks share.
CREATE OR REPLACE TEMP FUNCTION letters_shared(x ANY TYPE, y ANY TYPE) AS (
  BIT_COUNT(x.person_name__kana_fold_letters_lo & y.person_name__kana_fold_letters_lo)
  + BIT_COUNT(x.person_name__kana_fold_letters_hi & y.person_name__kana_fold_letters_hi)
);

-- matches_most returns the most matches Jaro can find between two katakana names. Jaro's matches pair equal letters,
-- so a pair has no more matches than the letters both names hold, each counted as often as the name that holds it
-- fewer times. So the bound is the distinct letters both names hold, plus the smaller of the two names' repeats, and
-- no more than the shorter name's length. A name's repeats are its length less its distinct letters.
CREATE OR REPLACE TEMP FUNCTION matches_most(x ANY TYPE, y ANY TYPE) AS (
  LEAST(letters_shared(x, y) + LEAST(LENGTH(x.person_name__kana_fold_one_byte) - letter_count(x),
                                     LENGTH(y.person_name__kana_fold_one_byte) - letter_count(y)),
        LENGTH(x.person_name__kana_fold_one_byte), LENGTH(y.person_name__kana_fold_one_byte))
);

-- name_jw_most returns an upper bound of two names' Jaro–Winkler score. If both names are katakana (both have one-byte
-- copies), the bound is the Jaro of matches_most's matches, which is tighter than jaro_winkler_most's, raised by the
-- common start. If either name isn't katakana, the bound is jaro_winkler_most's, from the lengths alone.
CREATE OR REPLACE TEMP FUNCTION name_jw_most(x ANY TYPE, y ANY TYPE) AS (
  IF(x.person_name__kana_fold_one_byte IS NULL OR y.person_name__kana_fold_one_byte IS NULL,
     jaro_winkler_most(x.person_name__kana_fold, y.person_name__kana_fold),
     winkler(jaro_most(matches_most(x, y), LENGTH(x.person_name__kana_fold_one_byte),
                       LENGTH(y.person_name__kana_fold_one_byte)),
             common_start(x.person_name__kana_fold, y.person_name__kana_fold)))
);

-- The comparison name tests the person's names as written, then folded (kana_fold), then as read (long_vowel), and last
-- by the folded names' Jaro–Winkler score. It takes two functions, so that Jaro–Winkler is called once a pair.
-- name_score returns the folded names' score, exact from 0.75 up. Below 0.75 it may return 0 instead. It returns NULL
-- if an equality settles the level. The caller computes it once, as the column s_name, and name_level then reads the
-- level from it. name_jw_most's bound is tested against cut_from(0.75), as the cl_* cut tests a score.
CREATE OR REPLACE TEMP FUNCTION name_score(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.person_name IS NULL OR y.person_name IS NULL OR x.person_name = y.person_name
      OR x.person_name__kana_fold = y.person_name__kana_fold
      OR x.person_name__kana_fold_long_vowel = y.person_name__kana_fold_long_vowel THEN NULL
    WHEN name_jw_most(x, y) < cut_from(CAST(0.75 AS FLOAT64)) THEN CAST(0 AS FLOAT64)  -- the bound rules out 0.75
    ELSE jaro_winkler_of(x.person_name__kana_fold, y.person_name__kana_fold, x.person_name__kana_fold_one_byte,
                         y.person_name__kana_fold_one_byte, CAST(0.75 AS FLOAT64))
  END
);

CREATE OR REPLACE TEMP FUNCTION name_level(x ANY TYPE, y ANY TYPE, s FLOAT64) AS (
  CASE
    WHEN x.person_name IS NULL OR y.person_name IS NULL THEN -1
    WHEN x.person_name = y.person_name THEN 6                                                -- exact
    WHEN x.person_name__kana_fold = y.person_name__kana_fold THEN 5                          -- fold exact
    WHEN x.person_name__kana_fold_long_vowel = y.person_name__kana_fold_long_vowel THEN 4    -- same reading
    WHEN s >= CAST(0.95 AS FLOAT64) THEN 3                                                   -- fold JW high
    WHEN x.given_name__kana_fold = y.given_name__kana_fold THEN 2                            -- given name
    WHEN s >= CAST(0.75 AS FLOAT64) THEN 1                                                   -- fold JW low
    ELSE 0
  END
);

-- The comparison company tests the companies' names in NFKC form, with their legal forms removed, and folded (the
-- column company_name__nfkc_strip_legal_form_kana_fold).
CREATE OR REPLACE TEMP FUNCTION gamma_company(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.company_name IS NULL OR y.company_name IS NULL THEN -1
    WHEN x.company_name__nfkc_strip_legal_form_kana_fold = y.company_name__nfkc_strip_legal_form_kana_fold
      THEN 2  -- exact
    WHEN jaro_winkler_of(x.company_name__nfkc_strip_legal_form_kana_fold,
                         y.company_name__nfkc_strip_legal_form_kana_fold,
                         x.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                         y.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                         CAST(0.8 AS FLOAT64)) >= CAST(0.8 AS FLOAT64) THEN 1  -- JW low
    ELSE 0
  END
);

-- address_close is TRUE if two addresses are two edits apart at most (Levenshtein). The costliest test runs last.
CREATE OR REPLACE TEMP FUNCTION address_close(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.address__address IS NULL OR y.address__address IS NULL
      OR ABS(LENGTH(x.address__address) - LENGTH(y.address__address)) > 2 THEN FALSE
    WHEN x.address__address_one_byte_hash IS NULL OR y.address__address_one_byte_hash IS NULL
      THEN cl_levenshtein_cut(x.address__address, y.address__address, 2) <= 2
    WHEN cl_levenshtein_cut(x.address__address_one_byte_hash, y.address__address_one_byte_hash, 2) > 2 THEN FALSE
    ELSE cl_levenshtein_cut(x.address__address, y.address__address, 2) <= 2
  END
);

-- The comparison address is missing only if the address code, the address and the postal code are each missing on
-- one side or both.
CREATE OR REPLACE TEMP FUNCTION gamma_address(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN (x.address_code IS NULL OR y.address_code IS NULL) AND (x.address IS NULL OR y.address IS NULL)
      AND (x.postal_code IS NULL OR y.postal_code IS NULL) THEN -1
    WHEN x.address_code = y.address_code OR x.address__address = y.address__address THEN 3          -- same address
    WHEN address_close(x, y) THEN 2                                                                  -- address close
    WHEN x.postal_code = y.postal_code THEN 1                                                        -- same postal
    ELSE 0
  END
);

-- may_be_one_edit is TRUE if a and b may be one edit apart. One edit (a character changed, added or dropped, or two
-- neighbours swapped) changes the length by one at most, and leaves whole either the first h characters or the last h,
-- with h = ⌊(the shorter length − 1)/2⌋. So two values one edit apart differ in length by one at most, and share
-- their first h characters or their last h. The test uses lengths and string equalities alone, so an edit distance
-- is computed only for a pair that passes it. Two random 13-digit IDs rarely pass.
CREATE OR REPLACE TEMP FUNCTION may_be_one_edit(a STRING, b STRING) AS (
  ABS(LENGTH(a) - LENGTH(b)) <= 1
  AND (LEFT(a, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)) = LEFT(b, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2))
       OR RIGHT(a, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)) = RIGHT(b, DIV(LEAST(LENGTH(a), LENGTH(b)) - 1, 2)))
);

-- The comparisons phone, cif and birth are exact, or one digit off. phone measures that by Hamming distance, which
-- pads the shorter value at its end. cif and birth use Damerau–Levenshtein, which also counts two swapped neighbours
-- as one edit. Each test has its own CASE branch, because both engines try a CASE's branches in order. So the
-- distance is computed only if the cheaper tests don't settle the level.
CREATE OR REPLACE TEMP FUNCTION gamma_phone(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.phone IS NULL OR y.phone IS NULL THEN -1
    WHEN x.phone = y.phone THEN 2                                                                      -- exact
    WHEN NOT may_be_one_edit(x.phone, y.phone) THEN 0
    WHEN cl_hamming_cut(x.phone, y.phone, 1) <= 1 THEN 1                                               -- one digit off
    ELSE 0
  END
);

CREATE OR REPLACE TEMP FUNCTION gamma_cif(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.customer_id IS NULL OR y.customer_id IS NULL THEN -1
    WHEN x.customer_id = y.customer_id THEN 2                                                          -- exact
    WHEN NOT may_be_one_edit(x.customer_id, y.customer_id) THEN 0
    WHEN cl_damerau_levenshtein_cut(x.customer_id, y.customer_id, 1) <= 1 THEN 1                      -- one digit off
    ELSE 0
  END
);

CREATE OR REPLACE TEMP FUNCTION gamma_birth(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.birth_date IS NULL OR y.birth_date IS NULL THEN -1
    WHEN x.birth_date = y.birth_date THEN 2                                                            -- exact
    WHEN NOT may_be_one_edit(x.birth_date, y.birth_date) THEN 0
    WHEN cl_damerau_levenshtein_cut(x.birth_date, y.birth_date, 1) <= 1 THEN 1                        -- one digit off
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
CREATE OR REPLACE TEMP FUNCTION near_name(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.person_name__kana_fold IS NULL OR y.person_name__kana_fold IS NULL THEN FALSE
    WHEN x.person_name__kana_fold = y.person_name__kana_fold THEN TRUE
    WHEN ABS(LENGTH(x.person_name__kana_fold) - LENGTH(y.person_name__kana_fold)) > 2 THEN FALSE
    ELSE IF(x.person_name__kana_fold_one_byte IS NOT NULL AND y.person_name__kana_fold_one_byte IS NOT NULL,
            cl_damerau_levenshtein_cut(x.person_name__kana_fold_one_byte, y.person_name__kana_fold_one_byte, 2),
            cl_damerau_levenshtein_cut(x.person_name__kana_fold, y.person_name__kana_fold, 2)) <= 2
  END
);

CREATE OR REPLACE TEMP FUNCTION near_company(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.company_name__nfkc_strip_legal_form_kana_fold IS NULL
      OR y.company_name__nfkc_strip_legal_form_kana_fold IS NULL THEN FALSE
    WHEN x.company_name__nfkc_strip_legal_form_kana_fold = y.company_name__nfkc_strip_legal_form_kana_fold THEN TRUE
    WHEN ABS(LENGTH(x.company_name__nfkc_strip_legal_form_kana_fold)
             - LENGTH(y.company_name__nfkc_strip_legal_form_kana_fold)) > 1 THEN FALSE
    ELSE IF(x.company_name__nfkc_strip_legal_form_kana_fold_one_byte IS NOT NULL
              AND y.company_name__nfkc_strip_legal_form_kana_fold_one_byte IS NOT NULL,
            cl_levenshtein_cut(x.company_name__nfkc_strip_legal_form_kana_fold_one_byte,
                               y.company_name__nfkc_strip_legal_form_kana_fold_one_byte, 1),
            cl_levenshtein_cut(x.company_name__nfkc_strip_legal_form_kana_fold,
                               y.company_name__nfkc_strip_legal_form_kana_fold, 1)) <= 1
  END
);

CREATE OR REPLACE TEMP FUNCTION near_address(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.address__address IS NULL OR y.address__address IS NULL THEN FALSE
    WHEN x.address__address = y.address__address THEN TRUE
    ELSE cl_jaro_winkler_cut(x.address__address, y.address__address, CAST(0.9 AS FLOAT64)) >= CAST(0.9 AS FLOAT64)
  END
);

CREATE OR REPLACE TEMP FUNCTION near_phone(x ANY TYPE, y ANY TYPE) AS (
  CASE
    WHEN x.phone IS NULL OR y.phone IS NULL THEN FALSE
    WHEN x.phone = y.phone THEN TRUE
    WHEN NOT may_be_one_edit(x.phone, y.phone) THEN FALSE
    ELSE cl_hamming_cut(x.phone, y.phone, 1) <= 1
  END
);


-- ---------- 4. The levels ----------

-- The table levels lists each comparison's levels, numbered as the functions above number them, with what the fit and
-- the report read of a level. agreement is exact (an equality alone), fuzzy (a distance or a similarity) or else.
-- position is the comparison's place in the model.
CREATE OR REPLACE TEMP TABLE levels AS
SELECT * FROM UNNEST([
  STRUCT(1 AS position, 'name' AS comparison, 6 AS gamma, 'exact' AS label, 'exact' AS agreement),
  STRUCT(1, 'name', 5, 'fold exact', 'exact'),
  STRUCT(1, 'name', 4, 'same reading', 'exact'),
  STRUCT(1, 'name', 3, 'fold JW high', 'fuzzy'),
  STRUCT(1, 'name', 2, 'given name', 'exact'),
  STRUCT(1, 'name', 1, 'fold JW low', 'fuzzy'),
  STRUCT(1, 'name', 0, 'else', 'else'),
  STRUCT(2, 'company', 2, 'exact', 'exact'),
  STRUCT(2, 'company', 1, 'JW low', 'fuzzy'),
  STRUCT(2, 'company', 0, 'else', 'else'),
  STRUCT(3, 'address', 3, 'same address', 'exact'),
  STRUCT(3, 'address', 2, 'address close', 'fuzzy'),
  STRUCT(3, 'address', 1, 'same postal', 'exact'),
  STRUCT(3, 'address', 0, 'else', 'else'),
  STRUCT(4, 'phone', 2, 'exact', 'exact'),
  STRUCT(4, 'phone', 1, 'one digit off', 'fuzzy'),
  STRUCT(4, 'phone', 0, 'else', 'else'),
  STRUCT(5, 'cif', 2, 'exact', 'exact'),
  STRUCT(5, 'cif', 1, 'one digit off', 'fuzzy'),
  STRUCT(5, 'cif', 0, 'else', 'else'),
  STRUCT(6, 'birth', 2, 'exact', 'exact'),
  STRUCT(6, 'birth', 1, 'one digit off', 'fuzzy'),
  STRUCT(6, 'birth', 0, 'else', 'else')
]);


-- ---------- 5. The steps that the stages share ----------

-- pairs_of(n) returns the number of pairs that n records make, n(n − 1)/2.
CREATE OR REPLACE TEMP FUNCTION pairs_of(n INT64) AS (DIV(n * (n - 1), 2));

-- The address copy's steps (records.sql), on an address in NFKC form. numbers_dashed writes 丁目, 番 or 番地 after a
-- number as a dash, and drops 号 after a number. up_to_street_number keeps the address up to the first space after
-- the street number, which drops the building and room.
CREATE OR REPLACE TEMP FUNCTION numbers_dashed(a STRING) AS (
  REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(a, r'(\d+)丁目', r'\1-'), r'(\d+)番地?', r'\1-'), r'(\d+)号', r'\1')
);

CREATE OR REPLACE TEMP FUNCTION up_to_street_number(a STRING) AS (REGEXP_REPLACE(a, r'^(.*?[0-9][^ ]*) .*$', r'\1'));
