-- This file maps the input's columns to the fields that records.sql reads. It is the mapping of the generated data,
-- whose columns design/generate.py writes. A deployment keeps its own mapping, in the same form, outside the
-- repository (in Secret Manager).
--
-- Every column is read through read_value (functions.sql). It reads damaged values and null tokens (@nulls, from
-- config.toml's [input] nulls) as missing, takes a list's first filled item and removes control characters. If its
-- second argument is TRUE, for a column of numbers, it also reads 12345.0 as 12345 and a number cut short in E
-- notation as missing.
-- A column that isn't text is cast to text first. A float column of codes, for example, is cast as
-- CAST(CAST(x AS INT64) AS STRING).
-- Each field takes the first of its sources, in order, whose columns are all filled. A source of two columns joins
-- them, as LAST_NAME_KANA || GIVEN_NAME_KANA does.
-- config.toml's [input] columns lists every column read here. A column that the file lacks is read as missing.

-- input_rows holds each distinct input row as the file gave it, with its ID read as mapped reads it (nayose_id).
-- records.sql sets aside rows from it as they were given, and counts its rows per ID to find an ID given with
-- different content.
CREATE OR REPLACE TEMP TABLE input_rows AS
SELECT DISTINCT read_value(CONT_ID, TRUE, @nulls) AS nayose_id, * FROM input;

CREATE OR REPLACE TEMP TABLE mapped AS
WITH source AS (
  SELECT
    read_value(CONT_ID, TRUE, @nulls)              AS id,
    read_value(FULL_NAME_KANA, FALSE, @nulls)      AS FULL_NAME_KANA,
    read_value(O_PERSON_NAME_KANA, FALSE, @nulls)  AS O_PERSON_NAME_KANA,
    read_value(LAST_NAME_KANA, FALSE, @nulls)      AS LAST_NAME_KANA,
    read_value(GIVEN_NAME_KANA, FALSE, @nulls)     AS GIVEN_NAME_KANA,
    read_value(NYS_CNV_P_NAME_KANA, FALSE, @nulls) AS NYS_CNV_P_NAME_KANA,
    read_value(STD_ADDRESS, FALSE, @nulls)         AS STD_ADDRESS,
    read_value(ORIGINAL_ADDRESS, FALSE, @nulls)    AS ORIGINAL_ADDRESS,
    read_value(SOURCE_ADDR_CD, TRUE, @nulls)       AS SOURCE_ADDR_CD,
    read_value(POST_CD, TRUE, @nulls)              AS POST_CD,
    read_value(POST_CD_KANA, TRUE, @nulls)         AS POST_CD_KANA,
    read_value(ADDRESS_ONE, FALSE, @nulls)         AS ADDRESS_ONE,
    read_value(ADDR_CD, TRUE, @nulls)              AS ADDR_CD,
    read_value(ADDRESS_TWO, FALSE, @nulls)         AS ADDRESS_TWO,
    read_value(PHONE_NUM_4, TRUE, @nulls)          AS PHONE_NUM_4,
    read_value(CIF_ID, TRUE, @nulls)               AS CIF_ID,
    read_value(BIRTH_DATE, TRUE, @nulls)           AS BIRTH_DATE,
    read_value(PERSON_ORG_CODE, TRUE, @nulls)      AS PERSON_ORG_CODE
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
