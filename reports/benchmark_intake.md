# The reader on damaged files

`.venv/bin/python scripts/benchmark_intake.py --entities 800000`

1,039,995 records × 25 columns, generated from config/generator.toml, as Parquet, every column text.

## The clean copy

Read in 3.4 s (3.3 s a million records); 0 values read back differently; fixed as read: nothing.

## The damaged copy

Read in 3.9 s (3.8 s a million records); fixed as read: 84,895 controls, 83,148 lists, 10,094 numbers, 84,222 placeholders.

| damage | values | read_back | share |
| --- | --- | --- | --- |
| a zero-width character and a NUL | 84895 | 84895 | 100.0% |
| NULL for no value | 84222 | 84222 | 100.0% |
| a number a spreadsheet wrote (5851.0) | 10094 | 10094 | 100.0% |
| a value written as a list (["…"]) | 83148 | 83148 | 100.0% |

Values changed that were never damaged (wrong fixes): 0.
