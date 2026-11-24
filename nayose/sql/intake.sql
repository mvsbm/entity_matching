-- Stage 1's first step, the intake: each value of the input files as read, what loses nothing fixed and counted,
-- never a value. O(bytes).
--
-- Here: the functions the intake applies. nayose.read applies them to every column of the file (its columns are its
-- own, so that statement is written for each file): raw (the files, every column as text) → input (each value read)
-- and intake (what was fixed: how many values, never one).
--
-- What is fixed, in order:
--   damaged       a value holding U+FFFD (bytes decoded wrong upstream, or bytes that aren't UTF-8): missing
--   lists         a value written as a list of plain items (["8700848"], ['大分市'], [0708612], a Parquet list
--                 column): its first filled item; none filled, missing
--   first of several   the same, when it lists several: the rest dropped
--   controls      control characters, zero-width characters and BOMs removed; tabs and line breaks one space
--   placeholders  a value written as a placeholder null ([input] nulls), or of spaces alone (any width): missing
--   numbers       in a column of numbers, a whole number a spreadsheet wrote as a float (12345.0) as its digits, and
--                 one cut short in E notation (1.23E+11: its digits are gone) missing
--
-- Spaces: SP below is Python's whitespace (str.strip): \t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}
-- \x{2028}\x{2029}\x{202f}\x{205f}\x{3000}.


-- A column of numbers: half its filled values digits, a point, an exponent's E+ and a leading minus aside. Each value:
-- NULL not filled, 1 a number, 0 not one.
CREATE TEMP FUNCTION numberlike(v STRING) RETURNS INT64 AS (
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
CREATE TEMP FUNCTION listed_item(v STRING) RETURNS STRING AS (
  -- the first filled item, as written (quotes and all): NULL when no item is filled
  REGEXP_EXTRACT(v, r'^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\[[ \t\n\r\x{0c}]*(?:(?:"[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*"|\x{27}[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*\x{27}|null)[ \t\n\r\x{0c}]*,[ \t\n\r\x{0c}]*)*("(?:[^"\\]|\\.)*(?:[^"\\\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]|\\.)(?:[^"\\]|\\.)*"|\x{27}[^\x{27}\\\r\n]*[^\x{27}\\\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}][^\x{27}\\\r\n]*\x{27}|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
);

CREATE TEMP FUNCTION item_read(item STRING) RETURNS STRING AS (
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

CREATE TEMP FUNCTION listed(v STRING) RETURNS STRUCT<v STRING, fixed STRING> AS (
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
CREATE TEMP FUNCTION settled(v STRING, fixed STRING, numeric BOOL, nulls ARRAY<STRING>) RETURNS STRUCT<v STRING, fixed STRING> AS (
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

CREATE TEMP FUNCTION tidied(v STRING, fixed STRING, numeric BOOL, nulls ARRAY<STRING>) RETURNS STRUCT<v STRING, fixed STRING> AS (
  CASE
    WHEN v IS NULL THEN STRUCT(CAST(NULL AS STRING) AS v, fixed AS fixed)
    WHEN REGEXP_CONTAINS(v, r'[\x00-\x1f\x7f-\x9f\x{200b}-\x{200d}\x{2060}\x{feff}]')  -- controls, tabs and breaks: removed, a space
      THEN settled(REGEXP_REPLACE(REGEXP_REPLACE(v, r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\x{200b}-\x{200d}\x{2060}\x{feff}]', ''), r'[\t\r\n]+', ' '),
                   'controls', numeric, nulls)
    ELSE settled(v, fixed, numeric, nulls)
  END
);
