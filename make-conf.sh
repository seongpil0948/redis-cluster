#!/bin/bash
set -a
source .env.local
set +a
echo "Using IP: $IP"


for i in `seq 6`
do
    port=$((7000 + i))
    echo "Creating config for port ${port}"
    mkdir -p ./${port}/data
    mkdir -p ./${port}/conf
    PORT=${port} IP=${IP} envsubst < ./redis-cluster.tmpl > ./${port}/conf/redis.conf
done