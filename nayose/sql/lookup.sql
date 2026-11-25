-- The lookup job. It finds the entities that a record asked about would be compared with, best first, as an update of
-- that record alone would compare it. records.sql and score.sql have already run on the record, with the run's model
-- as it stands. They ran in temporary tables named like the run's, which hold only the records of the record's blocks
-- (nayose.lookup), so a lookup writes nothing. The job gives each entity with @at_least points or more, or joined by a
-- rule, with its best record, its points, each comparison's level, the rule that would join it and the keys that
-- listed it. It also gives what was looked up, key by key.
-- O(G·b + C·K·L²) for the record's C candidates.
--
-- Reads: batch_records (the record asked about), batch_scored (score.sql, which scores every candidate
-- of a lookup whatever keep_from says), gold (each stored record's entity), records, model (each level's label),
-- generators, rules, key_blocks, gated, rule_blocks.
-- Values:
--   @at_least      an entity with this many points or more is shown
--   @likely_from   a pair with this many points or more, whose names were compared, counts as likely
--                  (config.toml's [lookup] likely_from)
--   @oversized     a block of this many records or more is oversized (score.sql)
--   @stored        true if the record asked about is a stored one, looked up as if it were new
-- Writes (temporary, read by the job): candidates, entities, checked.

CREATE OR REPLACE TEMP TABLE candidates AS
WITH paired AS (
  SELECT s.*, IF(s.id_l = a.id, s.id_r, s.id_l) AS other
  FROM batch_scored AS s JOIN batch_records AS a ON a.id = s.id_l OR a.id = s.id_r
),
shown AS (  -- this is match.sql's shown without the bits, so a missing side's level reads 'missing'
  SELECT comparison, gamma, label FROM model UNION ALL SELECT DISTINCT comparison, -1, 'missing' FROM model
)
SELECT
  p.other AS id, gd.cluster_id AS entity, p.match_weight AS points, p.rule, ru.i AS rule_rank, p.sources,
  p.match_weight >= @likely_from AND (p.gamma_name >= 0 OR p.gamma_company >= 0) AS likely,
  nm.label AS level_name, c.label AS level_company, d.label AS level_address, h.label AS level_phone,
  i.label AS level_cif, b.label AS level_birth,
  x.full_name, x.person_name, x.company_name, x.address, x.postal_code, x.phone, x.birth_date, x.customer_id
FROM paired AS p
JOIN gold AS gd ON gd.id = p.other
JOIN records AS x ON x.id = p.other
LEFT JOIN rules AS ru ON ru.rule = p.rule
JOIN shown AS nm ON nm.comparison = 'name' AND nm.gamma = p.gamma_name
JOIN shown AS c ON c.comparison = 'company' AND c.gamma = p.gamma_company
JOIN shown AS d ON d.comparison = 'address' AND d.gamma = p.gamma_address
JOIN shown AS h ON h.comparison = 'phone' AND h.gamma = p.gamma_phone
JOIN shown AS i ON i.comparison = 'cif' AND i.gamma = p.gamma_cif
JOIN shown AS b ON b.comparison = 'birth' AND b.gamma = p.gamma_birth;

-- entities holds each entity once, with its best record (the most points, then the lowest ID), the first rule in
-- order that joins any of its records, and how many of its records are candidates. An entity is shown if it has
-- @at_least points or more, or if a rule joins it.
CREATE OR REPLACE TEMP TABLE entities AS
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY entity ORDER BY points DESC, id) AS nth,
         COUNT(*) OVER (PARTITION BY entity) AS records
  FROM candidates
),
joined AS (
  SELECT entity, rule FROM (
    SELECT entity, rule, ROW_NUMBER() OVER (PARTITION BY entity ORDER BY rule_rank) AS nth
    FROM candidates WHERE rule IS NOT NULL
  ) WHERE nth = 1
)
SELECT rk.* EXCEPT (nth, rule, rule_rank, likely), j.rule, rk.likely OR j.rule IS NOT NULL AS likely
FROM ranked AS rk LEFT JOIN joined AS j USING (entity)
WHERE rk.nth = 1 AND (rk.points >= @at_least OR j.rule IS NOT NULL);

-- checked reports what was looked up. For each key the run uses, it gives how many records the record's blocks of
-- normal size hold (found), whether the record lacks the key (lacks), and the record's oversized blocks with the
-- gate's decision (big). found counts a stored record asked about, but not a typed one. Then, for each rule whose
-- key value is held by @oversized records or more, untrusted gives how many records hold it.
CREATE OR REPLACE TEMP TABLE checked AS
WITH mine AS (
  SELECT g, k, n FROM key_blocks WHERE id IN (SELECT id FROM batch_records)
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
SELECT 100 + ru.i, CONCAT('rule ', ru.rule), 0, FALSE, rb.n, NULL
FROM rules AS ru JOIN rule_blocks AS rb ON rb.i = ru.i
WHERE ru.used AND rb.id IN (SELECT id FROM batch_records) AND rb.n >= @oversized;
