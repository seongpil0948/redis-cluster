# --- Load environment early --------------------------------------------------
# Load variables from .env.local (if present) before any targets/commands run.
# This allows you to keep local overrides for items like S3_URI, AWS_PROFILE,
# ECR_REGISTRY, ECR_REPO, ECR_REGION, IP, etc.
ENV_FILE ?= .env.local
ifneq (,$(wildcard $(ENV_FILE)))
include $(ENV_FILE)
$(info Loaded environment variables from $(ENV_FILE))
else
$(info No $(ENV_FILE) found; using Makefile defaults and shell env)
endif

# Export all variables so they are visible to docker, uv, and other recipes.
.EXPORT_ALL_VARIABLES:

.PHONY: all up down clean gen-conf logs build-backup-tool ecr-login push-backup-tool-to-ecr \
	backup-local-profile restore-latest-profile list-backups-profile \
	dev-sync backup dev-restore-latest dev-list dev-verify

# Variables
CONF_DIR := $(shell pwd)
REDIS_NODES := 6
REDIS_PORTS := $(shell seq -s ' ' 7001 700$(REDIS_NODES))

# Backup tool defaults (override per-invocation)
S3_URI ?=
BACKUP_DIR ?= $(CONF_DIR)/backups
AWS_PROFILE ?= toy-root  # default profile for AWS CLI; override as needed

# Docker image for the backup tool (override to use ECR image)
BACKUP_IMAGE ?= redis-backup-tool:latest

# If an IP is provided (e.g., in .env.local), build a default 6-node list for ports 7001-7006.
# You can still override explicitly by passing REDIS_NODES=host1:port,... on the make command line.
ifdef IP
REDIS_NODES_OVERRIDE := $(IP):7001,$(IP):7002,$(IP):7003,$(IP):7004,$(IP):7005,$(IP):7006
endif

# ECR push settings
# ECR_REGISTRY should be the registry hostname only (no repo path), e.g. 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com
ECR_REGISTRY ?=
# ECR_REPO is the repository path/name in ECR, e.g. util/redis-backup-tool or just redis-backup-tool
ECR_REPO ?= redis-backup-tool
# ECR_REGION is required for login (e.g., ap-northeast-2)
ECR_REGION ?=

# --- Example (verified working) ---
# export ECR_REGISTRY="008971653402.dkr.ecr.ap-northeast-2.amazonaws.com"
# export ECR_REPO="util/redis-backup-tool"   # or just "redis-backup-tool"
# export ECR_REGION="ap-northeast-2"
# export AWS_PROFILE="toy-root" # optional
# make push-backup-tool-to-ecr

# Docker Compose commands
DOCKER_COMPOSE := docker-compose -f docker-compose.yml

all: up

up: gen-conf
	$(DOCKER_COMPOSE) up -d

down:
	$(DOCKER_COMPOSE) down

clean: down
	rm -rf 7001 7002 7003 7004 7005 7006
	rm -f redis-cluster.conf
	# Clean for redis-backup-tool
	rm -rf redis-backup-tool/build redis-backup-tool/dist redis-backup-tool/*.egg-info

gen-conf:
	./make-conf.sh

logs:
	$(DOCKER_COMPOSE) logs -f

# New targets for redis-backup-tool
build-backup-tool:
	docker build -t redis-backup-tool:latest -f redis-backup-tool/Dockerfile redis-backup-tool/

ecr-login:
	@if [ -z "$(ECR_REGISTRY)" ]; then \
		echo "Error: ECR_REGISTRY is required (e.g., 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com)"; \
		exit 1; \
	fi
	@if [ -z "$(ECR_REGION)" ]; then \
		echo "Error: ECR_REGION is required (e.g., ap-northeast-2)"; \
		exit 1; \
	fi
	@echo "Logging in to ECR: $(ECR_REGISTRY) (region=$(ECR_REGION))"
	@sh -c 'PROFILE_ARG=""; \
	  if [ -n "$(AWS_PROFILE)" ]; then PROFILE_ARG="--profile $(AWS_PROFILE)"; fi; \
	 echo "Using AWS_PROFILE: $(AWS_PROFILE)"; \
	 aws ecr get-login-password --region "$(ECR_REGION)" $$PROFILE_ARG | docker login --username AWS --password-stdin "$(ECR_REGISTRY)"'

pull-backup: ecr-login
	@if [ -z "$(ECR_REGISTRY)" ]; then \
		echo "Error: ECR_REGISTRY is required (e.g., 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com)"; \
		exit 1; \
	fi
	@if [ -z "$(ECR_REPO)" ]; then \
		echo "Error: ECR_REPO is not set (e.g., util/redis-backup-tool or redis-backup-tool)"; \
		exit 1; \
	fi
	@echo "Pulling image from ECR: $(ECR_REGISTRY)/$(ECR_REPO):latest"
	docker pull "$(ECR_REGISTRY)/$(ECR_REPO):latest"

push-backup-tool-to-ecr: build-backup-tool ecr-login
	@if [ -z "$(ECR_REGISTRY)" ]; then \
		echo "Error: ECR_REGISTRY environment variable is not set."; \
		echo "Set it to your ECR registry host (e.g., 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com)"; \
		exit 1; \
	fi
	@if [ -z "$(ECR_REPO)" ]; then \
		echo "Error: ECR_REPO is not set (e.g., util/redis-backup-tool or redis-backup-tool)"; \
		exit 1; \
	fi
	@echo "Tagging image as $(ECR_REGISTRY)/$(ECR_REPO):latest"
	docker tag redis-backup-tool:latest "$(ECR_REGISTRY)/$(ECR_REPO):latest"
	docker push "$(ECR_REGISTRY)/$(ECR_REPO):latest"



# ---------- Local Development & CI Targets (uv) ----------
# These targets run the tools locally using uv, which is faster for development.
# They rely on the centralized ./config.json for node addresses.

# Ensure dependencies are installed before running any target
.PHONY: sync
sync:
	uv sync

# --- Internal Generic Targets (called by env-specific targets below) ---
.PHONY: _backup _restore-latest _restore-id _list-backups _verify-backup

_backup: sync
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	@if [ -z "$(ENV_PROFILE)" ]; then echo "ENV_PROFILE is required (e.g., local, dev, prd)"; exit 1; fi
	@echo "--- Running backup for [$(ENV_PROFILE)] to [$(S3_URI)] ---"
	@mkdir -p "$(BACKUP_DIR)"
	AWS_PROFILE="$(AWS_PROFILE)" AWS_SDK_LOAD_CONFIG=1 S3_URI="$(S3_URI)" REDIS_NODES= \
	  uv run -- \
	  python redis-backup-tool/__main__.py backup --env-profile "$(ENV_PROFILE)" --out-dir "$(BACKUP_DIR)" --s3-uri "$(S3_URI)"

_restore-latest: sync
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	@if [ -z "$(ENV_PROFILE)" ]; then echo "ENV_PROFILE is required (e.g., local, dev, prd)"; exit 1; fi
	@echo "--- Restoring latest backup for [$(ENV_PROFILE)] from [$(S3_URI)] ---"
	AWS_PROFILE="$(AWS_PROFILE)" AWS_SDK_LOAD_CONFIG=1 REDIS_NODES= \
	  uv run -- \
	  python redis-backup-tool/__main__.py restore --env-profile "$(ENV_PROFILE)" --from-s3 latest --s3-uri "$(S3_URI)" --overwrite

_restore-id: sync
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	@if [ -z "$(BACKUP_ID)" ]; then echo "BACKUP_ID is required"; exit 1; fi
	@if [ -z "$(ENV_PROFILE)" ]; then echo "ENV_PROFILE is required (e.g., local, dev, prd)"; exit 1; fi
	@echo "--- Restoring backup [$(BACKUP_ID)] for [$(ENV_PROFILE)] from [$(S3_URI)] ---"
	AWS_PROFILE="$(AWS_PROFILE)" AWS_SDK_LOAD_CONFIG=1 REDIS_NODES= \
	  uv run -- \
	  python redis-backup-tool/__main__.py restore --env-profile "$(ENV_PROFILE)" --from-s3 "$(BACKUP_ID)" --s3-uri "$(S3_URI)" --overwrite

_list-backups: sync
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	AWS_PROFILE="$(AWS_PROFILE)" AWS_SDK_LOAD_CONFIG=1 REDIS_NODES= \
	  uv run -- \
	  python redis-backup-tool/__main__.py list --s3-uri "$(S3_URI)"

_verify-backup: sync
	@if [ -z "$(INPUT_DIR)" ]; then echo "INPUT_DIR is required (path to backup dir)"; exit 1; fi
	@if [ -z "$(ENV_PROFILE)" ]; then echo "ENV_PROFILE is required (e.g., local, dev, prd)"; exit 1; fi
	AWS_PROFILE="$(AWS_PROFILE)" AWS_SDK_LOAD_CONFIG=1 REDIS_NODES= \
	  uv run -- \
	  python redis-backup-tool/__main__.py verify --env-profile "$(ENV_PROFILE)" -i "$(INPUT_DIR)" --sample $$(or $$(SAMPLE),200)


# --- User-facing Backup & Restore Targets ---
.PHONY: backup-local backup-dev backup-prd \
        restore-latest-local restore-latest-dev restore-latest-prd \
        restore-id-local restore-id-dev restore-id-prd \
        list-backups \
        verify-backup-local verify-backup-dev verify-backup-prd

backup-local: ENV_PROFILE=local
backup-local: _backup
backup-dev: ENV_PROFILE=dev
backup-dev: _backup
backup-prd: ENV_PROFILE=prd
backup-prd: _backup

restore-latest-local: ENV_PROFILE=local
restore-latest-local: _restore-latest
restore-latest-dev: ENV_PROFILE=dev
restore-latest-dev: _restore-latest
restore-latest-prd: ENV_PROFILE=prd
restore-latest-prd: _restore-latest

restore-id-local: ENV_PROFILE=local
restore-id-local: _restore-id
restore-id-dev: ENV_PROFILE=dev
restore-id-dev: _restore-id
restore-id-prd: ENV_PROFILE=prd
restore-id-prd: _restore-id

list-backups: _list-backups

verify-backup-local: ENV_PROFILE=local
verify-backup-local: _verify-backup
verify-backup-dev: ENV_PROFILE=dev
verify-backup-dev: _verify-backup
verify-backup-prd: ENV_PROFILE=prd
verify-backup-prd: _verify-backup



# ---------- Testing Targets ----------
.PHONY: test-cluster-local test-cluster-dev test-cluster-prd poll-cluster-local poll-cluster-dev poll-cluster-prd

test-cluster-local:
	uv run -- python redis-cluster-test/main.py --env local

test-cluster-dev:
	uv run -- python redis-cluster-test/main.py --env dev

test-cluster-prd:
	uv run -- python redis-cluster-test/main.py --env prd

poll-cluster-local:
	uv run -- python redis-cluster-test/polling_app.py --env local --duration 60

poll-cluster-dev:
	uv run -- python redis-cluster-test/polling_app.py --env dev --duration 60

poll-cluster-prd:
	uv run -- python redis-cluster-test/polling_app.py --env prd --duration 60

# ---------- Destructive Operations ----------
.PHONY: flush-local-cluster

flush-local-cluster:
	@echo "🚨 WARNING: This will run FLUSHALL on all nodes in the 'local' cluster (10.101.99.145:7001-7006)."
	@echo "Discovering master nodes..."; \
	PRIMARIES=$$(redis-cli -h 10.101.99.145 -p 7001 cluster nodes \
	  | awk '$$3 ~ /master/ && $$3 !~ /fail/ { split($$2,a,"@"); print a[1] }' \
	  | sort -n | uniq); \
	if [ -z "$$PRIMARIES" ]; then \
	  echo "No master nodes found or unable to query cluster topology."; \
	  exit 1; \
	fi; \
	echo "Master nodes:"; \
	for p in $$PRIMARIES; do echo "  - $$p"; done; \
	echo "Running FLUSHALL on masters..."; \
	for p in $$PRIMARIES; do \
	  echo "Flushing $$p..."; \
	  redis-cli -h $${p%:*} -p $${p#*:} flushall; \
	done
	@echo "✨ Cluster flush complete."

# ---------- Cluster Status Targets ----------
.PHONY: status-local status-dev status-prd

# Helper to get the first host:port for a given environment from config.json
get_entry_node = $(shell jq -r '.redis_nodes."$(1)".nodes[0]' config.json)

# Generic status target
.PHONY: _status
_status:
	@if [ -z "$(ENV_PROFILE)" ]; then echo "ENV_PROFILE is required"; exit 1; fi
	@NODE=$(call get_entry_node,$(ENV_PROFILE)); \
	if [ -z "$$NODE" ] || [ "$$NODE" = "null" ]; then \
		echo "No nodes found for profile $(ENV_PROFILE) in config.json"; \
		exit 1; \
	fi; \
	IP=$${NODE%:*}; \
	PORT=$${NODE#*:}; \
	echo "--- Getting status for [$(ENV_PROFILE)] cluster (entrypoint: $$IP:$$PORT) ---"; \
	PRIMARIES=$$(redis-cli -h $$IP -p $$PORT cluster nodes \
	  | awk '$$3 ~ /master/ && $$3 !~ /fail/ { split($$2,a,"@"); print a[1] }' \
	  | sort -n | uniq); \
	echo "Primary nodes:"; \
	for p in $$PRIMARIES; do \
		echo -n "  - Node $$p "; \
		redis-cli -h $${p%:*} -p $${p#*:} dbsize | awk '{printf "(%s keys)\n", $$1}'; \
	done; \
	TOTAL=$$(for p in $$PRIMARIES; do redis-cli -h $${p%:*} -p $${p#*:} dbsize; done | awk '{s+=$$1} END{print s}'); \
	echo "Total keys across all primaries: $$TOTAL";

status-local: ENV_PROFILE=local
status-local: _status

status-dev: ENV_PROFILE=dev
status-dev: _status

status-prd: ENV_PROFILE=prd
status-prd: _status