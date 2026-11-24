-- u: how often two different customers land in each level of each comparison (comparisons.sql), measured on the
-- records of the table u_records: the fit's sample (fit.sql), then the file to be scored. Counts only, every one an
-- exact integer; nayose.em makes them shares, as er/match.py's exact_u and sample_u do.
--
-- A level of equality (and a near level of one edit after its column's equality) is counted exactly from how many
-- records hold each value, never pair by pair: a sample would miss an agreement rarer than one pair in a billion.
-- O(N) a column set, O(U·L²) for a near level's U values. The rest is Splink's random sample: the records whose hash
-- falls in the share that gives about @max_pairs pairs, and every pair of them. O(max_pairs · K).
--
-- Values: @draw (whether to sample: the share is under 1), @cut (the hash's cut: share · 10⁹), @seed.
-- Writes: u_outside, u_counted, u_near, u_sampled, u_filled.


-- 1. Each comparison's pairs outside its missing level: every pair, less those where each of its columns is empty on
--    a side. A record's mask: which of the comparison's columns it fills.
CREATE OR REPLACE TEMP TABLE u_masks AS
SELECT 'name' AS comparison, IF(person_name IS NOT NULL, 1, 0) AS mask, COUNT(*) AS n FROM u_records GROUP BY 1, 2
UNION ALL SELECT 'company', IF(company_name IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2
UNION ALL SELECT 'address', IF(address_code IS NOT NULL, 1, 0) + IF(address IS NOT NULL, 2, 0) + IF(postal_code IS NOT NULL, 4, 0), COUNT(*) FROM u_records GROUP BY 1, 2
UNION ALL SELECT 'phone', IF(phone IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2
UNION ALL SELECT 'cif', IF(customer_id IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2
UNION ALL SELECT 'birth', IF(birth_date IS NOT NULL, 1, 0), COUNT(*) FROM u_records GROUP BY 1, 2;

CREATE OR REPLACE TABLE u_outside AS
WITH every AS (SELECT DIV(COUNT(*) * (COUNT(*) - 1), 2) AS pairs FROM u_records),
missing AS (  -- two masks sharing no filled column: a pair of their records is missing
  SELECT a.comparison, SUM(IF(a.mask = b.mask, DIV(a.n * (a.n - 1), 2), a.n * b.n)) AS pairs
  FROM u_masks AS a JOIN u_masks AS b ON a.comparison = b.comparison AND a.mask <= b.mask AND (a.mask & b.mask) = 0
  GROUP BY a.comparison
)
SELECT c.comparison, every.pairs - COALESCE(missing.pairs, 0) AS pairs
FROM (SELECT DISTINCT comparison FROM u_masks) AS c CROSS JOIN every LEFT JOIN missing USING (comparison);


-- 2. The levels of equality, from the pairs equal on a set of columns (all filled): Σ n(n−1)/2 over its values.
--    A level that follows others counts the pairs equal on it and on none before it (inclusion–exclusion).
CREATE OR REPLACE TEMP TABLE u_agree AS
SELECT
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE person_name IS NOT NULL GROUP BY person_name)) AS name_,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE person_name__kana_fold IS NOT NULL GROUP BY person_name__kana_fold)) AS fold_,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE person_name__kana_fold_long_vowel IS NOT NULL GROUP BY person_name__kana_fold_long_vowel)) AS reading_,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE person_name IS NOT NULL AND person_name__kana_fold IS NOT NULL
                                         GROUP BY person_name, person_name__kana_fold)) AS name_fold,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE person_name IS NOT NULL AND person_name__kana_fold_long_vowel IS NOT NULL
                                         GROUP BY person_name, person_name__kana_fold_long_vowel)) AS name_reading,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE person_name__kana_fold IS NOT NULL AND person_name__kana_fold_long_vowel IS NOT NULL
                                         GROUP BY person_name__kana_fold, person_name__kana_fold_long_vowel)) AS fold_reading,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE person_name IS NOT NULL AND person_name__kana_fold IS NOT NULL
                                         AND person_name__kana_fold_long_vowel IS NOT NULL
                                         GROUP BY person_name, person_name__kana_fold, person_name__kana_fold_long_vowel)) AS name_fold_reading,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE company_name__nfkc_strip_legal_form_kana_fold IS NOT NULL
                                         GROUP BY company_name__nfkc_strip_legal_form_kana_fold)) AS company_,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE address_code IS NOT NULL GROUP BY address_code)) AS code_,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE address__address IS NOT NULL GROUP BY address__address)) AS normal_,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE address_code IS NOT NULL AND address__address IS NOT NULL
                                         GROUP BY address_code, address__address)) AS code_normal,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE phone IS NOT NULL GROUP BY phone)) AS phone_,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE customer_id IS NOT NULL GROUP BY customer_id)) AS cif_,
  (SELECT SUM(DIV(n * (n - 1), 2)) FROM (SELECT COUNT(*) AS n FROM u_records WHERE birth_date IS NOT NULL GROUP BY birth_date)) AS birth_;

-- each comparison's levels of equality, up to its first fuzzy level: after it, a level of equality isn't counted
CREATE OR REPLACE TABLE u_counted AS
SELECT x.comparison, x.label, x.pairs
FROM u_agree AS a,
  UNNEST([
    STRUCT('name' AS comparison, 'exact' AS label, COALESCE(a.name_, 0) AS pairs),
    STRUCT('name', 'fold exact', COALESCE(a.fold_, 0) - COALESCE(a.name_fold, 0)),
    STRUCT('name', 'same reading', COALESCE(a.reading_, 0) - COALESCE(a.name_reading, 0) - COALESCE(a.fold_reading, 0) + COALESCE(a.name_fold_reading, 0)),
    STRUCT('company', 'exact', COALESCE(a.company_, 0)),
    STRUCT('address', 'same address', COALESCE(a.code_, 0) + COALESCE(a.normal_, 0) - COALESCE(a.code_normal, 0)),
    STRUCT('phone', 'exact', COALESCE(a.phone_, 0)),
    STRUCT('cif', 'exact', COALESCE(a.cif_, 0)),
    STRUCT('birth', 'exact', COALESCE(a.birth_, 0))
  ]) AS x;


-- 3. One edit after equality, by keys, never pair by pair: values of one length one substitution apart share exactly
--    one key (the value without its i-th character, at i), two neighbours swapped apart exactly one (Damerau: the
--    pair in order, at i), so a key's records pair (Σn)² − Σn² over 2 ways; a value one character longer is one
--    deletion away (Hamming, which pads the shorter, its last character), joined on the shorter values.
CREATE OR REPLACE TEMP TABLE u_values AS
SELECT 'phone' AS comparison, phone AS x, COUNT(*) AS n, LENGTH(phone) AS len FROM u_records WHERE phone IS NOT NULL GROUP BY phone
UNION ALL SELECT 'cif', customer_id, COUNT(*), LENGTH(customer_id) FROM u_records WHERE customer_id IS NOT NULL GROUP BY customer_id
UNION ALL SELECT 'birth', birth_date, COUNT(*), LENGTH(birth_date) FROM u_records WHERE birth_date IS NOT NULL GROUP BY birth_date;

CREATE OR REPLACE TEMP TABLE u_at AS
SELECT v.comparison, v.x, v.n, v.len, i FROM u_values AS v, UNNEST(GENERATE_ARRAY(1, v.len)) AS i;

CREATE OR REPLACE TABLE u_near AS
WITH substituted AS (
  SELECT comparison, SUM(DIV(s * s - ss, 2)) AS pairs
  FROM (SELECT comparison, SUM(n) AS s, SUM(n * n) AS ss FROM u_at GROUP BY comparison, len, i, SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1))
  GROUP BY comparison
),
swapped AS (
  SELECT comparison, SUM(DIV(s * s - ss, 2)) AS pairs
  FROM (SELECT comparison, SUM(n) AS s, SUM(n * n) AS ss FROM u_at
        WHERE comparison IN ('cif', 'birth') AND i < len AND SUBSTR(x, i, 1) <> SUBSTR(x, i + 1, 1)
        GROUP BY comparison, len, i,
                 SUBSTR(x, 1, i - 1) || LEAST(SUBSTR(x, i, 1), SUBSTR(x, i + 1, 1)) || GREATEST(SUBSTR(x, i, 1), SUBSTR(x, i + 1, 1)) || SUBSTR(x, i + 2))
  GROUP BY comparison
),
shorter AS (  -- each value with a character deleted: Hamming its last; else each, a run of equal characters once
  SELECT comparison, x, n, len, SUBSTR(x, 1, len - 1) AS d FROM u_values WHERE comparison = 'phone'
  UNION ALL
  SELECT comparison, x, n, len, SUBSTR(x, 1, i - 1) || SUBSTR(x, i + 1) FROM u_values, UNNEST(GENERATE_ARRAY(1, len + 1)) AS i
  WHERE comparison <> 'phone' AND (i = 1 OR i > len OR SUBSTR(x, i - 1, 1) <> SUBSTR(x, i, 1))
),
longer AS (
  SELECT comparison, SUM(nn) AS pairs
  FROM (SELECT DISTINCT a.comparison, a.x AS ax, b.x AS bx, a.n * b.n AS nn FROM shorter AS a JOIN u_values AS b
        ON b.comparison = a.comparison AND b.x = a.d AND b.len = a.len - 1)
  GROUP BY comparison
)
SELECT c.comparison, 'one digit off' AS label, COALESCE(s.pairs, 0) + COALESCE(w.pairs, 0) + COALESCE(l.pairs, 0) AS pairs
FROM (SELECT 'phone' AS comparison UNION ALL SELECT 'cif' UNION ALL SELECT 'birth') AS c
LEFT JOIN substituted AS s ON s.comparison = c.comparison
LEFT JOIN swapped AS w ON w.comparison = c.comparison
LEFT JOIN longer AS l ON l.comparison = c.comparison;


-- 4. The rest sampled, as Splink samples: the records whose hash of ID and seed falls under the cut, every pair of
--    them, each pair's level of each comparison, counted. A comparison counted to its else level (each of its levels
--    counted, pairs left for its else level) isn't sampled.
CREATE OR REPLACE TEMP TABLE u_plan AS
WITH counted AS (
  SELECT o.comparison, NOT (c.pairs > 0 AND n.pairs > 0 AND c.pairs + n.pairs < o.pairs) AS sampled
  FROM u_outside AS o
  JOIN u_counted AS c ON c.comparison = o.comparison AND c.label = 'exact'
  JOIN u_near AS n ON n.comparison = o.comparison
)
SELECT
  COALESCE(LOGICAL_OR(comparison = 'phone' AND sampled), TRUE) AS phone,
  COALESCE(LOGICAL_OR(comparison = 'cif' AND sampled), TRUE) AS cif,
  COALESCE(LOGICAL_OR(comparison = 'birth' AND sampled), TRUE) AS birth
FROM counted;

CREATE OR REPLACE TEMP TABLE u_drawn AS
SELECT * FROM u_records WHERE NOT @draw OR MOD(er_hash(id || '_' || @seed), 1000000000) < @cut;

CREATE OR REPLACE TEMP TABLE u_pairs AS
SELECT
  gamma_name(l.person_name, r.person_name, l.person_name__kana_fold, r.person_name__kana_fold,
             l.person_name__kana_fold_long_vowel, r.person_name__kana_fold_long_vowel, l.given_name__kana_fold, r.given_name__kana_fold,
             l.person_name__kana_fold_one_byte, r.person_name__kana_fold_one_byte) AS name,
  gamma_company(l.company_name, r.company_name, l.company_name__nfkc_strip_legal_form_kana_fold, r.company_name__nfkc_strip_legal_form_kana_fold,
                l.company_name__nfkc_strip_legal_form_kana_fold_one_byte, r.company_name__nfkc_strip_legal_form_kana_fold_one_byte) AS company,
  gamma_address(l.address_code, r.address_code, l.address, r.address, l.postal_code, r.postal_code, l.address__address, r.address__address,
                l.address__address_one_byte_hash, r.address__address_one_byte_hash) AS address,
  IF(plan.phone, gamma_phone(l.phone, r.phone), NULL) AS phone,
  IF(plan.cif, gamma_cif(l.customer_id, r.customer_id), NULL) AS cif,
  IF(plan.birth, gamma_birth(l.birth_date, r.birth_date), NULL) AS birth
FROM u_drawn AS l JOIN u_drawn AS r ON l.id < r.id CROSS JOIN u_plan AS plan;

CREATE OR REPLACE TABLE u_sampled AS
SELECT 'name' AS comparison, name AS gamma, COUNT(*) AS pairs FROM u_pairs GROUP BY name
UNION ALL SELECT 'company', company, COUNT(*) FROM u_pairs GROUP BY company
UNION ALL SELECT 'address', address, COUNT(*) FROM u_pairs GROUP BY address
UNION ALL SELECT 'phone', phone, COUNT(*) FROM u_pairs WHERE phone IS NOT NULL GROUP BY phone
UNION ALL SELECT 'cif', cif, COUNT(*) FROM u_pairs WHERE cif IS NOT NULL GROUP BY cif
UNION ALL SELECT 'birth', birth, COUNT(*) FROM u_pairs WHERE birth IS NOT NULL GROUP BY birth;


-- 5. The records, and how many fill the column a comparison is filled most by: what bounds a level no sampled pair
--    reached
CREATE OR REPLACE TABLE u_filled AS
SELECT
  COUNT(*) AS records,
  COUNT(person_name) AS name,
  COUNT(company_name) AS company,
  GREATEST(COUNT(address_code), COUNT(address), COUNT(postal_code)) AS address,
  COUNT(phone) AS phone,
  COUNT(customer_id) AS cif,
  COUNT(birth_date) AS birth
FROM u_records;
