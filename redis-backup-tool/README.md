# redis-backup-tool

Logical backup and restore for Redis Cluster with S3 integration.

## Commands

- `backup`: Dumps keys to JSONL parts, preserves TTLs, captures stream groups, archives to `.tar.gz`, and optionally uploads to S3.
- `restore`: Restores from a local directory or `.tar.gz` (or downloads from S3), with `--overwrite` and `--recreate-stream-groups` options.
- `list`: Lists available backup archives in S3 under the configured prefix.
- `verify`: Samples keys from a local backup dir and checks existence/TTL against the live cluster.

## Common environment

- `ENV_PROFILE`: `local|dev|prd` (defaults to `local`). Only `local` has built-in node defaults.
- `REDIS_NODES`: `host:port,host:port,...` to override nodes (required for non-local).
- `S3_URI`: `s3://bucket/prefix` used by backup upload, list, and restore-from-s3.

## Examples

Backup locally and upload to S3

```bash
docker run --rm \
  -e ENV_PROFILE=local \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  -v /tmp/redis-backups:/data/backups \
  redis-backup-tool:latest backup --match "user:*" --chunk-keys 10000
```

Restore latest from S3

```bash
docker run --rm \
  -e ENV_PROFILE=local \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  -v /tmp:/tmp \
  redis-backup-tool:latest restore --from-s3 latest --overwrite
```

List backups in S3

```bash
docker run --rm \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  redis-backup-tool:latest list
```

Verify backup against cluster

```bash
docker run --rm \
  -e ENV_PROFILE=local \
  -v /tmp/my-backup:/in \
  redis-backup-tool:latest verify -i /in --sample 500
```

## Local Dev (uv)

Run without Docker for quick iteration using uv and the workspace config:

```bash
# Show CLI help by path
uv run --project redis-backup-tool python redis-backup-tool/__main__.py --help

# Makefile helpers (profile creds)
make dev-sync
make backup S3_URI=s3://your-bucket/redis-backups BACKUP_DIR=./backups AWS_PROFILE=default
make dev-restore-latest S3_URI=s3://your-bucket/redis-backups AWS_PROFILE=default
make dev-list S3_URI=s3://your-bucket/redis-backups AWS_PROFILE=default
make dev-verify INPUT_DIR=./backups/redis-backup-local-... SAMPLE=200 AWS_PROFILE=default
```
