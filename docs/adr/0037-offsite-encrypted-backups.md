# 0037. Off-host encrypted backups

- Status: Accepted
- Date: 2026-11-09
- Amends: [0035](0035-production-maturity.md) (backups, R4; residual risk RR7)

## Context

ADR-0035 gave the service verified backup sets, restore and retention, but
the sets lived on the same volume as the data and were not encrypted by the
application. Copying them off the host was a manual runbook step. The risk
register rated this (RR7) one of two blockers before real learners: losing
the host or its volume lost every backup with it, and the recovery point
was 24 hours.

## Decision

- The production stack gains an `offsite` service: the pinned
  `restic/restic` image running `ops/backup/offsite-backup.sh` as the
  application's unprivileged user, with a read-only root filesystem and no
  capabilities.
- Every `OFFSITE_INTERVAL_SECONDS` (1 h) it copies `/data/backups/` to
  `RESTIC_REPOSITORY`, prunes to hourly snapshots for 24 h and daily for
  30 days, runs `restic check`, and only then touches
  `/data/.offsite-last-success`. restic encrypts client-side with
  `RESTIC_PASSWORD`, so the storage provider holds ciphertext only.
- The API exports that time as
  `polyglot_offsite_backup_last_success_timestamp_seconds`;
  `PolyglotOffsiteBackupStale` and `PolyglotOffsiteBackupMissing` alert on it.
- Staging and production refuse to start (`polyglot ops config-check`, API
  startup) unless `RESTIC_REPOSITORY` names a non-local repository and
  `RESTIC_PASSWORD` has at least 16 characters.
- Local backup sets are written every `BACKUP_INTERVAL_SECONDS` (1 h, was
  24 h), so the recovery point is one hour for the whole volume, including
  loss of the host.
- The CI container job copies to a throwaway REST server and rebuilds a
  fresh volume from that copy alone (`ops/backup/offsite-drill.sh`).

## Alternatives considered

- **Litestream** (continuous SQLite replication): a recovery point of
  seconds, but it covers only the database, not media or profiles, and
  restores need their own procedure. Hourly verified sets are enough for
  now; Litestream remains the upgrade path.
- **Encrypting sets in the application**: a second key-management path to
  build and test. restic's format is audited, deduplicates, and has its own
  restore and integrity check.
- **Provider-side bucket encryption only**: the provider could read the
  data, and it ties the design to one provider.

## Consequences

- An operator must provide off-host storage and keep `RESTIC_PASSWORD`
  outside the host; without it the copies cannot be decrypted.
- Erased learner data survives in backups for up to 30 days (off-host
  retention). The privacy documentation states this bound; lengthening the
  retention requires updating it.
- The off-host copy runs independently of the backup job; a copy taken
  while a set is being written may include an incomplete set without a
  manifest, which `polyglot ops backups` ignores and the next copy replaces.
