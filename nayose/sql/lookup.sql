-- The lookup job: the entities a record asked about would be compared with, as an update of it alone compares it
-- (records.sql and score.sql ran on it, the run's model as it stands), best first; the job rolls the run back after,
-- so a lookup writes nothing. Each entity at @at_least points or more, or joined by a rule, with its best record, its
-- points, each comparison's level, the rule that would join it and the keys that listed it; and what was looked up,
-- key by key. O(G·b + C·K·L²) for the record's C candidates, after score.sql's scan of the run's keys.
--
-- Reads: fresh (the record asked about), batch_scored and batch_rule_pairs (score.sql: every candidate scored,
-- keep_from aside), gold (each stored record's entity), records, model (each level's label), generators, rules,
-- key_blocks, gated, rule_keys.
-- Values: @at_least (points), @likely_from (points: a pair from here up whose names were compared is likely, as
-- people review), @oversized, @stored (the record asked about is a stored one, looked up as if it were new).
-- Writes (temporary, read by the job before it rolls back): candidates, entities, checked.

CREATE OR REPLACE TEMP TABLE candidates AS
WITH paired AS (
  SELECT s.*, IF(s.id_l = a.id, s.id_r, s.id_l) AS other FROM batch_scored AS s JOIN fresh AS a ON a.id = s.id_l OR a.id = s.id_r
),
said AS (SELECT comparison, gamma, label FROM model UNION ALL SELECT DISTINCT comparison, -1, 'missing' FROM model)
SELECT
  p.other AS id, g.cluster_id AS entity, p.match_weight AS points, p.rule, r.i AS rule_rank, p.sources,
  p.match_weight >= @likely_from AND (p.gamma_name >= 0 OR p.gamma_company >= 0) AS likely,
  n.label AS level_name, c.label AS level_company, d.label AS level_address, h.label AS level_phone, i.label AS level_cif,
  b.label AS level_birth, x.full_name, x.person_name, x.company_name, x.address, x.postal_code, x.phone, x.birth_date, x.customer_id
FROM paired AS p
JOIN gold AS g ON g.id = p.other
JOIN records AS x ON x.id = p.other
LEFT JOIN rules AS r ON r.rule = p.rule
JOIN said AS n ON n.comparison = 'name' AND n.gamma = p.gamma_name
JOIN said AS c ON c.comparison = 'company' AND c.gamma = p.gamma_company
JOIN said AS d ON d.comparison = 'address' AND d.gamma = p.gamma_address
JOIN said AS h ON h.comparison = 'phone' AND h.gamma = p.gamma_phone
JOIN said AS i ON i.comparison = 'cif' AND i.gamma = p.gamma_cif
JOIN said AS b ON b.comparison = 'birth' AND b.gamma = p.gamma_birth;

-- each entity once: its best record (most points, then the lowest ID), the first rule in order that joins any of its
-- records, and how many of its records are candidates; shown from @at_least points up, or when a rule joins it
CREATE OR REPLACE TEMP TABLE entities AS
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY entity ORDER BY points DESC, id) AS k, COUNT(*) OVER (PARTITION BY entity) AS records
  FROM candidates
),
joined AS (
  SELECT entity, rule FROM (
    SELECT entity, rule, ROW_NUMBER() OVER (PARTITION BY entity ORDER BY rule_rank) AS k FROM candidates WHERE rule IS NOT NULL
  ) WHERE k = 1
)
SELECT r.* EXCEPT (k, rule, rule_rank, likely), j.rule, r.likely OR j.rule IS NOT NULL AS likely
FROM ranked AS r LEFT JOIN joined AS j USING (entity)
WHERE r.k = 1 AND (r.points >= @at_least OR j.rule IS NOT NULL);

-- what was looked up: each key the run uses, how many records its normal blocks hold (a stored record asked about
-- among them), whether the record lacks it, and its oversized blocks with the gate's decision; then each rule whose
-- value is on @oversized records or more (untrusted: how many)
CREATE OR REPLACE TEMP TABLE checked AS
WITH mine AS (
  SELECT g, k, n FROM key_blocks WHERE id IN (SELECT id FROM fresh)
),
normal AS (
  SELECT m.g, COUNT(DISTINCT b.id) - IF(@stored, 0, 1) AS found
  FROM mine AS m JOIN key_blocks AS b USING (g, k) WHERE m.n < @oversized GROUP BY m.g
),
big AS (
  SELECT m.g, ARRAY_AGG(STRUCT(m.n AS records, z.sampled, z.best, z.decision) ORDER BY m.k) AS blocks
  FROM mine AS m JOIN gated AS z ON z.g = m.g AND z.value = m.k WHERE m.n >= @oversized GROUP BY m.g
)
SELECT g AS position, name AS key, COALESCE(normal.found, 0) AS found, g NOT IN (SELECT g FROM mine) AS lacks,
       CAST(NULL AS INT64) AS untrusted, big.blocks AS big
FROM generators LEFT JOIN normal USING (g) LEFT JOIN big USING (g)
WHERE used
UNION ALL
SELECT 100 + r.i, CONCAT('rule ', r.rule), 0, FALSE, k.n, NULL
FROM rules AS r JOIN rule_keys AS k ON k.i = r.i
WHERE r.used AND k.id IN (SELECT id FROM fresh) AND k.n >= @oversized;
