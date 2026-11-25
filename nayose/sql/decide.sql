-- The decide job stores people's decisions on pairs and makes the entities again from them. The decisions come in
-- given, a match table that people filled in. They are stored with the run's earlier decisions, and each pair's latest
-- decision is its standing. The entities are the connected components of the pairs whose latest decision is match
-- (entities_of, nayose/entities.py), and each is named by its smallest ID. So a later no_match on a pair parts what
-- only that pair joined. Nothing merges by itself, so a record that no decision joins is an entity alone. A build and
-- an update run this file without @given, to make their entities from the decisions the run holds: they skip
-- sections 1 and 2, which read given. O(D + N) for D decisions.
--
-- Reads: given, the job's table of id_l, id_r, decision and why (with @given alone), records, and decisions if the
-- run has any.
-- Values: given, TRUE if the job was given decisions. A blank value is one that blank() finds (functions.sql): spaces
-- alone, of any width.
-- Writes: decisions (each decision that changed its pair's standing, with its round, and each pair's latest flagged)
-- and gold (each record's entity, what joined it, its kind and its entity's kind). A round is one call of this job.

CREATE TABLE IF NOT EXISTS decisions (id_l STRING, id_r STRING, decision STRING, why STRING, round INT64, latest BOOL);

-- 1. given_text reads what people said, each value as text. A blank value (spaces of any width) is missing, and the
--    decision is put in lower case. An ID that a spreadsheet saved as a number (151 for 0000000151) then names no
--    record, and the check below refuses it. said holds each decided pair once, with the lower ID first and one
--    why. A row without a decision is skipped.
-- when: @given
CREATE OR REPLACE TEMP TABLE given_text AS
SELECT IF(blank(l), NULL, l) AS id_l, IF(blank(r), NULL, r) AS id_r,
       NULLIF(LOWER(trimmed(d)), '') AS decision, NULLIF(trimmed(why), '') AS why
FROM (SELECT CAST(id_l AS STRING) AS l, CAST(id_r AS STRING) AS r, CAST(decision AS STRING) AS d,
             CAST(why AS STRING) AS why
      FROM given);

-- when: @given
CREATE OR REPLACE TEMP TABLE said AS
SELECT id_l, id_r, decision, MIN(why) AS why
FROM (SELECT LEAST(id_l, id_r) AS id_l, GREATEST(id_l, id_r) AS id_r, decision, why
      FROM given_text WHERE decision IS NOT NULL)
GROUP BY id_l, id_r, decision;

-- The check refuses the table and says what to do, for the first of these it finds, in this order: a decided row
-- without both IDs, a table with rows but no decision, a decision other than match or no_match, a pair decided both
-- ways, and an ID that names no record of the run. They are one statement, as BigQuery spends about a second on each.
-- when: @given
SELECT CASE
  WHEN lacking > 0 THEN ERROR(CONCAT('given: ', CAST(lacking AS STRING), ' decided rows lack an ID; fill in both IDs of each decided row, or clear its decision'))
  WHEN given_rows > 0 AND decided = 0 THEN ERROR('given: no row has a decision; write match or no_match in the decision column')
  WHEN other_decisions IS NOT NULL THEN ERROR(CONCAT('given: a decision is match or no_match, not ', other_decisions,
                                                     '; correct those rows, or leave them empty'))
  WHEN both_ways > 0 THEN ERROR(CONCAT('given: ', CAST(both_ways AS STRING), ' pairs decided both ways, as ', both_l, ' and ', both_r,
                                       '; keep one decision per pair'))
  WHEN unknown > 0 THEN ERROR(CONCAT('given: ', CAST(unknown AS STRING), ' IDs name no record of the run, as ', unknown_id,
                                     '; check the IDs as the run wrote them: a spreadsheet may read 0000000151 as the number 151'))
  ELSE 0 END
FROM (SELECT COUNT(CASE WHEN decision IS NOT NULL AND (id_l IS NULL OR id_r IS NULL) THEN 1 END) AS lacking,
             COUNT(*) AS given_rows, COUNT(decision) AS decided FROM given_text),
     (SELECT STRING_AGG(DISTINCT decision, ', ') AS other_decisions FROM said WHERE decision NOT IN ('match', 'no_match')),
     (SELECT COUNT(*) AS both_ways, MIN(id_l) AS both_l, MIN(id_r) AS both_r
      FROM (SELECT id_l, id_r FROM said GROUP BY id_l, id_r HAVING COUNT(*) > 1)),
     (SELECT COUNT(*) AS unknown, MIN(id) AS unknown_id
      FROM (SELECT id_l AS id FROM said UNION DISTINCT SELECT id_r FROM said) WHERE id NOT IN (SELECT id FROM records));


-- 2. decisions keeps the run's decisions and adds each new one that changes its pair's latest decision, so a table
--    given twice adds nothing. The new ones get the next round's number. Each pair's last decision is flagged latest.
-- when: @given
CREATE OR REPLACE TABLE decisions AS
WITH stored_and_said AS (
  SELECT id_l, id_r, decision, why, round FROM decisions
  UNION ALL
  SELECT s.id_l, s.id_r, s.decision, s.why, (SELECT COALESCE(MAX(round), -1) + 1 FROM decisions)
  FROM said AS s
  WHERE NOT EXISTS (SELECT 1 FROM decisions AS d
                    WHERE d.latest AND d.id_l = s.id_l AND d.id_r = s.id_r AND d.decision = s.decision)
)
SELECT *, ROW_NUMBER() OVER (PARTITION BY id_l, id_r ORDER BY round DESC) = 1 AS latest FROM stored_and_said;


-- 3. Each record is its own entity until the pairs whose latest decision is match join it to others. Only pairs of
--    this run's records join, because a decision kept from an earlier run may name records the run no longer holds.
--    resolved_by is review if people's decisions put the record with another record. entity_kind, the entity's
--    kind, is 2 (company) if any of its records is a company. It is 1 (person) if none of its records leans company
--    (kind_p under 0.5) and one is a person, and 0 (not sure) otherwise.
-- shortcut: entities_of takes every match decision in one call, a few MB for each 100,000 decisions. Past millions of
-- decisions, compute the components by label propagation in SQL.

-- joined is a table, not a WITH in gold: gold reads placed twice, and BigQuery runs a WITH once each time it is read.
CREATE OR REPLACE TEMP TABLE joined AS  -- each record that a match decision joins, with its entity
-- asked holds what entities_of is asked, as one JSON text: the pairs whose latest decision is match, both of whose
-- records the run holds.
WITH asked AS (
  SELECT TO_JSON_STRING(STRUCT(ARRAY_AGG(STRUCT(d.id_l AS l, d.id_r AS r)) AS pairs)) AS pairs FROM decisions AS d
  WHERE d.latest AND d.decision = 'match' AND d.id_l IN (SELECT id FROM records) AND d.id_r IN (SELECT id FROM records)
)
SELECT JSON_VALUE(e, '$.id') AS id, JSON_VALUE(e, '$.entity') AS entity
FROM asked, UNNEST(JSON_QUERY_ARRAY(entities_of(asked.pairs))) AS e;

CREATE OR REPLACE TABLE gold CLUSTER BY id AS  -- a lookup reads gold by its records' IDs
WITH placed AS (
  SELECT rec.id, COALESCE(j.entity, rec.id) AS entity, rec.kind, rec.kind_p, rec.kind_by, rec.kind_flagged
  FROM records AS rec LEFT JOIN joined AS j USING (id)
),
entities AS (
  SELECT entity, COUNT(*) AS n,
         CASE WHEN LOGICAL_OR(kind = 2) THEN 2
              WHEN COALESCE(MAX(kind_p), 0) < CAST(0.5 AS FLOAT64) AND LOGICAL_OR(kind = 1) THEN 1
              ELSE 0 END AS entity_kind
  FROM placed GROUP BY entity
)
SELECT p.id, p.entity, IF(e.n > 1, 'review', NULL) AS resolved_by,
       p.kind, p.kind_p, p.kind_by, p.kind_flagged, e.entity_kind
FROM placed AS p JOIN entities AS e USING (entity);
