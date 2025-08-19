# Redis Backup/Restore TEST Report
- 환경: local
- 노드: 10.101.99.145 (7001 ~ 7006)

### 테스트 데이터 생성(Optional)
```bash
bash scripts/gen-test-data.sh
```
### 현재 데이터 분포 확인
```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
bash scripts/check-current-data.sh > current-data_$TIMESTAMP.log
```

### 백업
```bash
time make backup-local BACKUP_DIR=./backups

aws s3 ls s3://theshop-lake-dev/backup/redis/ --profile toy-root --human-readable
```

### 데이터 제거

```bash
make flush-local-cluster
bash scripts/check-current-data.sh
```

### 데이터 복구 
```bash
make restore-latest-local
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
bash scripts/check-current-data.sh > current-data_$TIMESTAMP.log
```
