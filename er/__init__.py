"""Entity matching & resolution pipeline. No column names live here: config/settings.toml maps them to logical fields.

Stages and their tables:
  standardize  records → records + derived / normalized columns        (er.standardize)
  candidates   records → candidate pairs (uid_l, uid_r, sources)         (er.candidates)
  matching     pairs → scored / decided pairs                            (er.match)
  resolution   accepted pairs → clusters                                 (er.resolve, er.pipeline.cascade)
  evaluation   pairs and clusters vs truth, plus cost                     (er.evaluate)
"""
