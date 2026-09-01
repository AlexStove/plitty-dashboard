#!/usr/bin/env bash
# One-shot server-side setup for the AgentMUSIC library transplant + pool files.
#
# Run ON the server (10.25.21.190) as root AFTER stopping the AgentMUSIC app
# in Coolify and AFTER uploading:
#   /tmp/_transplant.tar.gz      (library bundle from the dev box)
#   /tmp/agentmusic-batch/...    (chart_top50 with the 500 mp4s)
#
#   bash /tmp/server_transplant.sh [container-name]
#
# What it does: finds the AgentMUSIC container and its /app/output volume,
# extracts the bundle, copies mp3s (never overwrites existing files), merges
# both index.json files, runs the mandatory non-destructive verify gate, and
# copies the batch videos into the volume for the MinIO upload step.
set -euo pipefail

BUNDLE=/tmp/_transplant.tar.gz
BATCH=/tmp/agentmusic-batch
USER_ID=694509855

say() { echo -e "\n==> $*"; }
die() { echo "ОШИБКА: $*" >&2; exit 1; }

[ -f "$BUNDLE" ] || die "нет $BUNDLE — сначала scp с дев-машины"

# --- 1. Find the AgentMUSIC container -------------------------------------
CTR="${1:-}"
if [ -z "$CTR" ]; then
  CTR=$(docker ps -a --format '{{.Names}}' | grep -i -m1 -E 'agentmusic|agent-music|music' || true)
fi
[ -n "$CTR" ] || die "контейнер AgentMUSIC не найден. Посмотрите 'docker ps -a' и запустите: bash $0 <имя-контейнера>"
say "Контейнер: $CTR"

RUNNING=$(docker inspect --format '{{.State.Running}}' "$CTR")
[ "$RUNNING" = "false" ] || die "контейнер ещё работает — сначала остановите приложение в Coolify (Stop)"

# --- 2. Find the /app/output volume on the host ---------------------------
VOL=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/output"}}{{.Source}}{{end}}{{end}}' "$CTR")
[ -n "$VOL" ] || die "у контейнера нет volume на /app/output — библиотека была бы эфемерной; проверьте маунты: docker inspect $CTR"
say "Volume /app/output = $VOL"

# --- 3. Extract the bundle -------------------------------------------------
rm -rf /tmp/_transplant_extracted
mkdir -p /tmp/_transplant_extracted
tar -xzf "$BUNDLE" -C /tmp/_transplant_extracted
INC=$(find /tmp/_transplant_extracted -maxdepth 2 -type d -name "$USER_ID" | head -1)
[ -n "$INC" ] || die "в бандле нет папки $USER_ID"
SCRIPT=$(find /tmp/_transplant_extracted -maxdepth 2 -name transplant_library.py | head -1)
[ -n "$SCRIPT" ] || die "в бандле нет transplant_library.py"

# --- 4. Copy mp3s (cp -n: existing server files are never overwritten) ----
say "Копирую mp3 (существующие не трогаю)"
mkdir -p "$VOL/$USER_ID/_tracks" "$VOL/$USER_ID/_choruses"
cp -n "$INC/_tracks/"*.mp3   "$VOL/$USER_ID/_tracks/"   2>/dev/null || true
cp -n "$INC/_choruses/"*.mp3 "$VOL/$USER_ID/_choruses/" 2>/dev/null || true

# --- 5. Merge indexes, then the mandatory verify gate ----------------------
DOCKER_PY="docker run --rm -v $VOL:/app/output -v $(dirname "$SCRIPT"):/inc -v $INC:/inc-user -w /app python:3.11"
say "Merge индексов"
$DOCKER_PY python /inc/transplant_library.py merge \
  --incoming "/inc-user/_tracks/index.json"   --existing /app/output/$USER_ID/_tracks/index.json
$DOCKER_PY python /inc/transplant_library.py merge \
  --incoming "/inc-user/_choruses/index.json" --existing /app/output/$USER_ID/_choruses/index.json

say "VERIFY (обязан быть OK — иначе НЕ запускайте приложение)"
$DOCKER_PY python /inc/transplant_library.py verify \
  --index /app/output/$USER_ID/_tracks/index.json --cwd /app
$DOCKER_PY python /inc/transplant_library.py verify \
  --index /app/output/$USER_ID/_choruses/index.json --cwd /app

# --- 6. Batch videos for the MinIO upload step -----------------------------
if [ -d "$BATCH" ]; then
  SRC="$BATCH"
  [ -f "$BATCH/manifest.json" ] || SRC="$BATCH/chart_top50"
  if [ -f "$SRC/manifest.json" ]; then
    say "Копирую 500 видео в volume (для заливки в MinIO из контейнера)"
    mkdir -p "$VOL/batch/chart_top50"
    cp -rn "$SRC/." "$VOL/batch/chart_top50/"
  else
    echo "ПРЕДУПРЕЖДЕНИЕ: в $BATCH не найден manifest.json — пропускаю видео" >&2
  fi
else
  echo "ПРЕДУПРЕЖДЕНИЕ: нет $BATCH — пропускаю видео (можно докинуть позже)" >&2
fi

say "ГОТОВО. Дальше:"
cat <<'NEXT'
  1) Coolify -> Environment Variables приложения AgentMUSIC: добавить
     DEEZER_ARL, PIXABAY_API_KEY, PEXELS_API_KEY,
     MINIO_URL=http://10.25.172.205:9000, MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
     MINIO_TRACKS_BUCKET=music-tracks,
     AGENTMUSIC_API_KEYS=<openssl rand -hex 24>
  2) Coolify -> Redeploy (подтянет свежий master), приложение стартует.
  3) Проверка библиотеки (дважды!):
     curl -s http://10.25.21.190:18009/api/tracks -H "X-API-Key: <ключ>" | grep -c '"id"'
  4) Заливка в MinIO из контейнера:
     docker exec <container> python scripts/pool_upload_minio.py --limit 1
     docker exec <container> python scripts/pool_upload_minio.py
     docker exec <container> python scripts/upload_tracks_minio.py
NEXT
