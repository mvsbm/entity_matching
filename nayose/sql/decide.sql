-- The decide job stores people's decisions on pairs and makes the entities again from them. The decisions come in
-- given, a match table that people filled in. They are stored with the run's earlier decisions, and each pair's latest
-- decision is its standing. The entities are the connected components of the pairs whose latest decision is match
-- (entities_of, nayose/entities.py), and each is named by its smallest ID. So a later no_match on a pair parts what
-- only that pair joined. Nothing merges by itself, so a record that no decision joins is an entity alone. A build runs
-- this file with nothing given, to make its entities from the decisions the run holds. O(D + N) for D decisions.
--
-- Reads: given, the job's table of id_l, id_r, decision and why (empty for a build), records, and decisions if the
-- run has any.
-- Values: @blank holds the characters that a blank value is made of. They are Python's whitespace, the full-width
-- space among them.
-- Writes: decisions (each decision that changed its pair's standing, with its batch, and each pair's latest flagged)
-- and gold (each record's entity, what joined it, its kind and its customer's kind).

CREATE TABLE IF NOT EXISTS decisions (id_l STRING, id_r STRING, decision STRING, why STRING, batch INT64, latest BOOL);

-- 1. given_text reads what people said, each value as text. A blank value (spaces of any width) is missing, and the
--    decision is put in lower case. An ID that a spreadsheet saved as a number (151 for 0000000151) then names no
--    record, and the last check below refuses it. said holds each decided pair once, with the lower ID first and one
--    why. A row without a decision is skipped. Each check below refuses the table and says what to do. They refuse a
--    decided row without both IDs, a table with rows but no decision, a decision other than match or no_match, a pair
--    decided both ways, and an ID that names no record of the run.
CREATE OR REPLACE TEMP TABLE given_text AS
SELECT IF(TRIM(l, @blank) = '', NULL, l) AS id_l, IF(TRIM(r, @blank) = '', NULL, r) AS id_r,
       NULLIF(LOWER(TRIM(d, @blank)), '') AS decision, NULLIF(TRIM(w, @blank), '') AS why
FROM (SELECT CAST(id_l AS STRING) AS l, CAST(id_r AS STRING) AS r, CAST(decision AS STRING) AS d,
             CAST(why AS STRING) AS w
      FROM given);

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


-- 2. decisions keeps the run's decisions and adds each new one that changes its pair's latest decision, so a table
--    given twice adds nothing. The new ones get the next batch number. Each pair's last decision is flagged latest.
CREATE OR REPLACE TABLE decisions AS
WITH every AS (
  SELECT id_l, id_r, decision, why, batch FROM decisions
  UNION ALL
  SELECT s.id_l, s.id_r, s.decision, s.why, (SELECT COALESCE(MAX(batch), -1) + 1 FROM decisions)
  FROM said AS s
  WHERE NOT EXISTS (SELECT 1 FROM decisions AS d
                    WHERE d.latest AND d.id_l = s.id_l AND d.id_r = s.id_r AND d.decision = s.decision)
)
SELECT *, ROW_NUMBER() OVER (PARTITION BY id_l, id_r ORDER BY batch DESC) = 1 AS latest FROM every;


-- 3. Each record is its own entity until the pairs whose latest decision is match join it to others. Only pairs of
--    this run's records join, because a decision kept from an earlier run may name records the run no longer holds.
--    resolved_by is review if people's decisions put the record with another record. customer_kind, the entity's
--    kind, is 2 (company) if any of its records is a company. It is 1 (person) if none of its records leans company
--    (kind_p under 0.5) and one is a person, and 0 (not sure) otherwise.
-- shortcut: entities_of takes every match decision in one call, a few MB for each 100,000 decisions. Past millions of
-- decisions, compute the components by label propagation in SQL.

-- joined is a table, not a WITH in gold: gold reads placed twice, and BigQuery runs a WITH once each time it is read.
CREATE OR REPLACE TEMP TABLE joined AS  -- each record that a match decision joins, with its entity
SELECT JSON_VALUE(e, '$.id') AS id, JSON_VALUE(e, '$.entity') AS entity
FROM UNNEST(JSON_QUERY_ARRAY(entities_of((
  SELECT TO_JSON_STRING(STRUCT(ARRAY_AGG(STRUCT(d.id_l AS l, d.id_r AS r)) AS pairs)) FROM decisions AS d
  WHERE d.latest AND d.decision = 'match' AND d.id_l IN (SELECT id FROM records) AND d.id_r IN (SELECT id FROM records)
)))) AS e;

CREATE OR REPLACE TABLE gold CLUSTER BY id AS  -- a lookup reads gold by its records' IDs
WITH placed AS (
  SELECT r.id, COALESCE(j.entity, r.id) AS cluster_id, r.kind, r.kind_p, r.kind_by, r.kind_flagged
  FROM records AS r LEFT JOIN joined AS j USING (id)
),
entity AS (
  SELECT cluster_id, COUNT(*) AS n,
         CASE WHEN LOGICAL_OR(kind = 2) THEN 2
              WHEN COALESCE(MAX(kind_p), 0) < CAST(0.5 AS FLOAT64) AND LOGICAL_OR(kind = 1) THEN 1
              ELSE 0 END AS customer_kind
  FROM placed GROUP BY cluster_id
)
SELECT p.id, p.cluster_id, IF(e.n > 1, 'review', NULL) AS resolved_stage, IF(e.n > 1, 'review', NULL) AS resolved_by,
       p.kind, p.kind_p, p.kind_by, p.kind_flagged, e.customer_kind
FROM placed AS p JOIN entity AS e USING (cluster_id);
