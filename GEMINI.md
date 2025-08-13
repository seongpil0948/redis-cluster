# GEMINI.md - redis-cluster

## Project Overview

This project sets up a 6-node Redis cluster using Docker Compose, configured to run as 3 masters with 3 replicas. It includes 6 Redis nodes, a cluster initialization service, and a P3X Redis UI for management. The configuration is generated from a template and a shell script, and is designed to simulate a production-like development environment.

**Technologies:**

*   Docker
*   Redis
*   Shell scripting
*   Makefile

**Architecture:**

*   Six Redis containers (`redis-1` to `redis-6`) are created, each with its own configuration and data volume.
*   A `redis-cluster-entry` container is used to initialize the Redis cluster with 3 masters and 3 replicas.
*   A `p3x-redis-ui` container provides a web-based UI for interacting with the Redis cluster.
*   The project uses a pre-existing external Docker network named `dev_net`.
*   The `make-conf.sh` script attempts to automatically determine the host IP for the cluster configuration.

## Building and Running

A `Makefile` is provided to simplify the management of the cluster.

1.  **Prerequisites**
    *   Ensure you have a Docker network named `dev_net`. If not, create it with `docker network create dev_net`.

2.  **Using the Makefile**
    *   **Generate configurations and start the cluster:** `make up` (this automatically calls `make gen-conf`)
    *   **Manually generate configurations:** `make gen-conf`
    *   **Stop the cluster:** `make down`
    *   **Clean the environment (stops cluster and removes all data):** `make clean`
    *   **Monitor logs:** `make logs`

## Accessing the Cluster

*   **Redis Nodes:** The Redis nodes are accessible on ports `7001` through `7006` on the host machine.
*   **P3X Redis UI:** The web UI is available at `http://localhost:7843`.

## Development Conventions

*   The Redis configuration is managed through the `redis-cluster.tmpl` template.
*   The `make-conf.sh` script is responsible for generating the final configuration files. It is called by the `make gen-conf` target.
*   The `Makefile` provides the primary interface for managing the lifecycle of the environment.
*   The `docker-compose.yml` file defines the services and their interactions.