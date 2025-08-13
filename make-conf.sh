
#!/bin/bash
for port in {7001..7006}; 
do
mkdir -p ./${port}/data;
mkdir -p ./${port}/conf && PORT=${port} IP=10.101.91.145 envsubst < ./redis-cluster.tmpl > ./${port}/conf/redis.conf; 
done
