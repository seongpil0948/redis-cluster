## Redis Backup and Restore Tool

This project now includes a dedicated tool for logical backup and restore of the Redis Cluster, with S3 integration. This tool allows you to:

-   Perform logical backups of all Redis data types, preserving TTLs and S### Notes and Known Issues

- **Redis Cluster Data Distribution**: When manually inserting test data, always use `redis-cli -c` (cluster mode) to ensure data is properly distributed across all cluster nodes. Without the `-c` flag, all data will be stored on the node you directly connect to, which defeats the purpose of clustering.
- Docker Desktop on macOS does not support `network_mode: host`. The `redis-1`…`redis-6` services in `docker-compose.yml` use host networking and are intended for Linux environments. On macOS, consider using Colima with host networking, or adapt the compose to bridge networking and adjust cluster creation accordingly.
- The `p3x-redis-ui` service expects an external network `dev_net`. Create it once with `docker network create dev_net`, or switch it to the default network if you don't need an external shared network.m Consumer Group metadata.
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

To push the built image to AWS ECR, export the following and run the Make target. This example is verified working:

```bash
# Set your registry host (no repo path)
export ECR_REGISTRY="008971653402.dkr.ecr.ap-northeast-2.amazonaws.com"

# Set your repository path/name
export ECR_REPO="util/redis-backup-tool"   # or just "redis-backup-tool"

# Set region and (optionally) profile for login
export ECR_REGION="ap-northeast-2"
export AWS_PROFILE="toy-root" # optional; use a profile with ECR permissions

# Build and push
make push-backup-tool-to-ecr
```

Notes:
- `ECR_REGISTRY` must be the registry hostname only (e.g., `123456789012.dkr.ecr.ap-northeast-2.amazonaws.com`).
- `ECR_REPO` is the repository path/name in ECR (e.g., `util/redis-backup-tool`).
- If you prefer raw CLI, you can login with:
  `aws ecr get-login-password --region $ECR_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY`

If you get an AccessDeniedException on `ecr:GetAuthorizationToken`, verify that your profile/user or assumed role has ECR permissions (e.g., the managed policy `AmazonEC2ContainerRegistryPowerUser`) or a minimal inline policy allowing `ecr:GetAuthorizationToken` and push to the specific repository.

### Using an Image from ECR in Make targets

If you want to run the Makefile convenience targets (backup, restore, list) with the image hosted on ECR instead of a locally-built image, first pull and set the image name via `BACKUP_IMAGE`:

```bash
# Login and pull the image (uses ECR_REGISTRY/ECR_REPO/ECR_REGION/AWS_PROFILE)
make pull-backup

# Use the ECR image for subsequent runs
export BACKUP_IMAGE="${ECR_REGISTRY}/${ECR_REPO}:latest"

# Now run the helpers
make backup-local-profile S3_URI=s3://theshop-lake-dev/backup/redis BACKUP_DIR=./backups
make list-backups-profile S3_URI=s3://theshop-lake-dev/backup/redis
make restore-latest-profile S3_URI=s3://theshop-lake-dev/backup/redis
```

Tip: You can also pass `BACKUP_IMAGE=...` inline per invocation instead of exporting it.

### Usage Examples

The `redis-backup-tool` can be run via `docker run`, supporting both command-line arguments and environment variables.

**Common Environment Variables:**

-   `ENV_PROFILE`: `local|dev|prd` (specifies the Redis cluster environment profile)
-   `REDIS_NODES`: `host1:port1,host2:port2,...` (overrides the default node list for the specified `ENV_PROFILE`)
-   `S3_URI`: `s3://your-bucket-name/your-prefix` (S3 path for backup uploads and restore downloads)
-   **AWS Credentials**: Prefer profile/role-based auth. You can provide credentials via:
  -   **Shared Credentials/Profile**: Mount your `~/.aws` directory and pass `AWS_PROFILE` (and `AWS_SDK_LOAD_CONFIG=1`), e.g., `-v $HOME/.aws:/root/.aws:ro -e AWS_PROFILE=toy-root -e AWS_SDK_LOAD_CONFIG=1`.
    -   **IAM Roles for Service Accounts (IRSA)**: For Kubernetes environments, configure an IRSA for the pod running the tool.

### Passing AWS Credentials with docker run

Using shared credentials + profile

```bash
export AWS_PROFILE=toy-root           # or another profile name

docker run --rm \
  -e ENV_PROFILE=local \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  -e AWS_PROFILE \
  -e AWS_SDK_LOAD_CONFIG=1 \
  -v "$HOME/.aws:/root/.aws:ro" \
  -v /tmp/redis-backups:/data/backups \
  redis-backup-tool:latest backup
```

Tip: You can also use the provided Makefile helpers with the same effect:

```bash
# Using shared credentials + profile (Makefile defaults AWS_PROFILE=toy-root)
make backup-local-profile S3_URI=s3://theshop-lake-dev/backup/redis BACKUP_DIR=./backups

# Restore latest
make restore-latest-profile S3_URI=s3://theshop-lake-dev/backup/redis

# List
make list-backups-profile S3_URI=s3://theshop-lake-dev/backup/redis
```

An `.env.example` file is included with helpful placeholders; copy it to `.env` as needed.

### Dev Workspace (uv)

This repo is configured as an Astral uv workspace for Python projects.

- Root `pyproject.toml` declares a workspace with two members: `redis-cluster-test` and `redis-backup-tool`.
- Use uv from the repo root to manage and run either project with a single shared lockfile.

Common commands (no Docker):

```bash
# Sync all workspace projects
uv sync

# Run the test client
uv run -p redis-cluster-test python redis-cluster-test/main.py

# Run the backup tool CLI (via __main__.py)
uv run --project redis-backup-tool python redis-backup-tool/__main__.py --help
```

### Local Dev Targets (no Docker)

Use Makefile helpers to run the tool locally via uv for fast iteration:

```bash
# Sync only the backup tool project
make dev-sync

# Backup locally (profile creds)
make dev-backup S3_URI=s3://theshop-lake-dev/backup/redis BACKUP_DIR=./backups \
  AWS_PROFILE=toy-root MATCH='user:*' CHUNK_KEYS=10000

# Restore latest from S3
make dev-restore-latest S3_URI=s3://theshop-lake-dev/backup/redis AWS_PROFILE=toy-root

# List backups
make dev-list S3_URI=s3://theshop-lake-dev/backup/redis AWS_PROFILE=toy-root

# Verify a local backup dir
make dev-verify INPUT_DIR=./backups/redis-backup-local-YYYYmmddThhmmssZ-xxxx SAMPLE=200 \
  AWS_PROFILE=toy-root
```

When not to use workspaces: If these projects ever need independent dependency resolution, release cadence, or isolated lockfiles, consider removing the workspace and using per-project `uv.lock` files instead. For now, a shared lock keeps versions consistent across tools that interact with the same Redis cluster.

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

**Important for Redis Cluster**: When inserting test data manually, always use the `-c` (cluster mode) flag with `redis-cli` to ensure proper data distribution across cluster nodes:

```bash
# Correct: Cluster-aware insertion (data distributed across nodes)
redis-cli -h 10.101.99.145 -p 7001 -c set user:1 "value1"
redis-cli -h 10.101.99.145 -p 7001 -c hmset profile:1 name "User1" email "user1@example.com"

# Incorrect: Direct insertion (all data goes to one node)
redis-cli -h 10.101.99.145 -p 7001 set user:1 "value1"  # Missing -c flag
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

### UV Workspace 사용법

루트 `pyproject.toml`로 `redis-cluster-test`, `redis-backup-tool`을 하나의 uv 워크스페이스로 통합했습니다.

- 실행 예시
  - `uv run -p redis-cluster-test python redis-cluster-test/main.py`
  - `uv run -p redis-backup-tool redis-backup-tool --help`
  - `uv run -p redis-backup-tool redis-backup-tool backup -e local -o /tmp/redis-backups`

### Notes and Known Issues

- Docker Desktop on macOS does not support `network_mode: host`. The `redis-1`…`redis-6` services in `docker-compose.yml` use host networking and are intended for Linux environments. On macOS, consider using Colima with host networking, or adapt the compose to bridge networking and adjust cluster creation accordingly.
- The `p3x-redis-ui` service expects an external network `dev_net`. Create it once with `docker network create dev_net`, or switch it to the default network if you don’t need an external shared network.
