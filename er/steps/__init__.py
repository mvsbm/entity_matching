"""The steps a job runs, each one module with one public function: (the job, its inputs) → its result. Each
module's docstring says the tables it reads and writes.

    load        1  read, set aside, standardize, placeholders
    budget      2  block sizes per rule and generator
    fit         3  λ, m by EM on a sample; u on the file
    rules       4  the certain cases
    candidates  5  the pairs the keys list
    score       6  every candidate that can reach the floor
    cluster     7  what merges, connected components, gold
    write       8  the workspace's files, staged
    report      9  report.txt
"""
