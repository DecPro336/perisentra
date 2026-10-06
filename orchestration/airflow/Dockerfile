# Airflow with the Perisentra project in its own virtualenv (keeps Airflow's pinned deps separate).
FROM apache/airflow:3.1.0-python3.12

USER root
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
USER airflow

COPY --chown=airflow:root . /opt/perisentra/project
RUN python -m venv /opt/perisentra/venv \
 && /opt/perisentra/venv/bin/pip install --no-cache-dir uv \
 && /opt/perisentra/venv/bin/uv pip install --python /opt/perisentra/venv/bin/python --no-cache -e "/opt/perisentra/project[snowflake]" -e /opt/perisentra/project/simulator

ENV PERISENTRA_CLI=/opt/perisentra/venv/bin/perisentra \
    FERNBROOK_CLI=/opt/perisentra/venv/bin/fernbrook \
    PERISENTRA_ROOT=/opt/perisentra/project \
    PERISENTRA_DATA_DIR=/opt/perisentra/project/data \
    PERISENTRA_CONFIG_DIR=/opt/perisentra/project/configs
