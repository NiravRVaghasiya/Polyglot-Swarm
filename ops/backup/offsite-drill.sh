#!/usr/bin/env bash
# Off-host backup drill (ADR-0037): copy the backup sets to a throwaway
# restic REST server, then rebuild the data on a fresh volume (a lost host)
# from that copy alone and check it.
#
# Run by the CI container job after the API container is up and has at least
# one backup set; also runnable locally with Docker:
#   IMAGE=polyglot-swarm:ci ENV_FILE=.env.staging VOLUME=polyglot-ci-data \
#     METRICS=<token> bash ops/backup/offsite-drill.sh
# ENV_FILE must set RESTIC_REPOSITORY=rest:http://rest:8000/polyglot and
# RESTIC_PASSWORD. Expects the API container (API_CONTAINER, default `api`)
# to publish port 8000 on localhost.
set -euo pipefail

IMAGE="${IMAGE:-polyglot-swarm:ci}"
ENV_FILE="${ENV_FILE:-.env.staging}"
VOLUME="${VOLUME:-polyglot-ci-data}"
API_CONTAINER="${API_CONTAINER:-api}"
NETWORK="${NETWORK:-polyglot-drill}"
MIN_USERS="${MIN_USERS:-0}" # learner accounts the restored set must contain
RESTORED="${VOLUME}-restored"
RESTIC_IMAGE=restic/restic:0.19.1
REST_SERVER_IMAGE=restic/rest-server:0.14.0
SCRIPT="${OFFSITE_SCRIPT:-$(cd "$(dirname "$0")" && pwd)/offsite-backup.sh}"

offsite() { # offsite <volume> <args...>: the offsite service, as compose runs it
  local volume="$1"
  shift
  docker run --rm --network "$NETWORK" --env-file "$ENV_FILE" --user 10001:10001 \
    -e RESTIC_CACHE_DIR=/tmp/restic-cache --read-only --tmpfs /tmp \
    --cap-drop ALL --security-opt no-new-privileges:true \
    -v "$volume:/data" -v "$SCRIPT:/ops/offsite-backup.sh:ro" \
    --entrypoint /bin/sh "$RESTIC_IMAGE" /ops/offsite-backup.sh "$@"
}

app() { # app <volume> <args...>: a one-off command in the application image
  local volume="$1"
  shift
  docker run --rm --env-file "$ENV_FILE" --read-only --tmpfs /tmp -e HOME=/data/.home \
    -v "$volume:/data" "$IMAGE" "$@"
}

cleanup() {
  docker rm -f rest >/dev/null 2>&1 || true
  docker volume rm -f "$RESTORED" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== off-host repository (throwaway REST server)"
docker network create "$NETWORK" >/dev/null
docker run -d --name rest --network "$NETWORK" -e DISABLE_AUTHENTICATION=1 \
  "$REST_SERVER_IMAGE" >/dev/null
sleep 3

echo "== copy the backup sets off-host"
offsite "$VOLUME" once
offsite "$VOLUME" snapshots

echo "== the API reports the off-host copy"
curl -fsS -H "Authorization: Bearer ${METRICS}" localhost:8000/metrics |
  grep -E '^polyglot_offsite_backup_last_success_timestamp_seconds [0-9]'

echo "== a wrong password fails instead of creating a second repository"
if docker run --rm --network "$NETWORK" --env-file "$ENV_FILE" \
  -e RESTIC_PASSWORD=wrong-password-0123456789 --user 10001:10001 \
  -e RESTIC_CACHE_DIR=/tmp/c --tmpfs /tmp -v "$VOLUME:/data" \
  -v "$SCRIPT:/ops/offsite-backup.sh:ro" --entrypoint /bin/sh "$RESTIC_IMAGE" \
  /ops/offsite-backup.sh once; then
  echo "a wrong RESTIC_PASSWORD was accepted" >&2
  exit 1
fi

echo "== lost host: rebuild a fresh volume from the off-host copy alone"
docker volume create "$RESTORED" >/dev/null
app "$RESTORED" true # a new volume takes /data's ownership from the app image
offsite "$RESTORED" restore latest --target /data/offsite-restore
SET="$(app "$RESTORED" sh -c 'ls -d /data/offsite-restore/data/backups/polyglot-* | tail -1')"
echo "restoring $SET"
VERIFIED="$(app "$RESTORED" polyglot ops verify "$SET")"
echo "$VERIFIED"
USERS="$(echo "$VERIFIED" | tr -d '\n' | sed -n "s/.*'users': \([0-9]*\).*/\1/p")"
if [ "${USERS:-0}" -lt "$MIN_USERS" ]; then
  echo "restored set has ${USERS:-0} users, expected at least $MIN_USERS" >&2
  exit 1
fi
app "$RESTORED" polyglot ops restore "$SET" --yes
app "$RESTORED" polyglot ops db-check

echo "== off-host drill passed"
