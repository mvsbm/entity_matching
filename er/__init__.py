"""Entity matching & resolution pipeline. No column names live here, except in the synthetic generator (design/generate.py): config/settings.toml maps a file's
columns to logical fields.

Stages and their tables:
  standardize  records → records + derived / normalized columns        (er.standardize)
  kind         each record → person, company or not sure; names routed  (er.kind)
  candidates   records → candidate pairs (uid_l, uid_r, sources)         (er.candidates)
  matching     pairs → scored / decided pairs                            (er.match)
  resolution   accepted pairs → clusters                                 (er.cluster.merge, in a run and at design time)
  report       report.txt, review.parquet                               (er.report, by er.steps.report)
  evaluation   pairs and clusters vs truth, plus cost                     (design.evaluate)

The jobs (er.jobs: build, update, decide, lookup) run each as `python -m er JOB` (er/__main__.py), on DuckDB here and
on Cloud Run alike (deploy/).
"""
