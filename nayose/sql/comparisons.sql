-- The model's comparisons: how two records compare, field by field. Each is a gamma, the level a pair lands in: -1
-- missing (a side empty), then its levels from the highest down, 0 the else level. The fit (fit.sql, u.sql) and the
-- scores (score.sql) call these, so each comparison is written once. The cl_* functions compare by character
-- (engines.py: JavaScript in BigQuery, rapidfuzz in DuckDB); a similarity passes at its threshold or above, a
-- distance at its threshold or below. An edit distance is never less than the two lengths' difference, so that is
-- tested first, and so is the distance of the strings' one_byte_hash copies (records.sql), never more than theirs: the
-- same levels, without the call where it can't pass. O(L²) a pair for a fuzzy level, O(L) otherwise.


-- Jaro–Winkler on the two strings' one-byte copies where both have one (records.sql), else on the strings: the same
-- score (it compares characters only for equality, and a copy keeps them apart), which DuckDB then finds natively.
CREATE OR REPLACE TEMP FUNCTION jaro_winkler_of(a STRING, b STRING, one_byte_a STRING, one_byte_b STRING, threshold FLOAT64) RETURNS FLOAT64 AS (
  IF(one_byte_a IS NOT NULL AND one_byte_b IS NOT NULL, cl_jaro_winkler_cut(one_byte_a, one_byte_b, threshold), cl_jaro_winkler_cut(a, b, threshold))
);

-- name: the person's name as written, folded (kana_fold), read alike (long_vowel), then near
CREATE OR REPLACE TEMP FUNCTION gamma_name(name_l STRING, name_r STRING, fold_l STRING, fold_r STRING, reading_l STRING, reading_r STRING,
                                given_l STRING, given_r STRING, one_byte_l STRING, one_byte_r STRING) RETURNS INT64 AS (
  CASE
    WHEN name_l IS NULL OR name_r IS NULL THEN -1
    WHEN name_l = name_r THEN 6                                                          -- exact
    WHEN fold_l = fold_r THEN 5                                                          -- fold exact
    WHEN reading_l = reading_r THEN 4                                                    -- same reading
    WHEN jaro_winkler_of(fold_l, fold_r, one_byte_l, one_byte_r, CAST(0.95 AS FLOAT64)) >= CAST(0.95 AS FLOAT64) THEN 3  -- fold JW high
    WHEN given_l = given_r THEN 2                                                        -- given name
    WHEN jaro_winkler_of(fold_l, fold_r, one_byte_l, one_byte_r, CAST(0.75 AS FLOAT64)) >= CAST(0.75 AS FLOAT64) THEN 1  -- fold JW low
    ELSE 0
  END
);

-- company: the company's name, its legal form gone and folded (company_name__nfkc_strip_legal_form_kana_fold)
CREATE OR REPLACE TEMP FUNCTION gamma_company(name_l STRING, name_r STRING, plain_l STRING, plain_r STRING, one_byte_l STRING, one_byte_r STRING) RETURNS INT64 AS (
  CASE
    WHEN name_l IS NULL OR name_r IS NULL THEN -1
    WHEN plain_l = plain_r THEN 2                                                        -- exact
    WHEN jaro_winkler_of(plain_l, plain_r, one_byte_l, one_byte_r, CAST(0.8 AS FLOAT64)) >= CAST(0.8 AS FLOAT64) THEN 1  -- JW low
    ELSE 0
  END
);

-- address: missing only when the address code, the address and the postal code are all missing on a side
CREATE OR REPLACE TEMP FUNCTION gamma_address(code_l STRING, code_r STRING, address_l STRING, address_r STRING, postal_l STRING, postal_r STRING,
                                   normal_l STRING, normal_r STRING, hash_l STRING, hash_r STRING) RETURNS INT64 AS (
  CASE
    WHEN (code_l IS NULL OR code_r IS NULL) AND (address_l IS NULL OR address_r IS NULL) AND (postal_l IS NULL OR postal_r IS NULL) THEN -1
    WHEN code_l = code_r OR normal_l = normal_r THEN 3                                   -- same address
    WHEN ABS(LENGTH(normal_l) - LENGTH(normal_r)) <= 2 AND (hash_l IS NULL OR hash_r IS NULL OR cl_levenshtein_cut(hash_l, hash_r, 2) <= 2)
      AND cl_levenshtein_cut(normal_l, normal_r, 2) <= 2 THEN 2                         -- address close
    WHEN postal_l = postal_r THEN 1                                                      -- same postal
    ELSE 0
  END
);

-- phone, cif, birth: equal, or one digit off (Hamming pads the shorter value at its end; Damerau–Levenshtein also
-- counts two neighbours swapped as one edit)
CREATE OR REPLACE TEMP FUNCTION gamma_phone(phone_l STRING, phone_r STRING) RETURNS INT64 AS (
  CASE
    WHEN phone_l IS NULL OR phone_r IS NULL THEN -1
    WHEN phone_l = phone_r THEN 2                                                        -- exact
    WHEN ABS(LENGTH(phone_l) - LENGTH(phone_r)) <= 1 AND cl_hamming_cut(phone_l, phone_r, 1) <= 1 THEN 1  -- one digit off
    ELSE 0
  END
);

CREATE OR REPLACE TEMP FUNCTION gamma_cif(cif_l STRING, cif_r STRING) RETURNS INT64 AS (
  CASE
    WHEN cif_l IS NULL OR cif_r IS NULL THEN -1
    WHEN cif_l = cif_r THEN 2                                                            -- exact
    WHEN ABS(LENGTH(cif_l) - LENGTH(cif_r)) <= 1 AND cl_damerau_levenshtein_cut(cif_l, cif_r, 1) <= 1 THEN 1  -- one digit off
    ELSE 0
  END
);

CREATE OR REPLACE TEMP FUNCTION gamma_birth(birth_l STRING, birth_r STRING) RETURNS INT64 AS (
  CASE
    WHEN birth_l IS NULL OR birth_r IS NULL THEN -1
    WHEN birth_l = birth_r THEN 2                                                        -- exact
    WHEN ABS(LENGTH(birth_l) - LENGTH(birth_r)) <= 1 AND cl_damerau_levenshtein_cut(birth_l, birth_r, 1) <= 1 THEN 1  -- one digit off
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
