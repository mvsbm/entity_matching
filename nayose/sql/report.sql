-- This file computes report.txt's numbers, which tell what the run holds and how its latest batch went. No number
-- holds a record's value. nayose.report sets them out as report.txt. O(N·F) for the fields' fill, and O(C) over the
-- batch's pairs.
--
-- Reads: records, this_batch, set_aside, gold, decisions, cands, batch_pairs and batch_scored (score.sql), key_blocks,
-- gated and generators. nayose.report_text reads placeholders, model and fit itself.
-- Values:
--   @looks      as JSON, the regular expression that each field's values look like (config.toml [report.looks],
--               and for company_name the legal forms)
--   @edges      the points at which each score band starts
--   @floor      the review floor, in points
--   @oversized  how many records make a block oversized
--   @sample_records, @patterns_shown   the records FIELDS samples, and the patterns each band shows (config.toml
--               [report])
-- Writes (read by nayose.report_text, here or after a BigQuery procedure): report_counts, report_fields,
-- report_scores, report_patterns, report_generators, report_entities.


-- report_counts holds one row of counts about the run, its latest batch, its entities and kinds, its oversized
-- blocks, and each field's filled records.
CREATE OR REPLACE TEMP TABLE report_counts AS
SELECT
  (SELECT COUNT(*) FROM records) AS records,
  (SELECT COUNT(*) FROM records WHERE batch = (SELECT batch FROM this_batch)) AS added,
  (SELECT batch FROM this_batch) AS batch,
  (SELECT COUNT(*) FROM set_aside) AS set_aside,
  (SELECT COUNT(*) FROM cands) AS candidates,
  (SELECT COUNT(*) FROM batch_scored) AS scored,
  (SELECT COUNT(*) FROM batch_scored WHERE rule IS NOT NULL) AS ruled,
  (SELECT COUNT(DISTINCT entity) FROM gold) AS entities,
  (SELECT COUNT(*) FROM gold WHERE resolved_by = 'review') AS by_people,
  (SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM gold GROUP BY entity)) AS largest,
  (SELECT COUNT(*) FROM decisions WHERE latest) AS decided,
  (SELECT COUNT(*) FROM gold WHERE kind = 2) AS companies, (SELECT COUNT(*) FROM gold WHERE kind = 1) AS persons,
  (SELECT COUNT(*) FROM gold WHERE kind = 0) AS unsure,
  (SELECT COUNT(DISTINCT entity) FROM gold WHERE entity_kind = 2) AS company_entities,
  (SELECT COUNT(DISTINCT entity) FROM gold WHERE entity_kind = 1) AS person_entities,
  (SELECT COUNT(DISTINCT entity) FROM gold WHERE entity_kind = 0) AS unsure_entities,
  (SELECT COUNT(*) FROM gold WHERE kind_flagged) AS flagged,
  (SELECT COUNT(*) FROM gated WHERE verdict = 'joined') AS oversized_joined,
  (SELECT COUNT(*) FROM gated WHERE verdict <> 'joined') AS oversized_skipped,
  COUNT(full_name) AS full_name, COUNT(person_name) AS person_name, COUNT(given_name) AS given_name,
  COUNT(company_name) AS company_name, COUNT(any_name) AS any_name, COUNT(address) AS address,
  COUNT(address_code) AS address_code, COUNT(postal_code) AS postal_code, COUNT(prefecture) AS prefecture,
  COUNT(town_code) AS town_code, COUNT(city) AS city, COUNT(phone) AS phone, COUNT(customer_id) AS customer_id,
  COUNT(birth_date) AS birth_date
FROM records;

-- report_fields describes each field on a sample of @sample_records records, chosen by hash so that the sample is the
-- same whatever the rows' order. It gives the share of a field's filled values that look like its pattern
-- (looks_right), the share that its most common value holds (top_value), the share with no letter or digit
-- (no_letters), and the values' mean and longest length.
CREATE OR REPLACE TEMP TABLE report_fields AS
WITH sample AS (SELECT * FROM records ORDER BY er_hash(id) LIMIT @sample_records),
sampled_values AS (
  SELECT 'full_name' AS field, full_name AS v FROM sample UNION ALL SELECT 'person_name', person_name FROM sample
  UNION ALL SELECT 'given_name', given_name FROM sample UNION ALL SELECT 'company_name', company_name FROM sample
  UNION ALL SELECT 'any_name', any_name FROM sample UNION ALL SELECT 'address', address FROM sample
  UNION ALL SELECT 'address_code', address_code FROM sample UNION ALL SELECT 'postal_code', postal_code FROM sample
  UNION ALL SELECT 'prefecture', prefecture FROM sample UNION ALL SELECT 'town_code', town_code FROM sample
  UNION ALL SELECT 'city', city FROM sample UNION ALL SELECT 'phone', phone FROM sample
  UNION ALL SELECT 'customer_id', customer_id FROM sample UNION ALL SELECT 'birth_date', birth_date FROM sample
),
top AS (
  SELECT field, MAX(n) / SUM(n) AS top_value
  FROM (SELECT field, v, COUNT(*) AS n FROM sampled_values WHERE v IS NOT NULL GROUP BY field, v)
  GROUP BY field
)
SELECT
  field, AVG(CAST(REGEXP_CONTAINS(v, JSON_VALUE(@looks, CONCAT('$.', field))) AS INT64)) AS looks_right,
  ANY_VALUE(top.top_value) AS top_value, AVG(CAST(NOT REGEXP_CONTAINS(v, r'[\pL\pN]') AS INT64)) AS no_letters,
  AVG(LENGTH(v)) AS length, MAX(LENGTH(v)) AS longest
FROM sampled_values LEFT JOIN top USING (field)
GROUP BY field;

-- report_scores counts the batch's pairs by band. A pair scored at 0 points or more is in band k if k of @edges are
-- at or below its points. Band -1 counts the rest of the batch's pairs (batch_pairs). With [score] keep_from at 0,
-- those are the pairs that scored below 0 points, and the pairs that the bound kept from being scored.
CREATE OR REPLACE TEMP TABLE report_scores AS
SELECT band, COUNT(*) AS pairs
FROM (SELECT ARRAY_LENGTH(ARRAY(SELECT e FROM UNNEST(@edges) AS e WHERE e <= points)) AS band
      FROM batch_scored WHERE points >= 0)
GROUP BY band
UNION ALL
SELECT -1, (SELECT COUNT(*) FROM batch_pairs) - (SELECT COUNT(*) FROM batch_scored WHERE points >= 0);

-- report_patterns splits the batch's pairs at 0 points or more into two bands, below the review floor (@floor) and
-- from it up. For each band it keeps the @patterns_shown most common patterns of levels, each with its pairs and their
-- mean points. It also gives the band's total pairs and how many patterns the band holds (patterns).
CREATE OR REPLACE TEMP TABLE report_patterns AS
WITH p AS (
  SELECT points >= @floor AS up, gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth,
         COUNT(*) AS n, AVG(points) AS mean_points
  FROM batch_scored WHERE points >= 0
  GROUP BY up, gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth
)
SELECT * FROM (
  SELECT *, SUM(n) OVER (PARTITION BY up) AS total, COUNT(*) OVER (PARTITION BY up) AS patterns,
         ROW_NUMBER() OVER (PARTITION BY up ORDER BY n DESC, mean_points DESC, gamma_name, gamma_company,
                                                     gamma_address, gamma_phone, gamma_cif, gamma_birth) AS nth
  FROM p
) WHERE nth <= @patterns_shown;

-- report_generators describes each generator that the run uses. pairs counts the candidates its keys listed, each
-- pair once, even if a deletion generator listed the pair through several of its deletions. largest is the size of
-- its largest block that holds a batch record, and oversized counts its blocks of @oversized records or more.
CREATE OR REPLACE TEMP TABLE report_generators AS
WITH listing AS (SELECT name, COUNT(*) AS pairs FROM cands, UNNEST(SPLIT(generators, '+')) AS name GROUP BY name),
blocks AS (
  SELECT g, MAX(n) AS largest, COUNT(DISTINCT CASE WHEN n >= @oversized THEN key END) AS oversized
  FROM key_blocks GROUP BY g
)
SELECT gen.g, gen.name, COALESCE(ls.pairs, 0) AS pairs, COALESCE(b.largest, 0) AS largest,
       COALESCE(b.oversized, 0) AS oversized
FROM generators AS gen LEFT JOIN listing AS ls USING (name) LEFT JOIN blocks AS b USING (g)
WHERE gen.used;

-- report_entities counts the entities of each size.
CREATE OR REPLACE TEMP TABLE report_entities AS
SELECT n AS size, COUNT(*) AS entities FROM (SELECT COUNT(*) AS n FROM gold GROUP BY entity) GROUP BY n;
