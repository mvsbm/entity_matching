[← README](../README.md) · [Operations](operations.md)

# Running nayose from the BigQuery console

This page is for people who run nayose by hand, in the BigQuery console in a web browser: no Python, no Terraform,
no Jenkins. Everything here is pasting SQL and clicking **Run**, or uploading a file.

## What you need

- **A Google Cloud project with BigQuery**, and these roles in it: *BigQuery Data Editor* on the dataset nayose
  uses, and *BigQuery Job User* on the project.
- **Your records in a BigQuery table**, in the location **Tokyo (asia-northeast1)**, the same as nayose's dataset:
  BigQuery doesn't read across locations.
- **Two files from your technical contact**, made for your project, your dataset and your table:
  - `deploy.sql`: everything nayose installs in the dataset (functions and one procedure a job).
  - `name_weights.csv`: the name model, which tells a person's name from a company's.

  Your technical contact makes them once (and again only when nayose changes), from the repository:

  ```
  python deploy/deploy.py YOUR_PROJECT.nayose --mapping your_mapping.sql --sql files/
  ```

  `your_mapping.sql` is a copy of `nayose/mapping.sql` with two things changed: the table it reads, its `FROM` lines
  (`FROM input` becomes ``FROM `YOUR_PROJECT.raw.nayose_batch` ``), and the columns, where yours are named otherwise.
  A column that isn't text is read as text: `CAST(x AS STRING)`. Every column the mapping names must be in your
  table: where yours lacks one, add it empty (``ALTER TABLE `YOUR_PROJECT.raw.nayose_batch` ADD COLUMN NAME STRING``)
  or take it out of the mapping. A build otherwise stops at "Unrecognized name: NAME".

## Once: install nayose

1. **Make the dataset.** In the Explorer, on your project, click ⋮ → *Create dataset*. Dataset ID: `nayose`.
   Location: *asia-northeast1 (Tokyo)*. Click *Create dataset*.
2. **Load the name model.** On the dataset `nayose`, click ⋮ → *Create table*. Source: *Upload*, file:
   `name_weights.csv`, format *CSV*. Table: `name_weights`. Schema: click *Edit as text* and paste
   `term:STRING,coef:FLOAT64`. Under *Advanced options*, *Header rows to skip*: `1`. Click *Create table*.
3. **Install.** Click *+* (a new query), paste all of `deploy.sql`, and click *Run*. It takes about a minute. Then
   the dataset holds nayose's functions and four procedures: `build`, `update`, `decide` and `match`.

Run step 3 again, with the new `deploy.sql`, each time your technical contact sends one.

## Each time: match your records

nayose reads the table your mapping names, here `YOUR_PROJECT.raw.nayose_batch`. Put in it the records to match:
all of them for a first build, only the new ones for an update.

4. **Build** (the first time, or to start again from all your records). In a new query:

   ```sql
   CALL `YOUR_PROJECT.nayose`.build();
   SELECT * FROM report_counts;
   ```

   The second line shows the run's counts (records, pairs, entities). A build takes a few minutes, longer for a
   large table.
5. **See each record's entity:**

   ```sql
   SELECT * FROM `YOUR_PROJECT.nayose`.gold;
   ```

   `entity` is the record's entity, named by its smallest ID; records with one `entity` are one customer.
6. **Make the list for people to review**, the pairs from 8 points up:

   ```sql
   CALL `YOUR_PROJECT.nayose`.match(8);
   SELECT * FROM `YOUR_PROJECT.nayose`.matched;
   ```

   Click *Save results* → *Google Sheets*.
7. **Review.** In the sheet, people write `match` or `no_match` in the column `decision`, row by row. A row left
   empty is skipped.
8. **Give the decisions back.** Download the sheet as CSV (*File* → *Download* → *CSV*). On the dataset `nayose`,
   click ⋮ → *Create table*, Source *Upload*, that CSV, Table `given`, *Auto detect* on, and create it. Then:

   ```sql
   CALL `YOUR_PROJECT.nayose`.decide();
   DROP TABLE `YOUR_PROJECT.nayose`.given;
   ```

   `gold` then holds the entities as people decided them.
9. **New records later.** Replace the contents of `nayose_batch` with only the new records, then:

   ```sql
   CALL `YOUR_PROJECT.nayose`.update();
   SELECT * FROM report_counts;
   ```

   and review again from step 6.

## When something goes wrong

- **A wrong decisions file is refused** with what to fix, for example "given: a decision is match or no_match, not
  maybe; correct those rows, or leave them empty". Correct the sheet, upload it again, and run step 8.
- **A job that stops partway isn't undone here** (deploy/run.py undoes it; the console doesn't). Run step 4 again
  with all your records: people's decisions are always kept.
- **"the method, its values or the mapping changed since the run was built"**: a new `deploy.sql` was installed.
  Run step 4 with all your records.

On-demand billing charges for the bytes read; a test of thousands of records reads a few GB at most.
