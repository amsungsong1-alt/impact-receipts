FROM python:3.11-slim-bookworm

# apt packages -- direct port of packages.txt (Streamlit Cloud's own
# apt-install list for this app), plus build-essential since psycopg2-binary
# and a couple of other C-extension deps don't always have a prebuilt wheel
# for every glibc/arch combination on this base image.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libcairo2-dev pkg-config python3-dev \
      build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# No reason for the Streamlit process to run as root in a container that
# only serves HTTP on 8501 to Nginx over the internal Docker network.
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

# Streamlit's own built-in health endpoint -- feeds this Dockerfile's
# HEALTHCHECK and docker-compose's healthcheck/depends_on condition. OSS
# Nginx has no active upstream health check of its own (that's an Nginx-Plus
# feature); recovery relies entirely on this + `restart: unless-stopped`.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || exit 1

# .streamlit/config.toml (enableXsrfProtection=true, headless=true) is baked
# into the image via COPY . . above and applies automatically -- do NOT
# repeat the devcontainer's dev-only --server.enableXsrfProtection=false
# override here; that setting must stay ON in production.
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true"]
