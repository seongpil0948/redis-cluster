# Makefile for managing the Redis Cluster environment

.PHONY: all up down clean logs build gen-conf test test-basic test-polling help

# Default action
all: up

# Generate Redis configurations
gen-conf:
	@echo "Generating Redis configurations..."
	./make-conf.sh

# Start the Redis cluster in detached mode
up: gen-conf
	@echo "Starting Redis cluster..."
	docker compose up -d --force-recreate --remove-orphans

# Stop and remove the Redis cluster containers
down:
	@echo "Stopping Redis cluster..."
	docker compose down

# Clean up all generated configuration and data
clean:
	@echo "Cleaning up Redis cluster configuration and data..."
	docker compose down -v
	rm -rf 700*

# View logs of all services
logs:
	docker compose logs -f

# Build the docker images (if needed)
build:
	@echo "Building Docker images..."
	docker compose build

# Run basic Redis cluster tests
test-basic:
	@echo "Running basic Redis cluster tests..."
	cd redis-cluster-test && uv run python main.py

# Run polling tests for continuous monitoring (30 seconds)
test-polling:
	@echo "Running Redis cluster polling tests (600s)..."
	cd redis-cluster-test && uv run python polling_app.py --duration 600

# Show help
help:
	@echo "Redis Cluster Management:"
	@echo ""
	@echo "Basic Commands:"
	@echo "  make up          - Start Redis cluster"
	@echo "  make down        - Stop Redis cluster"
	@echo "  make clean       - Clean up cluster data"
	@echo "  make logs        - View cluster logs"
	@echo ""
	@echo "Testing:"
	@echo "  make test        - Run all tests"
	@echo "  make test-basic  - Run basic functionality tests"
	@echo "  make test-polling - Run polling tests (30s)"
	@echo "  make test-full   - Start cluster and run all tests"