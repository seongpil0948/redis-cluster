## Redis Backup and Restore Tool

This project now includes a dedicated tool for logical backup and restore of the Redis Cluster, with S3 integration. This tool allows you to:

-   Perform logical backups of all Redis data types, preserving TTLs and Stream Consumer Group metadata.
-   Restore data to a Redis Cluster, with options for overwriting existing keys and recreating stream groups.
-   Upload backups to and download from S3.
-   List available backups in an S3 bucket.
-   Verify the integrity of a backup against a live cluster.

### Building the Backup Tool Image

The backup and restore tool is packaged as a Docker image.

```bash
make build-backup-tool
```

This command builds the `redis-backup-tool:latest` Docker image.

### Pushing to ECR (Elastic Container Registry)

To push the built image to your AWS ECR, set the `ECR_REGISTRY` environment variable and run:

```bash
export ECR_REGISTRY="your_aws_account_id.dkr.ecr.your_region.amazonaws.com" # e.g., 123456789012.dkr.ecr.us-east-1.amazonaws.com
make push-backup-tool-to-ecr
```

Ensure you are authenticated with AWS ECR before pushing.

### Usage Examples

The `redis-backup-tool` can be run via `docker run`, supporting both command-line arguments and environment variables.

**Common Environment Variables:**

-   `ENV_PROFILE`: `local|dev|prd` (specifies the Redis cluster environment profile)
-   `REDIS_NODES`: `host1:port1,host2:port2,...` (overrides the default node list for the specified `ENV_PROFILE`)
-   `S3_URI`: `s3://your-bucket-name/your-prefix` (S3 path for backup uploads and restore downloads)
-   **AWS Credentials**: Prefer profile/role-based auth. You can provide credentials via:
    -   **Shared Credentials File**: Mount your `~/.aws/credentials` (or `~/.aws`) into the container and set `AWS_PROFILE` (and `AWS_SDK_LOAD_CONFIG=1`).
    -   **IAM Roles for Service Accounts (IRSA)**: For Kubernetes environments, configure an IRSA for the pod running the tool.

#### 1. Backup

To perform a backup of your local Redis cluster and upload it to S3:

```bash
docker run --rm \
  -e ENV_PROFILE=local \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  -v /tmp/redis-backups:/data/backups \
  redis-backup-tool:latest backup
```

-   `-e ENV_PROFILE=local`: Connects to the local Redis cluster (ports 7001-7006 on `localhost`).
-   `-e S3_URI="..."`: Specifies the S3 bucket and prefix for storing backups.
-   `-v /tmp/redis-backups:/data/backups`: Mounts a local directory to store temporary backup files before S3 upload.
-   `backup`: The command to perform a backup.

You can override Redis nodes directly:

```bash
docker run --rm \
  -e REDIS_NODES="192.168.1.10:6379,192.168.1.11:6379" \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  -v /tmp/redis-backups:/data/backups \
  redis-backup-tool:latest backup --match "user:*" --chunk-keys 10000
```

#### 2. Restore

To restore the latest backup from S3 to your local Redis cluster:

```bash
docker run --rm \
  -e ENV_PROFILE=local \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  -v /tmp:/tmp \
  redis-backup-tool:latest restore --from-s3 latest --overwrite
```

-   `--from-s3 latest`: Downloads the most recent backup from the specified S3 URI. You can also specify a `backup-id` (e.g., `--from-s3 redis-backup-local-20231027T103000Z-abcdef12`).
-   `--overwrite`: Overwrites existing keys in the Redis cluster. Omit this flag to skip existing keys.

#### 3. List Backups

To list all available backups in a specific S3 location:

```bash
docker run --rm \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  redis-backup-tool:latest list
```

#### 4. Verify Backup

To verify a local backup directory against a live Redis cluster (e.g., after downloading it manually or from a previous backup run):

```bash
docker run --rm \
  -e ENV_PROFILE=local \
  -v /tmp/my-downloaded-backup:/in \
  redis-backup-tool:latest verify -i /in --sample 500
```

-   `-v /tmp/my-downloaded-backup:/in`: Mounts your local backup directory into the container.
-   `-i /in`: Specifies the input directory inside the container.
-   `--sample 500`: Checks a sample of 500 keys for existence and TTL.

For more details on arguments and environment variables, refer to the tool's help:

```bash
docker run --rm redis-backup-tool:latest --help
docker run --rm redis-backup-tool:latest backup --help
# etc.
```

### uv workspace usage (no Docker)

This repo uses an Astral uv workspace. To run the backup tool without Docker:

```bash
# Sync deps for all workspace projects
uv sync

# Show help by path
uv run --project redis-backup-tool python redis-backup-tool/__main__.py --help

#### Local dev Make targets

```bash
make dev-sync
make dev-backup S3_URI=s3://bucket/prefix BACKUP_DIR=./backups AWS_PROFILE=default
make dev-restore-latest S3_URI=s3://bucket/prefix AWS_PROFILE=default
make dev-list S3_URI=s3://bucket/prefix AWS_PROFILE=default
make dev-verify INPUT_DIR=./backups/redis-backup-local-... SAMPLE=200 AWS_PROFILE=default
```
```

Note: Use `-p redis-backup-tool` when running via uv from the repository root, so uv resolves the correct project environment.
