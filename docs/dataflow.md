[← README](../README.md) · [Architecture](architecture.md)

# Data flow

Each job's data flow, drawn from its SQL by `scripts/dataflow.py`, which a test holds this page to. A cylinder is one of the run's tables; a slanted box, a table loaded into the dataset (a file, or the deploy's name model). An arrow says that the stage it names writes its end from its start; the temporary tables, views and WITHs between them are folded into the arrow.

## build

Stages: functions, mapping, records, fit, score, decide, report.

```mermaid
flowchart LR
  cands[(cands)]
  decisions[(decisions)]
  every_key[(every_key)]
  fit[(fit)]
  gold[(gold)]
  input[/input/]
  model[(model)]
  name_weights[/name_weights/]
  placeholders[(placeholders)]
  records[(records)]
  rule_keys[(rule_keys)]
  scored[(scored)]
  set_aside[(set_aside)]
  cands -->|score| scored
  decisions -->|decide| gold
  every_key -->|score| cands
  fit -->|score| cands
  fit -->|fit| model
  fit -->|score| scored
  input -->|records| placeholders
  input -->|records| records
  input -->|records| set_aside
  model -->|score| cands
  model -->|score| scored
  name_weights -->|records| placeholders
  name_weights -->|records| records
  placeholders -->|score| cands
  placeholders -->|score| every_key
  placeholders -->|records| records
  placeholders -->|score| rule_keys
  placeholders -->|score| scored
  records -->|score| cands
  records -->|score| every_key
  records -->|fit| fit
  records -->|decide| gold
  records -->|fit| model
  records -->|records| placeholders
  records -->|score| rule_keys
  records -->|score| scored
  records -->|records| set_aside
  rule_keys -->|score| scored
```

## update

Stages: functions, mapping, records, score, decide, report.

```mermaid
flowchart LR
  cands[(cands)]
  decisions[(decisions)]
  every_key[(every_key)]
  fit[(fit)]
  gold[(gold)]
  input[/input/]
  model[(model)]
  name_weights[/name_weights/]
  placeholders[(placeholders)]
  records[(records)]
  rule_keys[(rule_keys)]
  scored[(scored)]
  set_aside[(set_aside)]
  cands -->|score| scored
  decisions -->|decide| gold
  every_key -->|score| cands
  fit -->|score| cands
  fit -->|score| scored
  input -->|records| placeholders
  input -->|records| records
  input -->|records| set_aside
  model -->|score| cands
  model -->|score| scored
  name_weights -->|records| placeholders
  name_weights -->|records| records
  placeholders -->|score| cands
  placeholders -->|score| every_key
  placeholders -->|records| records
  placeholders -->|score| rule_keys
  placeholders -->|score| scored
  records -->|score| cands
  records -->|score| every_key
  records -->|decide| gold
  records -->|records| placeholders
  records -->|score| rule_keys
  records -->|score| scored
  records -->|records| set_aside
  rule_keys -->|score| scored
```

## decide

Stages: functions, decide.

```mermaid
flowchart LR
  decisions[(decisions)]
  given[/given/]
  gold[(gold)]
  records[(records)]
  decisions -->|decide| gold
  given -->|decide| decisions
  records -->|decide| gold
```

## match

Stages: functions, match.

```mermaid
flowchart LR
  decisions[(decisions)]
  matched[(matched)]
  model[(model)]
  records[(records)]
  scored[(scored)]
  decisions -->|match| matched
  model -->|match| matched
  records -->|match| matched
  scored -->|match| matched
```
