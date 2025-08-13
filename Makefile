# Makefile for managing the Redis Cluster environment

.PHONY: all up down clean logs build gen-conf

# Default action
all: up

# Generate Redis configurations
gen-conf:
	@echo "Generating Redis configurations..."
	./make-conf.sh

# Start the Redis cluster in detached mode
up: gen-conf
	@echo "Starting Redis cluster..."
	docker-compose up -d --force-recreate --remove-orphans

# Stop and remove the Redis cluster containers
down:
	@echo "Stopping Redis cluster..."
	docker-compose down

# Clean up all generated configuration and data
clean:
	@echo "Cleaning up Redis cluster configuration and data..."
	docker-compose down -v
	rm -rf 700*

# View logs of all services
logs:
	docker-compose logs -f

# Build the docker images (if needed)
build:
	@echo "Building Docker images..."
	docker-compose build