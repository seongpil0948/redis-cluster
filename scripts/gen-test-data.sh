#!/usr/bin/env bash
set -euo pipefail

# Generate additional data types to broaden coverage:
# List, Set, Sorted Set, Stream
# Usage: IP=10.101.99.145 PORT=7001 ./scripts/gen_test_data.sh

IP=${IP:-10.101.99.145}
PORT=${PORT:-7001}

# Tunables (kept modest for speed)
LIST_N=${LIST_N:-1000}
SET_N=${SET_N:-1000}
ZSET_N=${ZSET_N:-1000}
STREAM_N=${STREAM_N:-10}

echo "[gen_test_data] Using IP=$IP PORT=$PORT"

# List
echo "[gen_test_data] Creating $LIST_N list keys (queue:*)..."
for i in $(seq 1 "$LIST_N"); do
  for j in 1 2 3 4 5; do
    redis-cli -h "$IP" -p "$PORT" -c lpush "queue:$i" "task-$i-$j|prio-$((j%3))|ts-$(date +%s)" >/dev/null || {
      echo "ERROR lpush queue:$i"; exit 1; }
  done
  if (( i % 200 == 0 )); then echo "  progress lists: $i/$LIST_N"; fi
done

# Set
echo "[gen_test_data] Creating $SET_N set keys (tags:*)..."
for i in $(seq 1 "$SET_N"); do
  redis-cli -h "$IP" -p "$PORT" -c sadd "tags:$i" \
    "tag$((i%20))" "tag$(( (i+1)%20 ))" "category$((i%10))" >/dev/null || {
    echo "ERROR sadd tags:$i"; exit 1; }
  if (( i % 200 == 0 )); then echo "  progress sets: $i/$SET_N"; fi
done

# Sorted Set
echo "[gen_test_data] Creating $ZSET_N sorted set keys (leaderboard:*)..."
for i in $(seq 1 "$ZSET_N"); do
  for j in 1 2 3 4 5 6 7 8 9 10; do
    redis-cli -h "$IP" -p "$PORT" -c zadd "leaderboard:$i" $((j*100 + i%100)) "player$j" >/dev/null || {
      echo "ERROR zadd leaderboard:$i"; exit 1; }
  done
  if (( i % 200 == 0 )); then echo "  progress zsets: $i/$ZSET_N"; fi
done

# Stream
echo "[gen_test_data] Creating $STREAM_N streams (stream:events:*)..."
for i in $(seq 1 "$STREAM_N"); do
  redis-cli -h "$IP" -p "$PORT" -c xadd "stream:events:$i" "*" \
    event_type "user_action" user_id $((i%1000)) action "click" timestamp "$(date +%s)" data "event_data_$i" >/dev/null || {
      echo "ERROR xadd stream:events:$i"; exit 1; }
  # Consumer group (ignore if exists)
  redis-cli -h "$IP" -p "$PORT" -c xgroup create "stream:events:$i" "processors" 0 mkstream 2>/dev/null || true
  if (( i % 2 == 0 )); then echo "  progress streams: $i/$STREAM_N"; fi
done

echo "[gen_test_data] Done."
