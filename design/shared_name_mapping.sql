-- nayose/mapping.sql for a file whose one column, NAME_KANA, holds every name, a person's or a company's
-- (design.generate.kind_problems writes such files; scripts/benchmark.py's person-or-company runs read them, with
-- config.toml [records] shared_name_column: the name fields keep it only on records that lean their kind).
--
-- Each column the mapping reads is read through read_value (functions.sql): damaged values, lists, controls,
-- placeholders and, in a column of numbers (TRUE), numbers a spreadsheet wrote, fixed. A column that isn't text is
-- cast first (a float column of codes: CAST(CAST(x AS INT64) AS STRING)). Each field is then built from its sources in
-- order: the first whose columns are all filled, joined. config.toml [input] columns lists every column read here; one
-- the file lacks is read as missing.

-- every distinct input row as the file gave it, its ID read as the records' is: what set_aside keeps, and tells apart
CREATE OR REPLACE TEMP TABLE input_rows AS
SELECT DISTINCT read_value(CONT_ID, TRUE, @nulls) AS nayose_id, * FROM input;

CREATE OR REPLACE TEMP TABLE mapped AS
WITH source AS (
  SELECT
    read_value(CONT_ID, TRUE, @nulls) AS id,
    read_value(FULL_NAME_KANA, FALSE, @nulls)      AS FULL_NAME_KANA,
    read_value(O_PERSON_NAME_KANA, FALSE, @nulls)  AS O_PERSON_NAME_KANA,
    read_value(LAST_NAME_KANA, FALSE, @nulls)      AS LAST_NAME_KANA,
    read_value(GIVEN_NAME_KANA, FALSE, @nulls)     AS GIVEN_NAME_KANA,
    read_value(NYS_CNV_P_NAME_KANA, FALSE, @nulls) AS NYS_CNV_P_NAME_KANA,
    read_value(NAME_KANA, FALSE, @nulls)           AS NAME_KANA,
    read_value(STD_ADDRESS, FALSE, @nulls)         AS STD_ADDRESS,
    read_value(ORIGINAL_ADDRESS, FALSE, @nulls)    AS ORIGINAL_ADDRESS,
    read_value(SOURCE_ADDR_CD, TRUE, @nulls)      AS SOURCE_ADDR_CD,
    read_value(POST_CD, TRUE, @nulls)             AS POST_CD,
    read_value(POST_CD_KANA, TRUE, @nulls)        AS POST_CD_KANA,
    read_value(ADDRESS_ONE, FALSE, @nulls)         AS ADDRESS_ONE,
    read_value(ADDR_CD, TRUE, @nulls)             AS ADDR_CD,
    read_value(ADDRESS_TWO, FALSE, @nulls)         AS ADDRESS_TWO,
    read_value(PHONE_NUM_4, TRUE, @nulls)         AS PHONE_NUM_4,
    read_value(CIF_ID, TRUE, @nulls)              AS CIF_ID,
    read_value(BIRTH_DATE, TRUE, @nulls)          AS BIRTH_DATE,
    read_value(PERSON_ORG_CODE, TRUE, @nulls)     AS PERSON_ORG_CODE
  FROM input
)
SELECT
  id,
  NAME_KANA AS full_name,
  NAME_KANA AS person_name,
  GIVEN_NAME_KANA AS given_name,
  NAME_KANA AS company_name,
  NAME_KANA AS any_name,
  COALESCE(STD_ADDRESS, ORIGINAL_ADDRESS) AS address,
  SOURCE_ADDR_CD AS address_code,
  COALESCE(POST_CD, POST_CD_KANA) AS postal_code,
  ADDRESS_ONE AS prefecture,
  ADDR_CD AS town_code,
  ADDRESS_TWO AS city,
  PHONE_NUM_4 AS phone,
  CIF_ID AS customer_id,
  BIRTH_DATE AS birth_date,
  PERSON_ORG_CODE AS kind_flag
FROM source;
