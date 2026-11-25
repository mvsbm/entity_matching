-- The match job. It makes one table of pairs for people to decide on, with the highest points first. The table holds
-- every pair the run scored at @threshold points or more, except the pairs whose latest decision is no_match.
-- Each row holds:
--   an empty decision, for people to fill in with match or no_match;
--   the pair, its points and its probability;
--   the rule that also joins the pair, if one does, and the keys that listed it (sources);
--   whether a name was compared (named), and whether the pair may be two people of one household;
--   both records' fields side by side, and each comparison's level with the bits it earned.
-- People give the filled table back to the decide job (decide.sql).
-- O(C) to scan scored, plus O(P·F) to join the P pairs kept to their records' F fields.
--
-- Reads: scored (score.sql), records, model (each level's label and bits), decisions (decide.sql).
-- Values: @threshold, in points. The job refuses a threshold below [score] keep_from, because the run keeps no pair
-- below that.
-- Writes: matched.


-- household marks a pair that may be two people of one household. Its records share an address code, an address or
-- a phone, and they differ in their given name (two edits or more), in the last three characters of their name's
-- reading (three edits or more) or in their birth date (two edits or more). A difference counts only if both sides
-- are filled. household is a label only, and it changes no score.
CREATE OR REPLACE TEMP FUNCTION household(l ANY TYPE, r ANY TYPE) AS (
  (l.address_code = r.address_code OR l.address__address = r.address__address OR l.phone = r.phone)
  AND ((l.given_name__kana_fold IS NOT NULL AND r.given_name__kana_fold IS NOT NULL
        AND NOT cl_damerau_levenshtein_cut(l.given_name__kana_fold, r.given_name__kana_fold, 1) <= 1)
    OR (l.person_name__kana_fold_long_vowel_last3 IS NOT NULL AND r.person_name__kana_fold_long_vowel_last3 IS NOT NULL
        AND NOT cl_damerau_levenshtein_cut(l.person_name__kana_fold_long_vowel_last3,
                                           r.person_name__kana_fold_long_vowel_last3, 2) <= 2)
    OR (l.birth_date IS NOT NULL AND r.birth_date IS NOT NULL
        AND NOT cl_damerau_levenshtein_cut(l.birth_date, r.birth_date, 1) <= 1))
);

-- shown gives each comparison's levels as people read them, each with its label and its bits rounded to two places.
-- A missing side is level -1, labelled missing, with 0 bits. lookup.sql's shown uses the same labels.
CREATE OR REPLACE TEMP TABLE shown AS
SELECT comparison, gamma, label, ROUND(bits, 2) AS bits FROM model
UNION ALL SELECT DISTINCT comparison, -1, 'missing', CAST(0 AS FLOAT64) FROM model;

-- pair_records holds only the columns the table shows and household reads, because a row passed to a function is
-- billed whole.
CREATE OR REPLACE TABLE matched AS
WITH pair_records AS (
  SELECT id, person_name, given_name, company_name, address_code, address, postal_code, phone, customer_id, birth_date,
         address__address, given_name__kana_fold, person_name__kana_fold_long_vowel_last3
  FROM records
)
SELECT
  CAST(NULL AS STRING) AS decision, s.id_l, s.id_r, s.match_weight, s.match_probability, s.rule, s.named,
  household(x, y) AS household, s.sources,
  x.person_name AS person_name_l, y.person_name AS person_name_r,
  x.given_name AS given_name_l, y.given_name AS given_name_r,
  x.company_name AS company_name_l, y.company_name AS company_name_r,
  x.address_code AS address_code_l, y.address_code AS address_code_r,
  x.address AS address_l, y.address AS address_r, x.postal_code AS postal_code_l, y.postal_code AS postal_code_r,
  x.phone AS phone_l, y.phone AS phone_r, x.customer_id AS customer_id_l, y.customer_id AS customer_id_r,
  x.birth_date AS birth_date_l, y.birth_date AS birth_date_r,
  n.label AS name, n.bits AS name_bits, c.label AS company, c.bits AS company_bits,
  a.label AS address, a.bits AS address_bits, p.label AS phone, p.bits AS phone_bits,
  i.label AS cif, i.bits AS cif_bits, b.label AS birth, b.bits AS birth_bits
FROM scored AS s
JOIN pair_records AS x ON x.id = s.id_l JOIN pair_records AS y ON y.id = s.id_r
JOIN shown AS n ON n.comparison = 'name' AND n.gamma = s.gamma_name
JOIN shown AS c ON c.comparison = 'company' AND c.gamma = s.gamma_company
JOIN shown AS a ON a.comparison = 'address' AND a.gamma = s.gamma_address
JOIN shown AS p ON p.comparison = 'phone' AND p.gamma = s.gamma_phone
JOIN shown AS i ON i.comparison = 'cif' AND i.gamma = s.gamma_cif
JOIN shown AS b ON b.comparison = 'birth' AND b.gamma = s.gamma_birth
WHERE s.match_weight >= @threshold
  AND NOT EXISTS (SELECT 1 FROM decisions AS d
                  WHERE d.id_l = s.id_l AND d.id_r = s.id_r AND d.latest AND d.decision = 'no_match')
ORDER BY s.match_weight DESC, s.id_l, s.id_r;
