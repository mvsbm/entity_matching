-- The decide job: people's decisions on pairs (given: a match table filled in) stored with the run's, each pair's
-- latest standing, and the entities made again from them all: connected components over the pairs whose latest
-- decision is match (entities_of, nayose/entities.py), each entity named by its smallest ID. So a pair said no_match
-- later parts what only it joined. Nothing merges by itself: a record no decision joins is an entity alone. A build
-- runs it with nothing given: its entities from the decisions the run holds. O(D + N) for D decisions.
--
-- Reads: given (id_l, id_r, decision, why; the job loads it, empty for a build), records, decisions (if any).
-- Values: @blank (the characters a blank value is made of, any width: Python's whitespace).
-- Writes: decisions (every decision that changed its pair's, with its batch, the latest flagged), gold (each record's
-- entity, what joined it, its kind and its customer's).

CREATE TABLE IF NOT EXISTS decisions (id_l STRING, id_r STRING, decision STRING, why STRING, batch INT64, latest BOOL);

-- 1. What people said, each value as text (an ID a spreadsheet saved as a number, 151 for 0000000151, then names no
--    record), a blank one (spaces of any width) missing, the decision in lower case. Each pair once, the lower ID
--    first; a row without a decision is skipped. Refused, each with what to do: a decided row without both IDs; rows
--    given and none decided; a decision other than match or no_match; a pair decided both ways; an ID that names no
--    record.
CREATE OR REPLACE TEMP TABLE given_text AS
SELECT IF(TRIM(l, @blank) = '', NULL, l) AS id_l, IF(TRIM(r, @blank) = '', NULL, r) AS id_r,
       NULLIF(LOWER(TRIM(d, @blank)), '') AS decision, NULLIF(TRIM(w, @blank), '') AS why
FROM (SELECT CAST(id_l AS STRING) AS l, CAST(id_r AS STRING) AS r, CAST(decision AS STRING) AS d, CAST(why AS STRING) AS w FROM given);

SELECT IF(COUNT(*) > 0, ERROR(CONCAT('given: ', CAST(COUNT(*) AS STRING), ' decided rows lack an ID; fill in both IDs of each decided row, or clear its decision')), 0)
FROM given_text WHERE decision IS NOT NULL AND (id_l IS NULL OR id_r IS NULL);

SELECT IF(COUNT(*) > 0 AND COUNT(decision) = 0, ERROR('given: no row has a decision; write match or no_match in the decision column'), 0)
FROM given_text;

CREATE OR REPLACE TEMP TABLE said AS
SELECT LEAST(id_l, id_r) AS id_l, GREATEST(id_l, id_r) AS id_r, decision, MIN(why) AS why
FROM given_text WHERE decision IS NOT NULL
GROUP BY 1, 2, 3;

SELECT IF(COUNT(*) > 0, ERROR(CONCAT('given: a decision is match or no_match, not ', STRING_AGG(DISTINCT decision, ', '),
                                     '; correct those rows, or leave them empty')), 0)
FROM said WHERE decision NOT IN ('match', 'no_match');

SELECT IF(COUNT(*) > 0, ERROR(CONCAT('given: ', CAST(COUNT(*) AS STRING), ' pairs decided both ways, as ', MIN(id_l), ' and ', MIN(id_r),
                                     '; keep one decision per pair')), 0)
FROM (SELECT id_l, id_r FROM said GROUP BY id_l, id_r HAVING COUNT(*) > 1);

SELECT IF(COUNT(*) > 0, ERROR(CONCAT('given: ', CAST(COUNT(*) AS STRING), ' IDs name no record of the run, as ', MIN(id),
                                     '; check the IDs as the run wrote them: a spreadsheet may read 0000000151 as the number 151')), 0)
FROM (SELECT id_l AS id FROM said UNION DISTINCT SELECT id_r FROM said)
WHERE id NOT IN (SELECT id FROM records);


-- 2. Stored: the run's decisions, and each one said that changes its pair's latest (a table given twice adds
--    nothing), as the next batch; each pair's last flagged latest.
CREATE OR REPLACE TABLE decisions AS
WITH every AS (
  SELECT id_l, id_r, decision, why, batch FROM decisions
  UNION ALL
  SELECT s.id_l, s.id_r, s.decision, s.why, (SELECT COALESCE(MAX(batch), -1) + 1 FROM decisions)
  FROM said AS s
  WHERE NOT EXISTS (SELECT 1 FROM decisions AS d WHERE d.latest AND d.id_l = s.id_l AND d.id_r = s.id_r AND d.decision = s.decision)
)
SELECT *, ROW_NUMBER() OVER (PARTITION BY id_l, id_r ORDER BY batch DESC) = 1 AS latest FROM every;


-- 3. The entities: each record its own, until the pairs whose latest decision is match join them (on this run's
--    records: a decision kept from a file run before may name others). resolved_by: review, where people's decision
--    put it with another record. customer_kind, each entity's: 2 company if a record is one; 1 person if no record
--    leans company (kind_p under 0.5) and one is a person; else 0 not sure.
-- shortcut: entities_of takes every match decision in one call, a few MB per 100,000 decisions; past millions,
-- components by label propagation in SQL.
CREATE OR REPLACE TEMP TABLE joined AS
SELECT JSON_VALUE(e, '$.id') AS id, JSON_VALUE(e, '$.entity') AS entity
FROM UNNEST(JSON_QUERY_ARRAY(entities_of((
  SELECT TO_JSON_STRING(STRUCT(ARRAY_AGG(STRUCT(d.id_l AS l, d.id_r AS r)) AS pairs)) FROM decisions AS d
  WHERE d.latest AND d.decision = 'match' AND d.id_l IN (SELECT id FROM records) AND d.id_r IN (SELECT id FROM records)
)))) AS e;

CREATE OR REPLACE TABLE gold AS
WITH placed AS (
  SELECT r.id, COALESCE(j.entity, r.id) AS cluster_id, r.kind, r.kind_p, r.kind_by, r.kind_flagged
  FROM records AS r LEFT JOIN joined AS j USING (id)
),
entity AS (
  SELECT cluster_id, COUNT(*) AS n,
         CASE WHEN LOGICAL_OR(kind = 2) THEN 2 WHEN COALESCE(MAX(kind_p), 0) < CAST(0.5 AS FLOAT64) AND LOGICAL_OR(kind = 1) THEN 1 ELSE 0 END AS customer_kind
  FROM placed GROUP BY cluster_id
)
SELECT p.id, p.cluster_id, IF(e.n > 1, 'review', NULL) AS resolved_stage, IF(e.n > 1, 'review', NULL) AS resolved_by,
       p.kind, p.kind_p, p.kind_by, p.kind_flagged, e.customer_kind
FROM placed AS p JOIN entity AS e USING (cluster_id);
