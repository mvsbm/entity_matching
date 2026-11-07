"""Entity matching & resolution pipeline. No column names live here, except in the synthetic generator (er/generate.py): config/settings.toml maps a file's
columns to logical fields.

Stages and their tables:
  standardize  records → records + derived / normalized columns        (er.standardize)
  kind         each record → person, company or not sure; names routed  (er.kind)
  candidates   records → candidate pairs (uid_l, uid_r, sources)         (er.candidates)
  matching     pairs → scored / decided pairs                            (er.match)
  resolution   accepted pairs → clusters                                 (er.cluster.merge, in a run and at design time)
  report       qa.md, report.txt, review.parquet, kind_review.parquet    (er.report, by er.run.Run.report)
  evaluation   pairs and clusters vs truth, plus cost                     (er.evaluate)

The command line, nayose: every command declared once (er.cli); an inbox served through it (er.inbox); the same commands in
a browser (er.ui, er/ui.html).
"""
