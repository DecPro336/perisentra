# Snowflake

The warehouse runs on Snowflake.
- **Ingestion** stages the source extracts and loads them with `COPY INTO raw.*`.
- **dbt** builds staging → intermediate → marts there: 35 models and 49 tests.
- **Training, scoring, the API and the Airflow DAGs** all read the marts back from Snowflake.

Everything runs as a key-pair service user (no password) on an X-Small warehouse capped at 20 credits a month.

## One-time setup

1. **Account.** Sign up at <https://signup.snowflake.com>. Pick Enterprise, AWS and a US East region, then activate the
   account from the email.
2. **Key pair** for the service user. It stays on this machine, and the private key is never uploaded:
   ```bash
   mkdir -p ~/.snowflake && chmod 700 ~/.snowflake
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/.snowflake/perisentra_rsa_key.p8 -nocrypt
   openssl rsa -in ~/.snowflake/perisentra_rsa_key.p8 -pubout -out ~/.snowflake/perisentra_rsa_key.pub
   chmod 600 ~/.snowflake/perisentra_rsa_key.p8
   ```
3. **Objects.**
   - In `setup.sql`, replace `<PUBLIC_KEY>` with the base64 body of `~/.snowflake/perisentra_rsa_key.pub`, on one
     line and without the BEGIN/END lines. This prints it ready to paste:
     `grep -v "PUBLIC KEY" ~/.snowflake/perisentra_rsa_key.pub | tr -d '\n'`
   - Paste the script into a Snowsight worksheet and run it with **Run All**. The ▶ button alone runs only the
     statement under the cursor.

   The script creates:
   - the `TRANSFORM_WH` warehouse (X-Small, suspends after 60 s idle) with a 20-credit monthly resource monitor
   - the `PERISENTRA` database and the `TRANSFORMER` role
   - the `PERISENTRA_SVC` service user (key-pair login only)

   Its last result row shows the account identifier and the stored key's fingerprint.
4. **Settings.** Run `cp .env.example .env` and set `SNOWFLAKE_ACCOUNT=<identifier>`.
5. **Check.** `uv run perisentra check-warehouse` shows the account, user, role and warehouse in use.

## Daily use

```bash
uv run perisentra ingest       # PUT Parquet to the table stages + COPY INTO raw.*  (~10 M rows, ~2 min)
uv run perisentra transform    # dbt build: 35 models + 49 tests (~30 s)
uv run perisentra score        # reads the marts, writes this morning's recommendations
make dbt-docs                  # dbt lineage and docs from the Snowflake catalog
```

Airflow (`make airflow`) runs the same commands every morning. Each task reads `.env`.

## How it works

- **Ingestion.** DuckDB parses the source files, the same way the offline copy does. Each table is then written as
  Parquet, `PUT` to its table stage and loaded with `COPY INTO ... MATCH_BY_COLUMN_NAME`.
- **dbt.** The models use cross-database macros (`macros/cross_db.sql`) for the date spine, ISO weekday, week start
  and day arithmetic.
  - Shares and ratios are computed in floating point, and denominators are wrapped in `nullif(..., 0)`. Snowflake's
    exact decimals and its error on division by zero would otherwise make results differ from the offline copy.
- **Reads.** Results come back as Arrow, with columns lower-cased and integers widened to 64-bit. Each process keeps
  one session, because a key-pair login takes about a second.
- **Not in Snowflake.** The operational decision log (dashboard decisions and store-app reports) lives in the app's
  SQLite database, and each ingestion copies it to `raw.app_*`.

## Offline copy (DuckDB)

`PERISENTRA_DBT_TARGET=duckdb` switches ingestion, dbt and the models to `data/warehouse/perisentra.duckdb`. It holds
the same models and produces identical tables and recommendations. The tests always use it, and it is the fallback
when Snowflake is unreachable. To refresh it:

```bash
PERISENTRA_DBT_TARGET=duckdb uv run perisentra ingest
PERISENTRA_DBT_TARGET=duckdb uv run perisentra transform
```
