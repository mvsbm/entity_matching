-- The report's numbers: what the run holds and how its latest batch went, with no record's value in them, for
-- nayose.report to set out as report.txt. O(N·F) for the fields' fill, O(C) over the batch's pairs.
--
-- Reads: records, this_batch, set_aside, placeholders, gold, decisions, model, fit, cands, batch_pairs and
-- batch_scored (score.sql), key_blocks, gated, generators.
-- Values: @patterns (JSON: each field's look, config.toml [report] patterns, and the legal forms for company_name),
-- @edges (bits: where a score band starts), @floor (bits: the review floor), @oversized.
-- Writes (read by nayose.report_text, here or after a BigQuery procedure): report_counts, report_fields, report_scores, report_patterns,
-- report_keys, report_clusters.


-- one row: the run's records, the batch's, those set aside, the batch's pairs and its rule pairs, the entities and the
-- records people's decisions joined, the largest entity, the kinds of records and of customers, the oversized blocks
-- kept and skipped, each field's filled records
CREATE OR REPLACE TABLE report_counts AS
SELECT
  (SELECT COUNT(*) FROM records) AS records,
  (SELECT COUNT(*) FROM records WHERE batch = (SELECT batch FROM this_batch)) AS added,
  (SELECT batch FROM this_batch) AS batch,
  (SELECT COUNT(*) FROM set_aside) AS set_aside,
  (SELECT COUNT(*) FROM cands) AS candidates,
  (SELECT COUNT(*) FROM batch_scored) AS scored,
  (SELECT COUNT(*) FROM batch_scored WHERE rule IS NOT NULL) AS ruled,
  (SELECT COUNT(DISTINCT cluster_id) FROM gold) AS entities,
  (SELECT COUNT(*) FROM gold WHERE resolved_by = 'review') AS by_people,
  (SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM gold GROUP BY cluster_id)) AS largest,
  (SELECT COUNT(*) FROM decisions WHERE latest) AS decided,
  (SELECT COUNT(*) FROM gold WHERE kind = 2) AS companies, (SELECT COUNT(*) FROM gold WHERE kind = 1) AS persons,
  (SELECT COUNT(*) FROM gold WHERE kind = 0) AS unsure,
  (SELECT COUNT(DISTINCT cluster_id) FROM gold WHERE customer_kind = 2) AS company_customers,
  (SELECT COUNT(DISTINCT cluster_id) FROM gold WHERE customer_kind = 1) AS person_customers,
  (SELECT COUNT(DISTINCT cluster_id) FROM gold WHERE customer_kind = 0) AS unsure_customers,
  (SELECT COUNT(*) FROM gold WHERE kind_flagged) AS flagged,
  (SELECT COUNT(*) FROM gated WHERE decision = 'kept') AS oversized_kept,
  (SELECT COUNT(*) FROM gated WHERE decision <> 'kept') AS oversized_skipped,
  COUNT(full_name) AS full_name, COUNT(person_name) AS person_name, COUNT(given_name) AS given_name,
  COUNT(company_name) AS company_name, COUNT(any_name) AS any_name, COUNT(address) AS address, COUNT(address_code) AS address_code,
  COUNT(postal_code) AS postal_code, COUNT(prefecture) AS prefecture, COUNT(town_code) AS town_code, COUNT(city) AS city,
  COUNT(phone) AS phone, COUNT(customer_id) AS customer_id, COUNT(birth_date) AS birth_date
FROM records;

-- each field on a sample of 10,000 records by hash (the same sample whatever the rows' order): the share of its filled
-- values that look like it, that its most common value holds, that hold no letter or digit; its mean and longest length
CREATE OR REPLACE TABLE report_fields AS
WITH sample AS (SELECT * FROM records ORDER BY er_hash(id) LIMIT 10000),
v AS (
  SELECT 'full_name' AS field, full_name AS v FROM sample UNION ALL SELECT 'person_name', person_name FROM sample
  UNION ALL SELECT 'given_name', given_name FROM sample UNION ALL SELECT 'company_name', company_name FROM sample
  UNION ALL SELECT 'any_name', any_name FROM sample UNION ALL SELECT 'address', address FROM sample
  UNION ALL SELECT 'address_code', address_code FROM sample UNION ALL SELECT 'postal_code', postal_code FROM sample
  UNION ALL SELECT 'prefecture', prefecture FROM sample UNION ALL SELECT 'town_code', town_code FROM sample
  UNION ALL SELECT 'city', city FROM sample UNION ALL SELECT 'phone', phone FROM sample
  UNION ALL SELECT 'customer_id', customer_id FROM sample UNION ALL SELECT 'birth_date', birth_date FROM sample
),
top AS (SELECT field, MAX(n) / SUM(n) AS top_value FROM (SELECT field, v, COUNT(*) AS n FROM v WHERE v IS NOT NULL GROUP BY field, v) GROUP BY field)
SELECT
  field, AVG(CAST(REGEXP_CONTAINS(v, JSON_VALUE(@patterns, CONCAT('$.', field))) AS INT64)) AS looks_right,
  ANY_VALUE(top.top_value) AS top_value, AVG(CAST(NOT REGEXP_CONTAINS(v, r'[\pL\pN]') AS INT64)) AS no_letters,
  AVG(LENGTH(v)) AS length, MAX(LENGTH(v)) AS longest
FROM v LEFT JOIN top USING (field)
GROUP BY field;

-- the batch's candidates by bits from 0 up (band: how many of @edges a pair reaches); the rest, below 0 (-1): those
-- weighed under it, and those the bound put there unweighed
CREATE OR REPLACE TABLE report_scores AS
SELECT band, COUNT(*) AS pairs
FROM (SELECT ARRAY_LENGTH(ARRAY(SELECT e FROM UNNEST(@edges) AS e WHERE e <= match_weight)) AS band FROM batch_scored WHERE match_weight >= 0)
GROUP BY band
UNION ALL
SELECT -1, (SELECT COUNT(*) FROM batch_pairs) - (SELECT COUNT(*) FROM batch_scored WHERE match_weight >= 0);

-- the batch's pairs at 0 bits and up, below the review floor and from it: each band's patterns of levels, with how
-- many pairs hold each and their mean bits, the 12 most common first
CREATE OR REPLACE TABLE report_patterns AS
WITH p AS (
  SELECT match_weight >= @floor AS up, gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth,
         COUNT(*) AS n, AVG(match_weight) AS w
  FROM batch_scored WHERE match_weight >= 0
  GROUP BY 1, 2, 3, 4, 5, 6, 7
)
SELECT * FROM (
  SELECT *, SUM(n) OVER (PARTITION BY up) AS total, COUNT(*) OVER (PARTITION BY up) AS kinds,
         ROW_NUMBER() OVER (PARTITION BY up ORDER BY n DESC, w DESC, gamma_name, gamma_company, gamma_address, gamma_phone, gamma_cif, gamma_birth) AS k
  FROM p
) WHERE k <= 12;

-- each key: the pairs it lists (each once, a deletion key's too), per record; its largest block, how many are oversized
CREATE OR REPLACE TABLE report_keys AS
WITH listing AS (SELECT name, COUNT(*) AS pairs FROM cands, UNNEST(SPLIT(sources, '+')) AS name GROUP BY name),
blocks AS (SELECT g, MAX(n) AS largest, COUNT(DISTINCT CASE WHEN n >= @oversized THEN k END) AS oversized FROM key_blocks GROUP BY g)
SELECT g.g, g.name, COALESCE(l.pairs, 0) AS pairs, COALESCE(b.largest, 0) AS largest, COALESCE(b.oversized, 0) AS oversized
FROM generators AS g LEFT JOIN listing AS l USING (name) LEFT JOIN blocks AS b USING (g)
WHERE g.used;

-- the entities by size
CREATE OR REPLACE TABLE report_clusters AS
SELECT n AS size, COUNT(*) AS entities FROM (SELECT COUNT(*) AS n FROM gold GROUP BY cluster_id) GROUP BY n;
