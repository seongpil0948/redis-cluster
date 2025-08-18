

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
	dev-sync dev-backup dev-restore-latest dev-list dev-verify

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

# ---------- Convenience targets for redis-backup-tool ----------
# These targets forward your current shell's AWS env automatically when present.
# Set S3_URI and optionally BACKUP_DIR. For profile-based auth, set AWS_PROFILE
# and ensure $(HOME)/.aws is populated.

backup-local-profile: ## Run backup (shared creds + profile)
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	@mkdir -p "$(BACKUP_DIR)"
	docker run --rm \
	  -e ENV_PROFILE=local \
	  -e S3_URI="$(S3_URI)" \
	  -e AWS_PROFILE="$(AWS_PROFILE)" \
	  -e AWS_SDK_LOAD_CONFIG=1 \
	  $(if $(REDIS_NODES_OVERRIDE),-e REDIS_NODES="$(REDIS_NODES_OVERRIDE)",) \
	  -v "$(HOME)/.aws":"/root/.aws":ro \
	  -v "$(BACKUP_DIR)":"/data/backups" \
	  $(BACKUP_IMAGE) backup

restore-latest-profile: ## Restore latest from S3 (shared creds + profile)
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	docker run --rm \
	  -e ENV_PROFILE=local \
	  -e S3_URI="$(S3_URI)" \
	  -e AWS_PROFILE="$(AWS_PROFILE)" \
	  -e AWS_SDK_LOAD_CONFIG=1 \
	  $(if $(REDIS_NODES_OVERRIDE),-e REDIS_NODES="$(REDIS_NODES_OVERRIDE)",) \
	  -v "$(HOME)/.aws":"/root/.aws":ro \
	  $(BACKUP_IMAGE) restore --from-s3 latest --overwrite

list-backups-profile: ## List S3 backups (shared creds + profile)
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	docker run --rm \
	  -e S3_URI="$(S3_URI)" \
	  -e AWS_PROFILE="$(AWS_PROFILE)" \
	  -e AWS_SDK_LOAD_CONFIG=1 \
	  $(if $(REDIS_NODES_OVERRIDE),-e REDIS_NODES="$(REDIS_NODES_OVERRIDE)",) \
	  -v "$(HOME)/.aws":"/root/.aws":ro \
	  $(BACKUP_IMAGE) list

# ---------- Local dev (no Docker) using uv ----------
dev-sync:
	VIRTUAL_ENV= uv sync --project redis-backup-tool

dev-backup: ## Run backup locally via uv
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	@mkdir -p "$(BACKUP_DIR)"
	VIRTUAL_ENV= uv sync --project redis-backup-tool >/dev/null
	AWS_PROFILE="$(AWS_PROFILE)" AWS_SDK_LOAD_CONFIG=1 S3_URI="$(S3_URI)" VIRTUAL_ENV= \
	  $(if $(REDIS_NODES_OVERRIDE),REDIS_NODES="$(REDIS_NODES_OVERRIDE)",) \
	  uv run --project redis-backup-tool \
	  python redis-backup-tool/__main__.py backup --match "$(MATCH)" --chunk-keys $(or $(CHUNK_KEYS),5000)

dev-restore-latest: ## Restore latest from S3 locally via uv
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	VIRTUAL_ENV= uv sync --project redis-backup-tool >/dev/null
	AWS_PROFILE="$(AWS_PROFILE)" AWS_SDK_LOAD_CONFIG=1 VIRTUAL_ENV= \
	  $(if $(REDIS_NODES_OVERRIDE),REDIS_NODES="$(REDIS_NODES_OVERRIDE)",) \
	  uv run --project redis-backup-tool \
	  python redis-backup-tool/__main__.py restore --from-s3 latest --overwrite

dev-list: ## List S3 backups locally via uv
	@if [ -z "$(S3_URI)" ]; then echo "S3_URI is required"; exit 1; fi
	VIRTUAL_ENV= uv sync --project redis-backup-tool >/dev/null
	AWS_PROFILE="$(AWS_PROFILE)" AWS_SDK_LOAD_CONFIG=1 VIRTUAL_ENV= \
	  $(if $(REDIS_NODES_OVERRIDE),REDIS_NODES="$(REDIS_NODES_OVERRIDE)",) \
	  uv run --project redis-backup-tool \
	  python redis-backup-tool/__main__.py list

dev-verify: ## Verify local backup dir against cluster via uv
	@if [ -z "$(INPUT_DIR)" ]; then echo "INPUT_DIR is required (path to backup dir)"; exit 1; fi
	VIRTUAL_ENV= uv sync --project redis-backup-tool >/dev/null
	AWS_PROFILE="$(AWS_PROFILE)" AWS_SDK_LOAD_CONFIG=1 VIRTUAL_ENV= \
	  $(if $(REDIS_NODES_OVERRIDE),REDIS_NODES="$(REDIS_NODES_OVERRIDE)",) \
	  uv run --project redis-backup-tool \
	  python redis-backup-tool/__main__.py verify -i "$(INPUT_DIR)" --sample $(or $(SAMPLE),200)
