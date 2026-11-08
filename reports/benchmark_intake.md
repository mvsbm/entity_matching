# The reader on damaged files

`.venv/bin/python scripts/benchmark_intake.py --entities 800000`

1,000,338 records × 25 columns, generated from config/generator.toml.

## The clean copy

A UTF-8 CSV of the records: read in 14.8 s (14.8 s a million records); 0 values read back differently, nothing proposed: none, nothing unread: 0.

## The damaged copy

Read with every proposal accepted, in 28.0 s (28.0 s a million records). Before any is accepted, the reader proposed 96,595 encoding, 4,559 garbled, 548 realign; 0 rows were left unread.

| damage | values | read_back | share | how |
| --- | --- | --- | --- | --- |
| a value in CP932 | 810732 | 810664 | 100.0% | by itself |
| a value in EUC-JP | 156724 | 156703 | 100.0% | by itself, or proposed (encoding) |
| a zero-width character and a NUL | 71466 | 71466 | 100.0% | by itself |
| NULL for no value | 80832 | 80832 | 100.0% | by itself |
| a number a spreadsheet wrote (5851.0) | 9698 | 9698 | 100.0% | by itself |
| a name garbled upstream | 4622 | 4622 | 100.0% | proposed (garbled) |
| an unquoted comma inside an address | 548 | 548 | 100.0% | proposed (realign) |

Values changed that were never damaged (wrong repairs): 0.
