# Official Spark and Java; Python and packages come from uv.lock, so jobs run as they do with uv.
FROM apache/spark:4.3.0-java21-python3

USER root
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked
COPY src ./src

# Executors must start the same Python as the driver, not the image's Python 3.10.
ENV PATH=/app/.venv/bin:$PATH PYSPARK_PYTHON=/app/.venv/bin/python
USER spark
ENTRYPOINT ["python", "src/main.py"]
