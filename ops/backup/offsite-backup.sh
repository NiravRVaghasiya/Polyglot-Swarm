#!/bin/sh
# Off-host, encrypted copies of the verified backup sets (ADR-0037, RR7).
#
# Runs in the restic/restic image as the `offsite` service of
# docker-compose.prod.yml. Every OFFSITE_INTERVAL_SECONDS it copies
# $DATA_DIR/backups to RESTIC_REPOSITORY (encrypted client-side with
# RESTIC_PASSWORD), applies the retention policy, checks the repository, and
# only then touches $DATA_DIR/.offsite-last-success, which the API exports
# as polyglot_offsite_backup_last_success_timestamp_seconds.
#
# Retention is 30 days at most (hourly for a day, then daily): it is the
# upper bound for how long erased learner data survives in backups, so do
# not lengthen it without updating the privacy documentation.
#
#   offsite-backup.sh          loop forever (the service)
#   offsite-backup.sh once     one copy; exit status says whether it worked
#   offsite-backup.sh <args>   any restic command (snapshots, restore, ...)
set -u

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required (see .env.production.example)}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required (see .env.production.example)}"
export RESTIC_REPOSITORY RESTIC_PASSWORD

DATA_DIR="${DATA_DIR:-/data}"
INTERVAL="${OFFSITE_INTERVAL_SECONDS:-3600}"
STATUS="$DATA_DIR/.offsite-last-success"
TAG=polyglot

ensure_repository() {
  # An existing repository opens; a new one is created. A wrong password
  # fails both, loudly, instead of silently starting a second repository.
  restic cat config >/dev/null 2>&1 || restic init
}

copy_once() {
  if [ ! -d "$DATA_DIR/backups" ]; then
    echo "offsite: $DATA_DIR/backups does not exist yet" >&2
    return 1
  fi
  ensure_repository &&
    restic backup --host "$TAG" --tag "$TAG" "$DATA_DIR/backups" &&
    restic forget --host "$TAG" --tag "$TAG" \
      --keep-hourly 24 --keep-daily 30 --prune &&
    restic check &&
    touch "$STATUS"
}

case "${1:-loop}" in
  loop)
    while true; do
      if copy_once; then
        echo "offsite: copy ok"
      else
        echo "OFFSITE BACKUP FAILED" >&2
      fi
      sleep "$INTERVAL"
    done
    ;;
  once)
    copy_once
    ;;
  *)
    exec restic "$@"
    ;;
esac
