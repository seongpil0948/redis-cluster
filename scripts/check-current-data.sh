IP=${IP:-10.101.99.145}
PORT=${PORT:-7001}
echo "[check_current_data] Using IP=$IP PORT=$PORT"

PRIMARIES=$(redis-cli -h $IP -p 7001 cluster nodes \
  | awk '$3 ~ /master/ && $3 !~ /fail/ {split($2,a,":"); split(a[2],b,"@"); print b[1]}' \
  | sort -n | uniq)

# 총 키 개수 확인
TOTAL=$(for p in $PRIMARIES; do redis-cli -h $IP -p $p dbsize; done | awk '{s+=$1} END{print s}')
echo "TOTAL_KEYS=$TOTAL"

# 데이터 타입별 개수 확인 (클러스터 모드로 조회)
echo "String keys: $(redis-cli -h $IP -p 7001 -c eval "return #redis.call('keys', 'user:*')" 0)"
echo "Hash keys: $(redis-cli -h $IP -p 7001 -c eval "return #redis.call('keys', 'profile:*')" 0)"  
echo "List keys: $(redis-cli -h $IP -p 7001 -c eval "return #redis.call('keys', 'queue:*')" 0)"
echo "Set keys: $(redis-cli -h $IP -p 7001 -c eval "return #redis.call('keys', 'tags:*')" 0)"
echo "Sorted Set keys: $(redis-cli -h $IP -p 7001 -c eval "return #redis.call('keys', 'leaderboard:*')" 0)"
echo "Stream keys: $(redis-cli -h $IP -p 7001 -c eval "return #redis.call('keys', 'stream:*')" 0)"

# 클러스터 간 데이터 분산 확인
echo "Data distribution across cluster nodes:"
for p in $PRIMARIES; do 
  count=$(redis-cli -h $IP -p $p dbsize)
  echo "Node $p: $count keys"
done

# 클러스터 데이터 분산 상세 확인
echo ""
echo "Detailed data distribution by data type:"
for p in $PRIMARIES; do
  echo "=== Node $p ==="
  echo "  user:* count: $(redis-cli -h $IP -p $p eval "return #redis.call('keys', 'user:*')" 0)"
  echo "  profile:* count: $(redis-cli -h $IP -p $p eval "return #redis.call('keys', 'profile:*')" 0)"
  echo "  queue:* count: $(redis-cli -h $IP -p $p eval "return #redis.call('keys', 'queue:*')" 0)"
  echo "  tags:* count: $(redis-cli -h $IP -p $p eval "return #redis.call('keys', 'tags:*')" 0)"
  echo "  leaderboard:* count: $(redis-cli -h $IP -p $p eval "return #redis.call('keys', 'leaderboard:*')" 0)"
done

# 데이터 분산이 균등한지 확인 (모든 노드에 데이터가 있어야 함)
echo ""
echo "⚠️ 데이터 분산 검증:"
echo "- 각 노드에 데이터가 고르게 분산되어 있는지 확인하세요"
echo "- 만약 한 노드에만 데이터가 몰려있다면 -c 플래그 없이 삽입된 것입니다"
echo "- 정상적인 클러스터 분산에서는 모든 마스터 노드에 데이터가 존재해야 합니다"

echo "=== String 타입 데이터 샘플 ==="
for i in 1 100 500 1000; do
    value=$(redis-cli -h $IP -p 7001 -c get "user:$i")
    ttl=$(redis-cli -h $IP -p 7001 -c ttl "user:$i")
    echo "user:$i = $value (TTL: $ttl seconds)"
done


echo ""
echo "=== Hash 타입 데이터 샘플 ==="
for i in 1 100 500 1000; do
    echo "profile:$i:"
    redis-cli -h $IP -p 7001 -c hgetall "profile:$i"
    echo ""
done


echo ""
echo "=== List 타입 데이터 샘플 ==="
for i in 1 100 500; do
    echo "queue:$i (length: $(redis-cli -h $IP -p 7001 -c llen "queue:$i")):"
    redis-cli -h $IP -p 7001 -c lrange "queue:$i" 0 2
    echo ""
done


echo ""
echo "=== Set 타입 데이터 샘플 ==="
for i in 1 100 500; do
    echo "tags:$i (cardinality: $(redis-cli -h $IP -p 7001 -c scard "tags:$i")):"
    redis-cli -h $IP -p 7001 -c smembers "tags:$i"
    echo ""
done


echo ""
echo "=== Sorted Set 타입 데이터 샘플 ==="
for i in 1 100 500; do
    echo "leaderboard:$i (count: $(redis-cli -h $IP -p 7001 -c zcard "leaderboard:$i")):"
    redis-cli -h $IP -p 7001 -c zrange "leaderboard:$i" 0 4 withscores
    echo ""
done


echo ""
echo "=== Stream 타입 데이터 샘플 ==="
for i in 1 5; do
    echo "stream:events:$i (length: $(redis-cli -h $IP -p 7001 -c xlen "stream:events:$i")):"
    redis-cli -h $IP -p 7001 -c xrange "stream:events:$i" - + count 2
    echo ""
done


echo ""
echo "=== 메모리 사용량 분석 ==="
echo "각 노드별 메모리 사용량:"
for p in $PRIMARIES; do
    used_memory=$(redis-cli -h $IP -p $p info memory | grep used_memory_human | cut -d: -f2 | tr -d '\r')
    echo "Node $p: $used_memory"
done

# End of script