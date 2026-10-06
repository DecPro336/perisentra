-- Perisentra: one-time Snowflake setup. Paste into a Snowsight worksheet and use "Run All" (the arrow next to the
-- Run button, or Ctrl+Shift+Enter). The Run button alone executes only the statement under the cursor.
-- Creates a small auto-suspending warehouse with a credit cap, the project database and a service user
-- that authenticates with a key pair (no password). Safe to run twice.
--
-- Before running: replace <PUBLIC_KEY> below with the base64 lines of your public key file
-- (`cat ~/.snowflake/perisentra_rsa_key.pub`), without the BEGIN/END lines and joined on one line.

USE ROLE ACCOUNTADMIN;

-- compute: X-Small, suspends after 60 s idle, capped at 20 credits a month
CREATE WAREHOUSE IF NOT EXISTS TRANSFORM_WH
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;
CREATE RESOURCE MONITOR IF NOT EXISTS PERISENTRA_MONITOR
  WITH CREDIT_QUOTA = 20 FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 80 PERCENT DO NOTIFY ON 100 PERCENT DO SUSPEND;
ALTER WAREHOUSE TRANSFORM_WH SET RESOURCE_MONITOR = PERISENTRA_MONITOR;

-- storage: one database; schemas raw / staging / intermediate / marts are created by the pipeline
CREATE ROLE IF NOT EXISTS TRANSFORMER;
GRANT ROLE TRANSFORMER TO ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS PERISENTRA;
GRANT USAGE, CREATE SCHEMA ON DATABASE PERISENTRA TO ROLE TRANSFORMER;
GRANT USAGE, OPERATE ON WAREHOUSE TRANSFORM_WH TO ROLE TRANSFORMER;

-- service user for dbt, ingestion and the models (key-pair authentication, no password)
CREATE USER IF NOT EXISTS PERISENTRA_SVC
  TYPE = SERVICE
  DEFAULT_ROLE = TRANSFORMER
  DEFAULT_WAREHOUSE = TRANSFORM_WH;
ALTER USER PERISENTRA_SVC SET RSA_PUBLIC_KEY = 'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAit+hpDUUaRe2MdXZ4ptXSho7HxLalO4ZyKb2QhGi8msdDzoX3itBftO3fwvdl7YHopSpT5egu+VWUWw65BxcJwAxfPMrImTn7G3N/Zil3CV5Q5QAbAunkbK0YEVXBLqQUvvYSRkA5V9yWqxc1/i4xcEER5HwZfEtURChv9PJ1uAmNqAyVdSQc3LbuqdHBjc2mXPUicn62KSBCRFRPl3ePopfvqRYO1zgIExTSWY27CJ/advIB2kJgEOvLqZM0Q7c1I2UfIOS3nAtNo6qAZZkXiPuobNHufTPJGms3Ed6efb5uPnQ6Ao07EZ1F64PdJkiLyVLGvbaltQkGmqqw/w/qQIDAQAB';
GRANT ROLE TRANSFORMER TO USER PERISENTRA_SVC;

-- check: one row with the account identifier for .env (SNOWFLAKE_ACCOUNT) and the fingerprint of the stored key,
-- which must match `perisentra check-warehouse` / the key file on the machine
DESC USER PERISENTRA_SVC;
SELECT CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME() AS snowflake_account,
       CURRENT_ACCOUNT()                                            AS account_locator,
       "value"                                                      AS service_user_key_fingerprint
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
WHERE "property" = 'RSA_PUBLIC_KEY_FP';
