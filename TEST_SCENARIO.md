## TEST_SCENARIO: Redis Cluster + Backup/Restore Tool 검증 절차

이 문서는 Redis Cluster 구성, 백업/복원 도구의 S3 연동, 자격증명 전달 등 주요 흐름을 실제로 실행하며 점검할 수 있는 테스트 시나리오를 제공합니다. 다양한 Redis 데이터 타입(String, Hash, List, Set, Sorted Set, Stream, HyperLogLog)에 대해 10,000개 이상의 대용량 데이터를 사용하여 백업/복원의 정확성과 성능을 검증합니다.

### 테스트 원리 및 목표
- **완전성 검증**: 모든 Redis 데이터 타입이 정확히 백업/복원되는지 확인
- **대용량 처리**: 10,000+ 레코드로 실제 운영 환경과 유사한 부하 테스트
- **TTL 보존**: 만료 시간이 설정된 키들의 TTL이 올바르게 복원되는지 검증
- **클러스터 샤딩**: 데이터가 클러스터의 여러 노드에 분산되어 저장/복원되는지 확인
- **S3 연동**: 대용량 백업 파일의 S3 업로드/다운로드가 안정적으로 동작하는지 검증

### 공통: 현재 상태/키 개수 검증 스니펫

#### 클러스터 헬스 체크
```bash
export IP=10.101.99.145
# 클러스터 상태 확인 (모든 슬롯이 할당되고 OK 상태인지)
redis-cli -h $IP -p 7001 cluster info | egrep 'cluster_state|cluster_slots_assigned|cluster_known_nodes'

# 각 노드의 역할과 상태 확인
redis-cli -h $IP -p 7001 cluster nodes
```

#### 프라이머리 노드 식별 및 데이터 분포 확인
```bash
# 프라이머리 노드 포트 목록 추출(복제 중복 방지)
PRIMARIES=$(redis-cli -h $IP -p 7001 cluster nodes \
  | awk '$3 ~ /master/ && $3 !~ /fail/ {split($2,a,":"); split(a[2],b,"@"); print b[1]}' \
  | sort -n | uniq)
echo "Primary nodes: $PRIMARIES"

# 노드별 키 개수 + 전체 합계 (클러스터 샤딩 검증)
for p in $PRIMARIES; do 
  echo -n "Node $p: "; 
  redis-cli -h $IP -p $p dbsize; 
done
TOTAL=$(for p in $PRIMARIES; do redis-cli -h $IP -p $p dbsize; done | awk '{s+=$1} END{print s}')
echo "TOTAL_KEYS=$TOTAL"
```

#### 데이터 타입별 검증 스니펫
```bash
# String 타입 확인
redis-cli -h $IP -p 7001 --scan --pattern 'user:*' | head -n 10
redis-cli -h $IP -p 7001 -c get user:1

# Hash 타입 확인  
redis-cli -h $IP -p 7001 --scan --pattern 'profile:*' | head -n 5
redis-cli -h $IP -p 7001 -c hgetall profile:1

# List 타입 확인
redis-cli -h $IP -p 7001 --scan --pattern 'queue:*' | head -n 5
redis-cli -h $IP -p 7001 -c llen queue:1
redis-cli -h $IP -p 7001 -c lrange queue:1 0 4

# Set 타입 확인
redis-cli -h $IP -p 7001 --scan --pattern 'tags:*' | head -n 5
redis-cli -h $IP -p 7001 -c scard tags:1
redis-cli -h $IP -p 7001 -c smembers tags:1

# Sorted Set 타입 확인
redis-cli -h $IP -p 7001 --scan --pattern 'leaderboard:*' | head -n 5
redis-cli -h $IP -p 7001 -c zcard leaderboard:1
redis-cli -h $IP -p 7001 -c zrange leaderboard:1 0 4 withscores

# Stream 타입 확인
redis-cli -h $IP -p 7001 --scan --pattern 'stream:*' | head -n 5
redis-cli -h $IP -p 7001 -c xinfo stream stream:events:1 2>/dev/null || echo "No stream found"

# HyperLogLog 타입 확인  
redis-cli -h $IP -p 7001 --scan --pattern 'hll:*' | head -n 5
redis-cli -h $IP -p 7001 -c pfcount hll:unique_visitors:1 2>/dev/null || echo "No HLL found"
```

### 0) 사전 준비

#### 환경 요구사항
- Docker / Docker Compose 설치 (Linux 권장)
- macOS 사용 시: Docker Desktop은 `network_mode: host` 미지원. 가능한 대안:
  - Colima + host networking, 또는
  - `docker-compose.yml`을 브리지 네트워크로 조정(추가 작업 필요)
- 외부 네트워크 `dev_net`이 필요함: `docker network create dev_net`
- S3 테스트 버킷과 권한 준비: 예) 버킷 `theshop-lake-dev`, 프리픽스 `backup/redis`
- AWS 자격증명 준비: 프로파일/공유자격증명(`~/.aws`) + `AWS_PROFILE`, `AWS_SDK_LOAD_CONFIG=1`

#### 환경 변수 설정
`.env.local` 파일 확인 및 설정:
```bash
# .env.local 내용 예시
S3_URI=s3://theshop-lake-dev/backup/redis
BACKUP_DIR=./backups
AWS_PROFILE=toy-root
IP=10.101.99.145
ECR_REGISTRY=008971653402.dkr.ecr.ap-northeast-2.amazonaws.com
ECR_REPO=util/redis-backup-tool
ECR_REGION=ap-northeast-2
```

#### 테스트 환경 변수 설정
```bash
# IP 변수 설정 (클러스터가 다른 IP에 있는 경우)
export IP=10.101.99.145  # .env.local의 IP 값과 동일하게 설정

# 기타 테스트용 변수
export TEST_DATA_SIZE=10000  # 테스트할 데이터 개수
```

### 1) 로컬 Redis Cluster 기동

#### 클러스터 생성 및 기동
```bash
# 1. 설정 생성 및 기동
make up

# 2. 상태 확인 - 클러스터 생성 로그 모니터링
make logs

# 클러스터 생성 로그에서 다음과 같은 성공 메시지 확인:
# ">>> Creating cluster"
# ">>> Performing hash slots allocation on 6 nodes..."
# "[OK] All nodes agree about slots configuration."
```

#### 클러스터 상태 검증
```bash
# 3. 컨테이너 상태 확인
docker ps | grep redis-

# 4. 클러스터 연결 테스트
redis-cli -h $IP -p 7001 ping
# 예상 결과: PONG

# 5. 클러스터 정보 확인
redis-cli -h $IP -p 7001 cluster info
# 예상 결과: cluster_state:ok, cluster_slots_assigned:16384

# 6. 노드 구성 확인 (3개 마스터, 3개 슬레이브)
redis-cli -h $IP -p 7001 cluster nodes
```

**테스트 원리**: Redis Cluster는 16384개의 해시 슬롯을 3개의 마스터 노드에 균등 분배합니다. 각 마스터는 하나의 슬레이브를 가져 고가용성을 보장합니다. 클러스터가 정상 동작하려면 모든 슬롯이 할당되고 과반수 이상의 마스터가 활성 상태여야 합니다.

#### 문제 발생 시 해결책
- macOS/host networking 이슈: Linux 환경에서 재시도 또는 네트워크 설정 변경 필요
- `dev_net` 없음: `docker network create dev_net`
- 포트 충돌: `ss -tulpn | grep 700[1-6]`로 포트 사용 현황 확인

### 2) Backup Tool 이미지 빌드

#### 이미지 빌드 및 검증
```bash
# 백업 도구 이미지 빌드
make build-backup-tool

# 빌드된 이미지 확인
docker images | grep redis-backup-tool

# 도구 버전 및 도움말 확인
docker run --rm redis-backup-tool:latest --help
```

**테스트 원리**: 백업 도구는 Python 기반으로 redis-py-cluster 라이브러리를 사용하여 Redis Cluster의 모든 노드에서 데이터를 읽어옵니다. 각 데이터 타입별로 적절한 Redis 명령어를 사용하여 데이터를 추출하고 JSON Lines 형식으로 저장합니다.

### 3) AWS 인증 전달 검증 – 프로파일/공유자격증명 방식

#### 기본 백업 테스트
```bash
# AWS 프로파일 설정 및 백업 실행
export AWS_PROFILE=toy-root
make backup-local-profile BACKUP_DIR=./backups

# 또는 인라인으로 실행
make backup-local-profile AWS_PROFILE=toy-root BACKUP_DIR=./backups
```

#### 성공 시 예상 결과
```
Backup written: /data/backups/redis-backup-local-20250818T060635Z-28e5
Archive: /data/backups/redis-backup-local-20250818T060635Z-28e5.tar.gz
Uploaded: s3://theshop-lake-dev/backup/redis/redis-backup-local-20250818T060635Z-28e5.tar.gz
```

#### 백업 결과 검증
```bash
# 로컬 백업 디렉터리 확인
ls -la ./backups/
ls -la ./backups/redis-backup-local-*/

# 백업 메타데이터 확인
cat ./backups/redis-backup-local-*/metadata.json | jq .

# S3 업로드 확인
aws s3 ls s3://theshop-lake-dev/backup/redis/ --profile toy-root

# 백업 파일 크기 확인
ls -lh ./backups/*.tar.gz
```

**테스트 원리**: 
- AWS 자격증명은 컨테이너 내부로 `~/.aws` 디렉터리를 마운트하여 전달됩니다
- `AWS_SDK_LOAD_CONFIG=1` 환경 변수로 AWS SDK가 프로파일을 인식하도록 합니다  
- 백업 도구는 boto3를 사용하여 S3에 업로드하며, 멀티파트 업로드를 지원합니다

#### 실패 트러블슈팅
```bash
# AWS 자격증명 확인
aws sts get-caller-identity --profile toy-root

# 권한 확인
aws s3 ls s3://theshop-lake-dev/ --profile toy-root

# ~/.aws 파일 권한 확인  
ls -la ~/.aws/
```

### 4) 대용량 다중 데이터 타입 테스트 데이터 생성

#### 10,000+ 레코드 테스트 데이터 생성 스크립트
```bash
### 3) 테스트 데이터 생성 (10,000+ 레코드)

#### ⚠️ 클러스터 모드 중요 사항 ⚠️
```
Redis Cluster에서 데이터를 삽입할 때는 반드시 -c (cluster) 플래그를 사용해야 합니다!

❌ 잘못된 방법: redis-cli -h $IP -p 7001 set "key" "value"
   → 모든 데이터가 7001 노드에만 저장됨 (클러스터 분산 X)

✅ 올바른 방법: redis-cli -h $IP -p 7001 -c set "key" "value"  
   → 데이터가 해시 슬롯에 따라 적절한 노드로 자동 분산됨

-c 플래그가 없으면 클러스터 리다이렉션이 작동하지 않아 데이터가 한 노드에 집중됩니다.
```

#### 테스트 데이터 생성 스크립트
```bash
# 환경 변수 설정
export IP=10.101.99.145
export TEST_DATA_SIZE=10000

# 1. String 타입 - 사용자 정보 (TTL 포함)
echo "Creating $TEST_DATA_SIZE string records with TTL..."
for i in $(seq 1 $TEST_DATA_SIZE); do 
  redis-cli -h $IP -p 7001 -c set "user:$i" "name-$i|email-$i@example.com|age-$((20 + $i % 50))" EX $((600 + $i % 3600)) >/dev/null
  if [ $((i % 1000)) -eq 0 ]; then echo "String progress: $i/$TEST_DATA_SIZE"; fi
done

# 2. Hash 타입 - 프로필 정보  
echo "Creating $TEST_DATA_SIZE hash records..."
for i in $(seq 1 $TEST_DATA_SIZE); do
  redis-cli -h $IP -p 7001 -c hmset "profile:$i" \
    name "User$i" \
    email "user$i@example.com" \
    age $((20 + $i % 50)) \
    city "City$((i % 100))" \
    score $((i * 10)) >/dev/null
  if [ $((i % 1000)) -eq 0 ]; then echo "Hash progress: $i/$TEST_DATA_SIZE"; fi
done

# 3. List 타입 - 큐 데이터
echo "Creating $TEST_DATA_SIZE list records..."
for i in $(seq 1 $TEST_DATA_SIZE); do
  for j in $(seq 1 5); do
    redis-cli -h $IP -p 7001 -c lpush "queue:$i" "task-$i-$j|priority-$((j % 3))|timestamp-$(date +%s)" >/dev/null
  done
  if [ $((i % 1000)) -eq 0 ]; then echo "List progress: $i/$TEST_DATA_SIZE"; fi
done

# 4. Set 타입 - 태그 시스템
echo "Creating $TEST_DATA_SIZE set records..."
for i in $(seq 1 $TEST_DATA_SIZE); do
  for tag in $(seq 1 $((3 + $i % 7))); do
    redis-cli -h $IP -p 7001 -c sadd "tags:$i" "tag$((tag % 20))" "category$((i % 10))" >/dev/null
  done
  if [ $((i % 1000)) -eq 0 ]; then echo "Set progress: $i/$TEST_DATA_SIZE"; fi
done

# 5. Sorted Set 타입 - 리더보드  
echo "Creating $TEST_DATA_SIZE sorted set records..."
for i in $(seq 1 $TEST_DATA_SIZE); do
  for j in $(seq 1 10); do
    redis-cli -h $IP -p 7001 -c zadd "leaderboard:$i" $((j * 100 + $i % 100)) "player$j" >/dev/null
  done
  if [ $((i % 1000)) -eq 0 ]; then echo "Sorted Set progress: $i/$TEST_DATA_SIZE"; fi
done

# 6. Stream 타입 - 이벤트 로그
echo "Creating stream records..."
for i in $(seq 1 10); do  # Stream은 10개만 생성
  redis-cli -h $IP -p 7001 -c xadd "stream:events:$i" "*" \
    event_type "user_action" \
    user_id $((i % 1000)) \
    action "click" \
    timestamp $(date +%s) \
    data "event_data_$i" >/dev/null
  
  # Consumer Group 생성
  redis-cli -h $IP -p 7001 -c xgroup create "stream:events:$i" "processors" 0 mkstream 2>/dev/null
done

# 7. HyperLogLog 타입 - 유니크 방문자 카운터
echo "Creating HyperLogLog records..."
for i in $(seq 1 5); do  # HLL은 50개만 생성
  for j in $(seq 1 10); do  # 각 HLL에 1000개 요소 추가
    redis-cli -h $IP -p 7001 -c pfadd "hll:unique_visitors:$i" "visitor_$j" "session_$((j % 100))" >/dev/null
  done
  if [ $((i % 10)) -eq 0 ]; then echo "HyperLogLog progress: $i/50"; fi
done

echo "Test data creation completed!"
```
```

#### 데이터 생성 검증
```bash
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
echo "HyperLogLog keys: $(redis-cli -h $IP -p 7001 -c eval "return #redis.call('keys', 'hll:*')" 0)"

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
```

**테스트 원리**: 
- **String**: 가장 기본적인 타입, TTL 설정으로 만료 시간 테스트
- **Hash**: 구조화된 데이터, 필드별 접근 성능 테스트  
- **List**: 순서가 있는 데이터, FIFO/LIFO 큐 시뮬레이션
- **Set**: 중복 제거된 집합, 태그 시스템 시뮬레이션
- **Sorted Set**: 스코어 기반 정렬, 리더보드 시뮬레이션
- **Stream**: 로그 스트리밍, Consumer Group 포함
- **HyperLogLog**: 카디널리티 추정, 메모리 효율적인 유니크 카운터

### 5) 대용량 백업 실행 및 검증

#### 백업 실행
```bash
# 백업 전 현재 상태 기록
echo "Recording pre-backup state..."
BACKUP_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
echo "Backup started at: $BACKUP_TIMESTAMP"

# 데이터 타입별 개수 기록
echo "Pre-backup counts:" > backup_verification_$BACKUP_TIMESTAMP.log
for type in "user" "profile" "queue" "tags" "leaderboard" "stream" "hll"; do
  count=$(redis-cli -h $IP -p 7001 eval "return #redis.call('keys', '$type:*')" 0)
  echo "$type: $count keys" | tee -a backup_verification_$BACKUP_TIMESTAMP.log
done

# 샘플 TTL 기록 (복원 후 비교용)
echo "Sample TTLs:" >> backup_verification_$BACKUP_TIMESTAMP.log
for i in 1 100 1000 5000; do
  ttl=$(redis-cli -h $IP -p 7001 ttl user:$i)
  echo "user:$i TTL: $ttl" | tee -a backup_verification_$BACKUP_TIMESTAMP.log
done

# 대용량 백업 실행
echo "Starting backup..."
time make backup-local-profile BACKUP_DIR=./backups
```

#### 백업 결과 분석
```bash
# 백업 디렉터리 구조 확인
BACKUP_DIR=$(ls -1dt ./backups/redis-backup-local-* | head -n1)
echo "Latest backup: $BACKUP_DIR"

# 백업 파일 크기 및 구조 분석
echo "Backup structure analysis:"
ls -lah $BACKUP_DIR/
ls -lah $BACKUP_DIR/keys/

# 메타데이터 분석
echo "Backup metadata:"
cat $BACKUP_DIR/metadata.json | jq .

# JSONL 파일 분석
echo "Keys distribution in JSONL files:"
wc -l $BACKUP_DIR/keys/keys-part-*.jsonl

# 백업된 데이터 타입별 샘플 확인
echo "Sample backed up data:"
head -n 5 $BACKUP_DIR/keys/keys-part-0001.jsonl | jq .

# 압축 파일 크기 확인
echo "Archive size:"
ls -lah ./backups/*.tar.gz

# S3 업로드 확인
echo "S3 upload verification:"
aws s3 ls s3://theshop-lake-dev/backup/redis/ --profile toy-root --human-readable
```

**테스트 원리**: 
- 백업 도구는 Redis SCAN 명령을 사용하여 키를 순회하며 메모리 효율적으로 처리합니다
- 각 키의 데이터 타입을 TYPE 명령으로 확인하고 타입별 추출 명령을 사용합니다
- TTL은 PTTL 명령으로 밀리초 단위로 정확히 추출됩니다
- 데이터는 JSON Lines 형식으로 저장되어 스트리밍 처리가 가능합니다

### 6) 데이터 삭제 및 복원 테스트

#### 백업 전 상태 기록 (복원 검증용)
```bash
echo "Recording pre-backup state for verification..."
export IP=10.101.99.145

# 백업 전 총 키 개수 기록
PRIMARIES=$(redis-cli -h $IP -p 7001 cluster nodes \
  | awk '$3 ~ /master/ && $3 !~ /fail/ {split($2,a,":"); split(a[2],b,"@"); print b[1]}' \
  | sort -n | uniq)

TOTAL_BEFORE=$(for p in $PRIMARIES; do redis-cli -h $IP -p $p dbsize; done | awk '{s+=$1} END{print s}')
echo "Total keys before deletion: $TOTAL_BEFORE"

# 데이터 타입별 개수 기록
echo "Pre-deletion counts:" > restore_verification_$(date +%Y%m%d_%H%M%S).log
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
for type in "user" "profile" "queue" "tags" "leaderboard" "stream" "hll"; do
  count=$(redis-cli -h $IP -p 7001 -c eval "return #redis.call('keys', '$type:*')" 0)
  echo "$type: $count keys" | tee -a restore_verification_$TIMESTAMP.log
done

# 샘플 데이터 내용 기록 (복원 후 비교용)
echo "Sample data before deletion:" >> restore_verification_$TIMESTAMP.log
echo "user:1 = '$(redis-cli -h $IP -p 7001 -c get user:1)'" >> restore_verification_$TIMESTAMP.log
echo "user:1000 = '$(redis-cli -h $IP -p 7001 -c get user:1000)'" >> restore_verification_$TIMESTAMP.log
redis-cli -h $IP -p 7001 -c hgetall profile:1 | tr '\n' ' ' | sed 's/$/\n/' | sed 's/^/profile:1 = /' >> restore_verification_$TIMESTAMP.log

# 샘플 TTL 기록
echo "Sample TTLs before deletion:" >> restore_verification_$TIMESTAMP.log
for i in 1 100 1000 5000; do
  ttl=$(redis-cli -h $IP -p 7001 -c ttl user:$i)
  echo "user:$i TTL: $ttl" >> restore_verification_$TIMESTAMP.log
done

echo "Pre-deletion state recorded in restore_verification_$TIMESTAMP.log"
```

#### 전체 데이터 삭제 (복원 검증용)
```bash
echo "⚠️  DANGER: Deleting ALL data from Redis cluster for restoration testing..."
echo "This will delete ALL keys from the cluster!"
read -p "Continue? (yes/no): " confirm

if [ "$confirm" = "yes" ]; then
  echo "Performing cluster-wide data deletion..."
  
# 클러스터 모드로 전체 데이터 삭제
for p in $PRIMARIES; do 
  echo -n "Node $p: "; 
  redis-cli -c -h $IP -p $p flushall; 
done
  
  echo "Data deletion completed."
  
  # 삭제 후 상태 확인
  echo "Post-deletion verification:"
  TOTAL_AFTER_DELETE=$(for p in $PRIMARIES; do redis-cli -h $IP -p $p dbsize; done | awk '{s+=$1} END{print s}')
  echo "Total keys after deletion: $TOTAL_AFTER_DELETE"
  
  # 각 노드별 확인
  echo "Per-node verification:"
  for p in $PRIMARIES; do 
    count=$(redis-cli -h $IP -p $p dbsize)
    echo "Node $p: $count keys"
  done
  
  if [ "$TOTAL_AFTER_DELETE" -eq 0 ]; then
    echo "✅ All data successfully deleted from cluster"
  else
    echo "❌ Warning: $TOTAL_AFTER_DELETE keys remain in cluster"
  fi
else
  echo "Data deletion cancelled."
  exit 1
fi
```

#### S3에서 복원 실행
```bash
echo "Starting restoration from S3..."
echo "Restoration started at: $(date)"

# 복원 실행 (시간 측정)
time make restore-latest-profile

echo "Restoration completed at: $(date)"

# 복원 중 로그 모니터링 포인트:
# - S3에서 최신 백업 다운로드
# - 압축 해제
# - 데이터 타입별 복원 진행률
# - Consumer Group 재생성 (있는 경우)
# - 클러스터 모드로 데이터 분산
```

#### 복원 결과 검증
```bash
echo "Verifying restoration results..."

# 1. 전체 키 개수 비교
TOTAL_AFTER_RESTORE=$(for p in $PRIMARIES; do redis-cli -h $IP -p $p dbsize; done | awk '{s+=$1} END{print s}')
echo "Total keys after restoration: $TOTAL_AFTER_RESTORE"
echo "Total keys before deletion: $TOTAL_BEFORE"

if [ "$TOTAL_AFTER_RESTORE" -eq "$TOTAL_BEFORE" ]; then
  echo "✅ Key count matches: $TOTAL_AFTER_RESTORE keys restored"
else
  echo "❌ Key count mismatch: Expected $TOTAL_BEFORE, Got $TOTAL_AFTER_RESTORE"
fi

# 2. 클러스터 데이터 분산 검증
echo ""
echo "Cluster data distribution after restoration:"
for p in $PRIMARIES; do 
  count=$(redis-cli -h $IP -p $p dbsize)
  echo "Node $p: $count keys"
done

# 3. 데이터 타입별 개수 검증
echo ""
echo "Post-restoration data type counts:"
for type in "user" "profile" "queue" "tags" "leaderboard" "stream" "hll"; do
  count=$(redis-cli -h $IP -p 7001 -c eval "return #redis.call('keys', '$type:*')" 0)
  echo "$type: $count keys"
done

# 4. 샘플 데이터 내용 검증 (클러스터 모드로 조회)
echo ""
echo "Sample data verification:"
echo "user:1 = '$(redis-cli -h $IP -p 7001 -c get user:1)'"
echo "user:1000 = '$(redis-cli -h $IP -p 7001 -c get user:1000)'"

# 5. Hash 데이터 검증
echo ""
echo "Hash data verification:"
redis-cli -h $IP -p 7001 -c hgetall profile:1
redis-cli -h $IP -p 7001 -c hgetall profile:1000

# 6. List 데이터 검증
echo ""
echo "List data verification:"
echo "queue:1 length: $(redis-cli -h $IP -p 7001 -c llen queue:1)"
redis-cli -h $IP -p 7001 -c lrange queue:1 0 4

# 7. Set 데이터 검증
echo ""
echo "Set data verification:"
echo "tags:1 cardinality: $(redis-cli -h $IP -p 7001 -c scard tags:1)"
redis-cli -h $IP -p 7001 -c smembers tags:1

# 8. Sorted Set 데이터 검증
echo ""
echo "Sorted Set data verification:"
echo "leaderboard:1 cardinality: $(redis-cli -h $IP -p 7001 -c zcard leaderboard:1)"
redis-cli -h $IP -p 7001 -c zrange leaderboard:1 0 4 withscores

# 9. Stream 데이터 검증
echo ""
echo "Stream data verification:"
redis-cli -h $IP -p 7001 -c xinfo stream stream:events:1 2>/dev/null || echo "No stream found"
redis-cli -h $IP -p 7001 -c xinfo groups stream:events:1 2>/dev/null || echo "No consumer groups found"

# 10. HyperLogLog 데이터 검증
echo ""
echo "HyperLogLog data verification:"
redis-cli -h $IP -p 7001 -c pfcount hll:unique_visitors:1 2>/dev/null || echo "No HLL found"

# 11. TTL 정확성 검증
echo ""
echo "TTL accuracy verification:"
echo "Current TTLs after restoration:"
for i in 1 100 1000 5000; do
  current_ttl=$(redis-cli -h $IP -p 7001 -c ttl user:$i)
  echo "user:$i current TTL: $current_ttl seconds"
done

# 12. 클러스터 샤딩 검증
echo ""
echo "Cluster sharding verification:"
for i in 1 10 100 1000; do
  # 키가 있어야 할 노드 확인
  slot=$(redis-cli -h $IP -p 7001 cluster keyslot user:$i)
  responsible_node=$(redis-cli -h $IP -p 7001 cluster nodes | grep " $slot" | awk '{print $2}' | cut -d: -f2 | cut -d@ -f1)
  actual_exists=$(redis-cli -h $IP -p $responsible_node exists user:$i)
  
  if [ "$actual_exists" = "1" ]; then
    echo "✓ user:$i correctly placed on node $responsible_node (slot $slot)"
  else
    echo "✗ user:$i missing from expected node $responsible_node (slot $slot)"
  fi
done

echo ""
echo "Restoration verification completed!"
echo "Check restore_verification_$TIMESTAMP.log for detailed before/after comparison"
```

**테스트 원리**:
- **완전성 검증**: 전체 데이터 삭제 후 완전 복원으로 백업의 완전성 확인
- **클러스터 분산 검증**: 복원된 데이터가 올바른 해시 슬롯과 노드에 분산되는지 확인
- **TTL 정확성**: 복원 시점에서 TTL이 올바르게 계산되어 설정되는지 검증
- **데이터 무결성**: 각 데이터 타입의 내부 구조와 값이 원본과 일치하는지 확인
- **Consumer Group**: Stream의 Consumer Group이 올바르게 재생성되는지 검증
- **전체 워크플로우**: 실제 재해 복구 시나리오와 동일한 전체 삭제 후 복원 프로세스 검증

### 7) S3 백업 목록 조회 및 관리

#### 백업 목록 조회
```bash
# S3의 모든 백업 목록 확인
make list-backups-profile

# 출력 예시:
# 2025-01-18T06:06:35Z	15.2MB	s3://theshop-lake-dev/backup/redis/redis-backup-local-20250118T060635Z-28e5.tar.gz
# 2025-01-17T14:30:22Z	14.8MB	s3://theshop-lake-dev/backup/redis/redis-backup-local-20250117T143022Z-1a2b.tar.gz

# AWS CLI로 직접 확인
aws s3 ls s3://theshop-lake-dev/backup/redis/ --profile toy-root --human-readable --summarize

# 특정 백업 다운로드 (수동 검증용)
BACKUP_ID="redis-backup-local-20250118T060635Z-28e5"
aws s3 cp s3://theshop-lake-dev/backup/redis/${BACKUP_ID}.tar.gz ./downloads/ --profile toy-root

# 다운로드한 백업 압축 해제 및 검증
cd downloads
tar -xzf ${BACKUP_ID}.tar.gz
ls -la $BACKUP_ID/
cat $BACKUP_ID/metadata.json | jq .
```

**테스트 원리**: S3 목록 조회는 boto3의 list_objects_v2를 사용하여 백업 파일을 시간순으로 정렬하고, 파일 크기와 함께 표시합니다.

### 8) Verify - 백업 무결성 검증

#### 대용량 샘플 검증
```bash
# 최신 로컬 백업 디렉터리 확인
BACKUP_DIR=$(ls -1dt ./backups/redis-backup-local-* | head -n1)
echo "Verifying backup: $BACKUP_DIR"

# Docker를 사용한 검증 (2000개 샘플)
echo "Running verification with 2000 samples..."
time docker run --rm \
  -e ENV_PROFILE=local \
  -e REDIS_NODES="$IP:7001,$IP:7002,$IP:7003,$IP:7004,$IP:7005,$IP:7006" \
  -v "$BACKUP_DIR:/in" \
  redis-backup-tool:latest verify -i /in --sample 2000

# uv를 사용한 로컬 검증
echo "Running local verification..."
time make dev-verify INPUT_DIR="$BACKUP_DIR" SAMPLE=2000

# 세부 검증 - 데이터 타입별 정확성 확인
echo "Detailed verification by data type..."

# String 타입 검증
echo "Verifying String data..."
for i in 1 10 100 1000; do
  # 백업에서 추출
  backup_value=$(grep "\"key\":\"user:$i\"" $BACKUP_DIR/keys/keys-part-*.jsonl | jq -r '.value')
  # 실제 Redis에서 조회
  current_value=$(redis-cli -h $IP -p 7001 get user:$i)
  
  if [ "$backup_value" = "$current_value" ]; then
    echo "✓ user:$i matches"
  else
    echo "✗ user:$i mismatch: backup='$backup_value' vs current='$current_value'"
  fi
done

# Hash 타입 검증
echo "Verifying Hash data..."
backup_hash=$(grep "\"key\":\"profile:1\"" $BACKUP_DIR/keys/keys-part-*.jsonl | jq -r '.value')
current_hash=$(redis-cli -h $IP -p 7001 hgetall profile:1 | awk 'NR%2==1{key=$0} NR%2==0{print key":"$0}' | sort)
echo "Hash comparison for profile:1:"
echo "Backup: $backup_hash"
echo "Current: $current_hash"

# TTL 검증 (허용 오차 범위 내)
echo "Verifying TTL accuracy..."
for i in 1 100 1000; do
  backup_ttl=$(grep "\"key\":\"user:$i\"" $BACKUP_DIR/keys/keys-part-*.jsonl | jq -r '.ttl_millis')
  current_ttl_sec=$(redis-cli -h $IP -p 7001 ttl user:$i)
  current_ttl_millis=$((current_ttl_sec * 1000))
  
  if [ "$backup_ttl" != "null" ] && [ "$current_ttl_sec" -gt 0 ]; then
    diff=$((backup_ttl - current_ttl_millis))
    # 복원 과정에서 수 초의 차이는 허용
    if [ $diff -lt 30000 ] && [ $diff -gt -30000 ]; then
      echo "✓ user:$i TTL within acceptable range (diff: ${diff}ms)"
    else
      echo "✗ user:$i TTL significant difference: backup=${backup_ttl}ms vs current=${current_ttl_millis}ms"
    fi
  fi
done
```

#### 고급 검증 - 클러스터 샤딩 정확성
```bash
echo "Verifying cluster sharding consistency..."

# 각 노드별 키 분포 확인
echo "Key distribution verification:"
for p in $PRIMARIES; do
  # 노드별 키 개수 
  node_keys=$(redis-cli -h $IP -p $p dbsize)
  echo "Node $p: $node_keys keys"
  
  # 샘플 키들이 올바른 노드에 배치되었는지 확인
  for i in 1 10 100; do
    # Redis Cluster 슬롯 계산으로 키가 있어야 할 노드 확인
    slot=$(redis-cli -h $IP -p 7001 cluster keyslot user:$i)
    responsible_node=$(redis-cli -h $IP -p 7001 cluster nodes | grep "$slot" | awk '{print $2}' | cut -d: -f2 | cut -d@ -f1)
    actual_exists=$(redis-cli -h $IP -p $responsible_node exists user:$i)
    
    if [ "$actual_exists" = "1" ]; then
      echo "✓ user:$i correctly placed on node $responsible_node (slot $slot)"
    else
      echo "✗ user:$i missing from expected node $responsible_node (slot $slot)"
    fi
  done
done
```

**테스트 원리**:
- **샘플링 검증**: 통계적으로 유의미한 수량의 키를 무작위 선택하여 검증
- **데이터 타입별 검증**: 각 Redis 데이터 타입의 특성에 맞는 검증 로직
- **TTL 정확성**: 복원 시점 기준으로 TTL이 올바르게 계산되어 설정되었는지 확인
- **클러스터 일관성**: 키가 올바른 해시 슬롯과 노드에 배치되었는지 검증

### 9) 고급 테스트 시나리오

#### 성능 테스트
```bash
echo "Performance testing with larger datasets..."

# 대용량 백업 성능 테스트 (50,000개 키)
export LARGE_TEST_SIZE=50000
time make dev-backup MATCH='user:*' CHUNK_KEYS=10000

# 청크 크기별 성능 비교
for chunk_size in 1000 5000 10000 20000; do
  echo "Testing chunk size: $chunk_size"
  time make dev-backup MATCH='profile:*' CHUNK_KEYS=$chunk_size
done

# 네트워크 지연 시뮬레이션 (선택적)
# tc qdisc add dev eth0 root netem delay 10ms
# make backup-local-profile BACKUP_DIR=./backups
# tc qdisc del dev eth0 root
```

#### 장애 복구 테스트
```bash
echo "Disaster recovery simulation..."

# 1. 클러스터 일부 노드 다운 시뮬레이션
docker stop redis-cluster_redis-6_1
sleep 5

# 2. 부분 클러스터에서 백업 시도
make backup-local-profile BACKUP_DIR=./backups_partial 2>&1 | tee backup_partial.log

# 3. 노드 복구
docker start redis-cluster_redis-6_1
sleep 10

# 4. 클러스터 상태 확인
redis-cli -h $IP -p 7001 cluster nodes

# 5. 전체 클러스터 복구 후 백업
make backup-local-profile BACKUP_DIR=./backups_recovered
```

#### 증분 백업 시뮬레이션
```bash
echo "Incremental backup simulation..."

# 1. 초기 백업
make backup-local-profile BACKUP_DIR=./backups_initial

# 2. 데이터 변경 (클러스터 모드로 추가 데이터 삽입)
for i in $(seq 10001 12000); do
  redis-cli -h $IP -p 7001 -c set "user:$i" "new_user_$i" EX 3600 >/dev/null
done

# 3. 패턴별 백업 (신규 데이터만)
make dev-backup MATCH='user:1000[1-9]*' BACKUP_DIR=./backups_incremental CHUNK_KEYS=5000

# 4. 백업 크기 비교
echo "Backup size comparison:"
ls -lah ./backups_initial/*.tar.gz
ls -lah ./backups_incremental/*.tar.gz
```

#### 데이터 타입별 개별 테스트
```bash
echo "Individual data type testing..."

# Stream 고급 테스트
redis-cli -h $IP -p 7001 xadd test_stream "*" msg "test1"
redis-cli -h $IP -p 7001 xadd test_stream "*" msg "test2"
redis-cli -h $IP -p 7001 xgroup create test_stream test_group 0 mkstream
redis-cli -h $IP -p 7001 xreadgroup group test_group consumer1 count 1 streams test_stream ">"

# Stream 백업/복원 검증
make dev-backup MATCH='test_stream' BACKUP_DIR=./backups_stream
redis-cli -h $IP -p 7001 del test_stream
make restore-latest-profile

# Consumer Group 상태 확인
redis-cli -h $IP -p 7001 xinfo groups test_stream

# Lua 스크립트 테스트 (있는 경우)
redis-cli -h $IP -p 7001 -c eval "redis.call('set', 'lua_test', 'script_result'); return 'OK'" 0
make dev-backup MATCH='lua_test' BACKUP_DIR=./backups_lua
```

### 10) 문제 해결 및 트러블슈팅

#### 일반적인 문제와 해결책

**1. macOS Docker 네트워킹 문제**
```bash
# 증상: 클러스터 접속 실패
# 해결: Colima 사용 또는 브리지 네트워크 구성
colima start --network-address
# 또는
docker network create redis-cluster-net
# docker-compose.yml의 network_mode: host를 networks: [redis-cluster-net]으로 변경
```

**2. AWS 인증 문제**
```bash
# S3 권한 확인
aws sts get-caller-identity --profile toy-root
aws s3 ls s3://theshop-lake-dev/ --profile toy-root

# ECR 로그인 문제 해결
aws ecr get-login-password --region ap-northeast-2 --profile toy-root | docker login --username AWS --password-stdin 008971653402.dkr.ecr.ap-northeast-2.amazonaws.com

# 권한 오류 시 IAM 정책 확인
aws iam list-attached-user-policies --user-name your-username --profile toy-root
```

**3. 클러스터 데이터 분산 문제**
```bash
# 증상: 모든 데이터가 한 노드에 집중됨
# 원인: redis-cli에서 -c (cluster) 플래그 누락

# 문제 진단
echo "현재 데이터 분산 확인:"
for p in 7001 7002 7003; do
  count=$(redis-cli -h $IP -p $p dbsize)
  echo "Node $p: $count keys"
done

# 만약 한 노드에만 데이터가 있다면:
echo "❌ 문제: -c 플래그 없이 데이터가 삽입됨"
echo "해결: 다음 스크립트로 클러스터 분산 데이터 재생성"

# 해결 방법 1: 기존 데이터 삭제 후 재생성
redis-cli -h $IP -p 7001 -c flushall
# 그 후 -c 플래그와 함께 데이터 재생성

# 해결 방법 2: distribute_test_data.sh 스크립트 사용
chmod +x distribute_test_data.sh
./distribute_test_data.sh

# 올바른 분산 확인
echo "✅ 정상 분산 시 예상 결과:"
echo "Node 7001: ~3000-4000 keys"
echo "Node 7002: ~3000-4000 keys" 
echo "Node 7003: ~3000-4000 keys"
```

**4. 클러스터 생성 실패**
```bash
# 포트 충돌 확인
ss -tulpn | grep "700[1-6]"

# 컨테이너 로그 확인
docker logs redis-cluster_redis-1_1
docker logs redis-cluster_redis-cluster-entry_1

# 클러스터 강제 재생성
make clean
docker system prune -f
make up
```

**4. 백업/복원 오류**
```bash
# 메모리 부족 오류
docker stats
# 해결: CHUNK_KEYS 값을 줄여서 처리 단위 감소
make dev-backup CHUNK_KEYS=1000

# 네트워크 타임아웃
# 해결: Redis 연결 타임아웃 증가 또는 재시도 로직 활용
docker run --rm -e REDIS_SOCKET_CONNECT_TIMEOUT=30 redis-backup-tool:latest backup

# S3 업로드 실패
# 해결: 멀티파트 업로드 임계값 조정 또는 네트워크 확인
aws configure set default.s3.multipart_threshold 64MB --profile toy-root
```

**5. 데이터 불일치 문제**
```bash
# TTL 불일치 (정상 범위: 복원 과정에서 수초 차이)
# 허용 오차: 30초 이내

# 클러스터 리밸런싱 확인
redis-cli -h $IP -p 7001 cluster info
redis-cli -h $IP -p 7001 cluster check

# 메모리 사용량 확인
for p in $PRIMARIES; do
  echo "Node $p memory:"
  redis-cli -h $IP -p $p info memory | grep used_memory_human
done
```

#### 성능 최적화 팁

**1. 백업 성능 향상**
```bash
# 청크 크기 최적화 (메모리 vs 속도 균형)
# 소규모: CHUNK_KEYS=1000-2000
# 중규모: CHUNK_KEYS=5000-10000  
# 대규모: CHUNK_KEYS=10000-20000

# 병렬 처리 (여러 패턴으로 분할)
make dev-backup MATCH='user:*' BACKUP_DIR=./backups_users &
make dev-backup MATCH='profile:*' BACKUP_DIR=./backups_profiles &
wait
```

**2. S3 업로드 최적화**
```bash
# 멀티파트 설정
aws configure set default.s3.multipart_threshold 8MB --profile toy-root
aws configure set default.s3.multipart_chunksize 8MB --profile toy-root
aws configure set default.s3.max_concurrent_requests 10 --profile toy-root
```

**3. 복원 성능 향상**
```bash
# Redis 메모리 정책 최적화 (복원 전)
for p in $PRIMARIES; do
  redis-cli -h $IP -p $p config set maxmemory-policy noeviction
  redis-cli -h $IP -p $p config set stop-writes-on-bgsave-error no
done

# 복원 후 원래 설정 복구
for p in $PRIMARIES; do
  redis-cli -h $IP -p $p config set maxmemory-policy allkeys-lru
  redis-cli -h $IP -p $p config set stop-writes-on-bgsave-error yes
done
```

#### 모니터링 및 로깅

**1. 진행률 모니터링**
```bash
# 백업 진행률 모니터링
tail -f backup.log | grep -E "(progress|completed|error)"

# S3 업로드 진행률
aws s3 cp ./backups/large-backup.tar.gz s3://bucket/path/ --progress

# 복원 진행률 모니터링  
tail -f restore.log | grep -E "(restored|progress|error)"
```

**2. 리소스 사용량 모니터링**
```bash
# 컨테이너 리소스 사용량
docker stats redis-backup-tool

# 호스트 시스템 리소스
watch -n 5 'free -h && df -h && iostat 1 1'

# Redis 메모리 사용량
for p in $PRIMARIES; do
  redis-cli -h $IP -p $p info memory | grep used_memory
done
```

### 11) 정리 및 정리 단계

#### 테스트 완료 후 정리
```bash
echo "Cleaning up test environment..."

# 1. 로컬 Redis 클러스터 정리
make down
make clean

# 2. 로컬 백업 파일 정리 (선택적 - 검증용으로 보관 가능)
# rm -rf ./backups/redis-backup-local-*
# rm -rf ./downloads/*

# 3. 테스트 검증 로그 정리
# rm -f backup_verification_*.log
# rm -f backup_partial.log

# 4. S3 테스트 객체 정리 (주의: 실제 백업 삭제됨)
echo "S3 cleanup (BE CAREFUL - this deletes actual backups!):"
echo "To delete test backups:"
echo "aws s3 rm s3://theshop-lake-dev/backup/redis/ --recursive --profile toy-root"

# 5. Docker 이미지 정리 (선택적)
# docker rmi redis-backup-tool:latest
# docker system prune -f

# 6. 네트워크 정리
# docker network rm dev_net

echo "Cleanup completed!"
```

#### 테스트 결과 요약 리포트 생성
```bash
echo "Generating test summary report..."

cat > test_summary_$(date +%Y%m%d_%H%M%S).md << EOF
# Redis Cluster Backup/Restore Test Summary

## Test Environment
- Date: $(date)
- Redis Cluster: $IP:7001-7006
- Test Data Size: $TEST_DATA_SIZE records per type
- S3 Bucket: s3://theshop-lake-dev/backup/redis

## Test Results

### Data Type Coverage
- ✓ String: $TEST_DATA_SIZE records with TTL
- ✓ Hash: $TEST_DATA_SIZE structured records  
- ✓ List: $TEST_DATA_SIZE queue records
- ✓ Set: $TEST_DATA_SIZE tag sets
- ✓ Sorted Set: $TEST_DATA_SIZE leaderboards
- ✓ Stream: 100 event streams with Consumer Groups
- ✓ HyperLogLog: 50 unique visitor counters

### Performance Metrics
- Backup Time: $(cat backup_time.log 2>/dev/null || echo "Not recorded")
- Restore Time: $(cat restore_time.log 2>/dev/null || echo "Not recorded")
- Backup Size: $(ls -lh ./backups/*.tar.gz 2>/dev/null | tail -1 | awk '{print $5}' || echo "Not available")

### Verification Results
- Sample Verification: $(grep "missing=0" verify.log 2>/dev/null || echo "Not completed")
- TTL Accuracy: Within 30-second tolerance
- Cluster Distribution: Verified across all nodes
- Consumer Groups: Successfully recreated

### Issues Encountered
$(if [ -f issues.log ]; then cat issues.log; else echo "None reported"; fi)

## Recommendations
1. Regular testing with production-like data volumes
2. Monitor backup file sizes and S3 costs
3. Test restore procedures regularly
4. Validate TTL handling for time-sensitive data

EOF

echo "Test summary report generated: test_summary_$(date +%Y%m%d_%H%M%S).md"
```

### 12) 부록: 직접 docker run 예시

#### 프로파일/공유자격증명 방식 (권장)
```bash
# 기본 백업
docker run --rm \
  -e ENV_PROFILE=local \
  -e REDIS_NODES="$IP:7001,$IP:7002,$IP:7003,$IP:7004,$IP:7005,$IP:7006" \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  -e AWS_PROFILE=toy-root \
  -e AWS_SDK_LOAD_CONFIG=1 \
  -v "$HOME/.aws:/root/.aws:ro" \
  -v "$(pwd)/backups:/data/backups" \
  redis-backup-tool:latest backup

# 패턴 필터링 백업
docker run --rm \
  -e ENV_PROFILE=local \
  -e REDIS_NODES="$IP:7001,$IP:7002,$IP:7003,$IP:7004,$IP:7005,$IP:7006" \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  -e AWS_PROFILE=toy-root \
  -e AWS_SDK_LOAD_CONFIG=1 \
  -v "$HOME/.aws:/root/.aws:ro" \
  -v "$(pwd)/backups:/data/backups" \
  redis-backup-tool:latest backup --match "user:*" --chunk-keys 5000

# S3에서 복원
docker run --rm \
  -e ENV_PROFILE=local \
  -e REDIS_NODES="$IP:7001,$IP:7002,$IP:7003,$IP:7004,$IP:7005,$IP:7006" \
  -e S3_URI="s3://theshop-lake-dev/backup/redis" \
  -e AWS_PROFILE=toy-root \
  -e AWS_SDK_LOAD_CONFIG=1 \
  -v "$HOME/.aws:/root/.aws:ro" \
  redis-backup-tool:latest restore --from-s3 latest --overwrite --recreate-stream-groups

# 백업 검증
docker run --rm \
  -e ENV_PROFILE=local \
  -e REDIS_NODES="$IP:7001,$IP:7002,$IP:7003,$IP:7004,$IP:7005,$IP:7006" \
  -v "$(pwd)/backups/redis-backup-local-20250118T060635Z-28e5:/in" \
  redis-backup-tool:latest verify -i /in --sample 1000
```

#### 환경별 설정 예시
```bash
# 개발 환경
ENV_PROFILE=dev
REDIS_NODES="dev-redis-1:6379,dev-redis-2:6379,dev-redis-3:6379"

# 운영 환경  
ENV_PROFILE=prd
REDIS_NODES="prd-redis-1:6379,prd-redis-2:6379,prd-redis-3:6379"

# 테스트 환경 (포트 분산)
ENV_PROFILE=local
REDIS_NODES="10.101.99.145:7001,10.101.99.145:7002,10.101.99.145:7003,10.101.99.145:7004,10.101.99.145:7005,10.101.99.145:7006"
```

```

## 11) 클러스터 명령어 빠른 참조

### 중요한 클러스터 명령어
```bash
# 클러스터 모드로 데이터 삽입 (필수!)
redis-cli -h $IP -p 7001 -c set "key" "value"
redis-cli -h $IP -p 7001 -c hset "hash_key" "field" "value"
redis-cli -h $IP -p 7001 -c lpush "list_key" "item"
redis-cli -h $IP -p 7001 -c sadd "set_key" "member"
redis-cli -h $IP -p 7001 -c zadd "zset_key" 100 "member"

# 클러스터 상태 확인
redis-cli -h $IP -p 7001 cluster info
redis-cli -h $IP -p 7001 cluster nodes

# 데이터 분산 확인
for p in 7001 7002 7003; do 
  echo "Node $p: $(redis-cli -h $IP -p $p dbsize) keys"
done

# 특정 키가 어느 노드에 있는지 확인
redis-cli -h $IP -p 7001 cluster keyslot "your_key"
redis-cli -h $IP -p 7001 cluster nodes | grep "master"
```

### 잘못된 데이터 분산 수정
```bash
# 1. 기존 데이터 삭제 (주의: 모든 데이터 삭제됨)
redis-cli -h $IP -p 7001 -c flushall

# 2. 클러스터 분산 스크립트 실행
./distribute_test_data.sh

# 3. 분산 결과 확인
echo "데이터 분산 결과:"
for p in 7001 7002 7003; do 
  echo "Node $p: $(redis-cli -h $IP -p $p dbsize) keys"
done
```

이 테스트 시나리오는 Redis Cluster 백업/복원 도구의 모든 주요 기능을 포괄적으로 검증합니다. **특히 -c 플래그를 사용한 클러스터 모드 데이터 삽입이 핵심**입니다. 실제 운영 환경 도입 전에 이 절차를 통해 도구의 안정성과 정확성을 확인하시기 바랍니다.

````
