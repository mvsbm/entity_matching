-- Stage 2, fit: what the model learns from, on a sample of a fixed size, so its cost doesn't grow with the file.
-- nayose.em learns the model from these counts (λ, then m by EM); u.sql measures u, on the sample and on the file.
-- O(n + P_prior + P_em·K) on the sample of n records.
--
-- Reads: records. Values: @fit_rows. Writes: fit_sample (and the view u_records of it), fit_prior, em_patterns.


-- 1. The sample: whole postal areas by hash, so households stay together and a smaller sample is part of a bigger one
CREATE OR REPLACE TABLE fit_sample AS
SELECT records.* FROM records
JOIN (SELECT id FROM records ORDER BY er_hash(postal_code__first3), er_hash(id) LIMIT @fit_rows) USING (id);

-- what u.sql measures: the sample first
CREATE OR REPLACE VIEW u_records AS
SELECT * FROM fit_sample;


-- 2. λ, how likely two random records are one customer, from the pairs the near-certain rules find: each pair once,
--    whichever rules find it. Each rule's own pairs too: a rule that finds none in the sample is skipped (named).
CREATE OR REPLACE TABLE fit_prior AS
SELECT
  (SELECT COUNT(*) FROM fit_sample) AS records,
  (SELECT COUNT(*) FROM (
     SELECT l.id AS l, r.id AS r FROM fit_sample AS l JOIN fit_sample AS r
       ON l.customer_id = r.customer_id AND l.full_name = r.full_name AND l.id < r.id
     UNION DISTINCT
     SELECT l.id, r.id FROM fit_sample AS l JOIN fit_sample AS r
       ON l.customer_id = r.customer_id AND l.company_name = r.company_name AND l.id < r.id
     UNION DISTINCT
     SELECT l.id, r.id FROM fit_sample AS l JOIN fit_sample AS r
       ON l.full_name = r.full_name AND l.address_code = r.address_code AND l.phone = r.phone AND l.id < r.id
  )) AS found,
  (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample
     WHERE customer_id IS NOT NULL AND full_name IS NOT NULL GROUP BY customer_id, full_name)) AS cif_name,
  (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample
     WHERE customer_id IS NOT NULL AND company_name IS NOT NULL GROUP BY customer_id, company_name)) AS cif_company,
  (SELECT COALESCE(SUM(DIV(n * (n - 1), 2)), 0) FROM (SELECT COUNT(*) AS n FROM fit_sample
     WHERE full_name IS NOT NULL AND address_code IS NOT NULL AND phone IS NOT NULL GROUP BY full_name, address_code, phone)) AS name_code_phone;


-- 3. EM's pairs, a session a key: the sample's pairs sharing a phone, then an address, each pattern of levels with
--    its count. A comparison the key chose its pairs by can't be learned from them: NULL in its session.
CREATE OR REPLACE TABLE em_patterns AS
SELECT
  'phone' AS session,
  gamma_name(l.person_name, r.person_name, l.person_name__kana_fold, r.person_name__kana_fold,
             l.person_name__kana_fold_long_vowel, r.person_name__kana_fold_long_vowel, l.given_name__kana_fold, r.given_name__kana_fold) AS name,
  gamma_company(l.company_name, r.company_name, l.company_name__nfkc_strip_legal_form_kana_fold, r.company_name__nfkc_strip_legal_form_kana_fold) AS company,
  gamma_address(l.address_code, r.address_code, l.address, r.address, l.postal_code, r.postal_code, l.address__address, r.address__address) AS address,
  CAST(NULL AS INT64) AS phone,
  gamma_cif(l.customer_id, r.customer_id) AS cif,
  gamma_birth(l.birth_date, r.birth_date) AS birth,
  COUNT(*) AS pairs
FROM fit_sample AS l JOIN fit_sample AS r ON l.phone = r.phone AND l.id < r.id
GROUP BY 1, 2, 3, 4, 5, 6, 7
UNION ALL
SELECT
  'address',
  gamma_name(l.person_name, r.person_name, l.person_name__kana_fold, r.person_name__kana_fold,
             l.person_name__kana_fold_long_vowel, r.person_name__kana_fold_long_vowel, l.given_name__kana_fold, r.given_name__kana_fold),
  gamma_company(l.company_name, r.company_name, l.company_name__nfkc_strip_legal_form_kana_fold, r.company_name__nfkc_strip_legal_form_kana_fold),
  CAST(NULL AS INT64),
  gamma_phone(l.phone, r.phone),
  gamma_cif(l.customer_id, r.customer_id),
  gamma_birth(l.birth_date, r.birth_date),
  COUNT(*)
FROM fit_sample AS l JOIN fit_sample AS r ON l.address__address = r.address__address AND l.id < r.id
GROUP BY 1, 2, 3, 4, 5, 6, 7;
