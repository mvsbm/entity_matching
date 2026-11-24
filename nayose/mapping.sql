-- The input's columns as the fields records.sql reads: the generated data's mapping (design/generate.py writes these
-- columns). A deployment's own file has its own mapping in this form, kept out of the repository (Secret Manager).
--
-- Each field is built from its sources in order: the first whose columns are all filled, joined. The values are as
-- the intake read them (sql/intake.sql: spaces alone, placeholders, missing); records.sql normalizes them.
-- config.toml [input] columns lists every column read here; one the file lacks is read as missing.

-- every input row as the file gave it, its ID named as records.sql reads it: the rows set aside are kept so
CREATE OR REPLACE TEMP TABLE input_rows AS
SELECT CONT_ID AS nayose_id, * FROM input;

CREATE OR REPLACE TEMP TABLE mapped AS
SELECT
  CONT_ID AS id,
  FULL_NAME_KANA AS full_name,
  COALESCE(FULL_NAME_KANA, O_PERSON_NAME_KANA, LAST_NAME_KANA || GIVEN_NAME_KANA) AS person_name,
  GIVEN_NAME_KANA AS given_name,
  NYS_CNV_P_NAME_KANA AS company_name,
  COALESCE(FULL_NAME_KANA, O_PERSON_NAME_KANA, LAST_NAME_KANA || GIVEN_NAME_KANA, NYS_CNV_P_NAME_KANA) AS any_name,
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
FROM input;
