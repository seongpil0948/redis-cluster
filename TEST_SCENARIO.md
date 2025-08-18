## TEST_SCENARIO: Redis Cluster + Backup/Restore Tool 검증 절차

이 문서는 로컬 Redis Cluster 구성, 백업/복원 도구의 S3 연동, 자격증명 전달(ENV/프로파일) 등 주요 흐름을 실제로 실행하며 점검할 수 있는 테스트 시나리오를 제공합니다.

### 공통: 현재 상태/키 개수 검증 스니펫
- 클러스터 헬스:
```
redis-cli -p 7001 cluster info | egrep 'cluster_state|cluster_slots_assigned|cluster_known_nodes'
```
- 프라이머리 노드 포트 목록 추출(복제 중복 방지):
```
PRIMARIES=$(redis-cli -p 7001 cluster nodes \
  | awk '$3 ~ /master/ && $3 !~ /fail/ {split($2,a,":"); split(a[2],b,"@"); print b[1]}' \
  | sort -n | uniq)
echo "$PRIMARIES"
```
- 노드별 키 개수 + 전체 합계:
```
for p in $PRIMARIES; do echo -n "$p: "; redis-cli -p $p dbsize; done
TOTAL=$(for p in $PRIMARIES; do redis-cli -p $p dbsize; done | awk '{s+=$1} END{print s}')
echo "TOTAL_KEYS=$TOTAL"
```
- 패턴별 샘플 키 확인:
```
redis-cli -p 7001 --scan --pattern 'user:*' | head -n 10
```
- 스트림/함수 확인(있을 경우):
```
redis-cli -p 7001 xinfo stream mystream
redis-cli -p 7001 function list | head -n 20
```

### 0) 사전 준비
- Docker / Docker Compose 설치 (Linux 권장)
- macOS 사용 시: Docker Desktop은 `network_mode: host` 미지원. 가능한 대안:
  - Colima + host networking, 또는
  - `docker-compose.yml`을 브리지 네트워크로 조정(추가 작업 필요)
- 외부 네트워크 `dev_net`이 필요함: `docker network create dev_net`
- S3 테스트 버킷과 권한 준비: 예) 버킷 `my-bucket`, 프리픽스 `redis-backups`
- AWS 자격증명 준비: 프로파일/공유자격증명(`~/.aws`) + `AWS_PROFILE`, `AWS_SDK_LOAD_CONFIG=1`

권장 환경 변수
```
export BUCKET=my-bucket
export PREFIX=redis-backups
export S3_URI="s3://$BUCKET/$PREFIX"
```

### 1) 로컬 Redis Cluster 기동
1. 설정 생성 및 기동
   - `make up`
2. 상태 확인
   - `make logs`로 클러스터 생성 로그에서 `--cluster create ... --cluster-yes` 성공 여부 확인
   - `docker ps`로 `redis-1`~`redis-6` 컨테이너가 정상인지 확인
3. 간단 점검 (옵션)
   - 호스트에 `redis-cli`가 있다면 `redis-cli -p 7001 ping` → `PONG`
   - 위 "공통 스니펫"을 사용해 `cluster_state:ok`, `cluster_slots_assigned:16384` 확인 및 현재 `TOTAL_KEYS` 확보

문제 발생 시
- macOS/host networking 이슈: Linux 환경에서 재시도 또는 네트워크 설정 변경 필요
- `dev_net` 없음: `docker network create dev_net`

### 2) Backup Tool 이미지 빌드
- `make build-backup-tool`
- 이미지는 `redis-backup-tool:latest`

### 3) AWS 인증 전달 검증 – 프로파일/공유자격증명 방식
1. 프로파일 지정 및 공유자격증명 마운트
```
export AWS_PROFILE=toy-root
make backup-local-profile S3_URI="$S3_URI" AWS_PROFILE=$AWS_PROFILE BACKUP_DIR=./backups
```
2. 기대 결과
- 콘솔 로그에 `Backup written:` 및 `Archive:` 경로가 출력되고, S3 URI가 설정된 경우 `Uploaded:` 로그가 출력됩니다.
- S3 버킷에 `s3://$BUCKET/$PREFIX/redis-backup-local-<timestamp>-<id>.tar.gz` 객체가 생성됩니다.
- 로컬 `./backups/redis-backup-local-*/` 폴더에 `metadata.json` 과 `keys/keys-part-*.jsonl` 파일이 생성되고, 동일한 루트에 `<backup_id>.tar.gz` 아카이브가 생성됩니다.

실패 트러블슈팅
- 실패 시 `~/.aws` 권한/파일, 프로파일 이름, `AWS_SDK_LOAD_CONFIG=1` 여부 확인

### 4) AWS 인증 전달 검증 – 프로파일/공유자격증명 방식
1. 프로파일 지정 및 공유자격증명 마운트
```
export AWS_PROFILE=toy-root
make backup-local-profile S3_URI="$S3_URI" AWS_PROFILE=$AWS_PROFILE BACKUP_DIR=./backups
```
2. 기대 결과
- 3)과 동일. 실패 시 `~/.aws` 권한/파일, 프로파일 이름, `AWS_SDK_LOAD_CONFIG=1` 여부 확인

### 5) 데이터 준비 및 백업/복원 시나리오
1. 테스트 데이터 적재
   - 호스트 `redis-cli` 사용 예:
```
for i in $(seq 1 1000); do redis-cli -p 7001 set "user:$i" "name-$i" EX 600 >/dev/null; done
redis-cli -p 7001 XADD mystream * field value
```
2. 백업 실행
```
make backup-local-profile S3_URI="$S3_URI" AWS_PROFILE=$AWS_PROFILE BACKUP_DIR=./backups
```
3. 강제 클린(복원 검증용): 일부/전체 키 삭제
```
redis-cli -p 7001 scan 0 match 'user:*' count 100000 | xargs -n1 redis-cli -p 7001 del >/dev/null
redis-cli -p 7001 del mystream
```
4. 복원 – 최신 백업에서 S3 다운로드 후 복원
```
make restore-latest-profile S3_URI="$S3_URI" AWS_PROFILE=$AWS_PROFILE
```
5. 검증
```
redis-cli -p 7001 get user:1        # 값 존재
redis-cli -p 7001 ttl user:1        # TTL(약 600초에서 경과 값) 존재
redis-cli -p 7001 xinfo stream mystream  # 스트림 존재
```
- 키 개수 비교: 백업 직후 기록해 둔 `TOTAL_KEYS`와 복원 후 `TOTAL_KEYS`가 근사치로 동일한지 확인(진행 중 TTL 만료로 약간 감소 가능)

### 6) 목록 조회(list)
```
make list-backups-profile S3_URI="$S3_URI" AWS_PROFILE=$AWS_PROFILE
```
- 최신순으로 `timestamp\t size\t s3/key/path.tar.gz` 형태의 라인이 출력됩니다.

### 7) verify 검증
1. 최신 백업 디렉터리 로컬 존재 확인 (3/5 단계의 BACKUP_DIR 내부)
2. 무작위 샘플 비교
```
DIR=$(ls -1dt ./backups/redis-backup-local-* | head -n1)
# Docker
docker run --rm \
  -e ENV_PROFILE=local \
  -v "$DIR:/in" \
  redis-backup-tool:latest verify -i /in --sample 200

# Or locally via uv
make dev-verify INPUT_DIR="$DIR" SAMPLE=200 AWS_PROFILE=$AWS_PROFILE
```
- 결과 예: `Verify sample=200 -> missing=0, ttl_mismatch=<허용오차 내>`

### 8) 동작 옵션별 추가 검증
- 키 필터: `--match 'user:*'` 로 특정 패턴만 백업
- 청크 크기: `--chunk-keys 10000` 조정 후 `keys/keys-part-*.jsonl` 분할 여부 확인
- 스트림 그룹 복원: `restore --recreate-stream-groups` 사용 시 그룹 메타데이터 생성 확인
- 덮어쓰기 제어: `restore` 기본은 스킵, `--overwrite` 시 기존 키를 덮어씀
- 노드 오버라이드: `-e REDIS_NODES="host1:port,host2:port,..."` 로 원격 클러스터에 수행

### 9) 자주 발생하는 문제와 해결
- macOS에서 클러스터 접속 실패: Docker host 네트워킹 미지원. Linux에서 실행하거나 네트워크를 브리지로 개편 필요
- `dev_net` 없음: `docker network create dev_net`
- S3 `AccessDenied/InvalidAccessKeyId`: 키/세션/리전 값 재확인, STS 만료 여부 확인
- `AWS_PROFILE` 사용 시 동작 안 함: `-v $HOME/.aws:/root/.aws:ro` 마운트와 `-e AWS_SDK_LOAD_CONFIG=1` 동시 설정 필요
- 클러스터 생성 실패: `redis-cluster-entry` 로그 확인 후 컨테이너 재시작 또는 포트 충돌 검사(7001~7006)

### 10) 정리
- 로컬 정리: `make down && make clean`
- S3 테스트 객체: 버킷에서 프리픽스 `$PREFIX` 하위 데이터를 정리

### 부록) 직접 docker run 예시
- 프로파일/공유자격증명 방식
```
docker run --rm \
  -e ENV_PROFILE=local \
  -e S3_URI="$S3_URI" \
  -e AWS_PROFILE=toy-root \
  -e AWS_SDK_LOAD_CONFIG=1 \
  -v "$HOME/.aws:/root/.aws:ro" \
  -v /tmp/redis-backups:/data/backups \
  redis-backup-tool:latest backup
```
