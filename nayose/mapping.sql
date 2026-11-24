-- The input's columns as the fields records.sql reads: the generated data's mapping (design/generate.py writes these
-- columns). A deployment's own file has its own mapping in this form, kept out of the repository (Secret Manager).
--
-- Each field is built from its sources in order: the first whose columns are all filled, joined. A source value of
-- spaces alone (any width) is missing first, so it never wins. Nothing is normalized here: records.sql does that.
-- config.toml [input] columns lists every column read here; one the file lacks is read as missing.

-- every input row as the file gave it, its ID named as records.sql reads it: the rows set aside are kept so
CREATE OR REPLACE TEMP TABLE input_rows AS
SELECT CONT_ID AS nayose_id, * FROM input;

CREATE OR REPLACE TEMP TABLE mapped AS
WITH source AS (
  SELECT
    CONT_ID AS id,
    IF(REGEXP_CONTAINS(FULL_NAME_KANA, r'^[\s\x{3000}]*$'), NULL, FULL_NAME_KANA) AS FULL_NAME_KANA,
    IF(REGEXP_CONTAINS(O_PERSON_NAME_KANA, r'^[\s\x{3000}]*$'), NULL, O_PERSON_NAME_KANA) AS O_PERSON_NAME_KANA,
    IF(REGEXP_CONTAINS(LAST_NAME_KANA, r'^[\s\x{3000}]*$'), NULL, LAST_NAME_KANA) AS LAST_NAME_KANA,
    IF(REGEXP_CONTAINS(GIVEN_NAME_KANA, r'^[\s\x{3000}]*$'), NULL, GIVEN_NAME_KANA) AS GIVEN_NAME_KANA,
    IF(REGEXP_CONTAINS(NYS_CNV_P_NAME_KANA, r'^[\s\x{3000}]*$'), NULL, NYS_CNV_P_NAME_KANA) AS NYS_CNV_P_NAME_KANA,
    IF(REGEXP_CONTAINS(STD_ADDRESS, r'^[\s\x{3000}]*$'), NULL, STD_ADDRESS) AS STD_ADDRESS,
    IF(REGEXP_CONTAINS(ORIGINAL_ADDRESS, r'^[\s\x{3000}]*$'), NULL, ORIGINAL_ADDRESS) AS ORIGINAL_ADDRESS,
    IF(REGEXP_CONTAINS(SOURCE_ADDR_CD, r'^[\s\x{3000}]*$'), NULL, SOURCE_ADDR_CD) AS SOURCE_ADDR_CD,
    IF(REGEXP_CONTAINS(POST_CD, r'^[\s\x{3000}]*$'), NULL, POST_CD) AS POST_CD,
    IF(REGEXP_CONTAINS(POST_CD_KANA, r'^[\s\x{3000}]*$'), NULL, POST_CD_KANA) AS POST_CD_KANA,
    IF(REGEXP_CONTAINS(ADDRESS_ONE, r'^[\s\x{3000}]*$'), NULL, ADDRESS_ONE) AS ADDRESS_ONE,
    IF(REGEXP_CONTAINS(ADDR_CD, r'^[\s\x{3000}]*$'), NULL, ADDR_CD) AS ADDR_CD,
    IF(REGEXP_CONTAINS(ADDRESS_TWO, r'^[\s\x{3000}]*$'), NULL, ADDRESS_TWO) AS ADDRESS_TWO,
    IF(REGEXP_CONTAINS(PHONE_NUM_4, r'^[\s\x{3000}]*$'), NULL, PHONE_NUM_4) AS PHONE_NUM_4,
    IF(REGEXP_CONTAINS(CIF_ID, r'^[\s\x{3000}]*$'), NULL, CIF_ID) AS CIF_ID,
    IF(REGEXP_CONTAINS(BIRTH_DATE, r'^[\s\x{3000}]*$'), NULL, BIRTH_DATE) AS BIRTH_DATE,
    IF(REGEXP_CONTAINS(PERSON_ORG_CODE, r'^[\s\x{3000}]*$'), NULL, PERSON_ORG_CODE) AS PERSON_ORG_CODE
  FROM input
)
SELECT
  id,
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
FROM source;
