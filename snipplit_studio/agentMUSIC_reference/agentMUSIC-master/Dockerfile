FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    g++ \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Deno — JS runtime for yt-dlp EJS (YouTube in 2026). Non-fatal: Deezer works
# without it, so a Deno install hiccup must not fail the whole deploy.
RUN (curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh) \
    || echo "WARN: deno install failed; YouTube EJS leg degraded (Deezer unaffected)"
ENV PATH="/usr/local/bin:${PATH}"

WORKDIR /app

RUN pip install --upgrade pip "setuptools<81" wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# streamrip (Deezer downloader) is used as a CLI via subprocess. Its pinned deps
# (aiofiles<0.8, Pillow<10) conflict with this app, so install it in an isolated
# venv and expose the `rip` binary on PATH.
RUN python -m venv /opt/streamrip-venv \
    && /opt/streamrip-venv/bin/pip install --no-cache-dir streamrip \
    && ln -sf /opt/streamrip-venv/bin/rip /usr/local/bin/rip

# Patch spotdl: Spotify API removed several fields (genres, label, etc.)
COPY patch_spotdl.py .
RUN python patch_spotdl.py && rm patch_spotdl.py

COPY . .

CMD ["python", "bot.py"]
