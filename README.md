# Redis Cluster Development Environment

This project provides a Docker-based Redis cluster for development and testing purposes. It sets up a 6-node cluster with 3 masters and 3 replicas, allowing for the simulation of a production-like Redis environment, including master-replica replication and failover testing.

## Features

- **6-Node Redis Cluster**: 3 master nodes and 3 replica nodes.
- **Docker Compose**: Easily manage the entire cluster with Docker Compose.
- **Production-like Configuration**: The Redis configuration is based on best practices for a production environment.
- **P3X Redis UI**: Includes a web-based UI for easy management and monitoring of the cluster.
- **Simplified Management**: A `Makefile` is provided to streamline common tasks.

## Prerequisites

- Docker
- Docker Compose
- A pre-existing external Docker network named `dev_net`. If you don't have one, you can create it with `docker network create dev_net`.

## Getting Started

Use the provided `Makefile` to manage the cluster. The `make up` command will automatically generate the necessary Redis configurations and start the cluster.

```bash
# Generate configs and start the cluster
make up

# Stop the cluster
make down

# Stop the cluster and remove all data
make clean

# View the logs of all services
make logs

# Manually generate Redis configurations
make gen-conf
```

## Accessing the Cluster

-   **Redis Nodes**: The Redis nodes are accessible on ports `7001` through `7006` on your host machine.
-   **P3X Redis UI**: The web UI is available at `http://localhost:7843`.

## Cluster Configuration

-   The Redis configuration is generated from the `redis-cluster.tmpl` template via the `make gen-conf` command.
-   The `make-conf.sh` script, called by the make target, generates the individual configuration files for each node in the `700x/conf` directories.
-   To customize the Redis configuration, modify the `redis-cluster.tmpl` file and regenerate the configurations with `make gen-conf`, then restart the cluster.

## Redis Cluster Operational Commands

Here are some common Redis commands useful for managing and troubleshooting the cluster. You can execute these commands using `redis-cli` within one of the Redis containers.

To connect to a Redis node:
```bash
docker exec -it redis-1 redis-cli -p 7001
```
(Replace `redis-1` and `7001` with the desired node and port)

### Cluster Information

-   `CLUSTER INFO`: Provides general information about the cluster state.
    ```bash
    CLUSTER INFO
    ```
-   `CLUSTER NODES`: Shows a list of all nodes in the cluster, their roles (master/replica), and their state.
    ```bash
    CLUSTER NODES
    ```

### Data Management

-   `BGSAVE`: Forces a background save of the dataset to disk.
    ```bash
    BGSAVE
    ```
-   `SAVE`: Synchronously saves the dataset to disk. (Caution: This command blocks the Redis server).
    ```bash
    SAVE
    ```

### Troubleshooting and Monitoring

-   `INFO`: Returns information and statistics about the server in a format that is simple to parse by computers and easy to read by humans.
    ```bash
    INFO
    ```
-   `MONITOR`: Streams back every command processed by the Redis server. Useful for real-time debugging.
    ```bash
    MONITOR
    ```
-   `SLOWLOG GET [count]`: Returns the Redis Slow Log. Useful for identifying slow queries.
    ```bash
    SLOWLOG GET 10
    ```
-   `CLIENT LIST`: Returns a list of all connected clients (servers and clients).
    ```bash
    CLIENT LIST
    ```
-   `CONFIG GET <parameter>`: Get the value of a configuration parameter.
    ```bash
    CONFIG GET maxmemory
    ```
-   `CONFIG SET <parameter> <value>`: Set a configuration parameter to a new value.
    ```bash
    CONFIG SET maxmemory 1gb
    ```

### Cluster Resharding and Failover (Advanced)

These commands are for advanced cluster management and should be used with caution.

-   `redis-cli --cluster reshard <host>:<port> --from <node-id> --to <node-id> --slots <number-of-slots> --yes`: Reshards hash slots from one node to another.
-   `redis-cli --cluster failover <host>:<port>`: Forces a manual failover of a master node.

Remember to replace `<host>:<port>` and `<node-id>` with actual values from your cluster.
