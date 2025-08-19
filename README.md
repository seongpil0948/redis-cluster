# Redis 클러스터 안정성 관리 도구

이 저장소는 Redis 클러스터의 구성 변경, 버전 업그레이드 등 주요 유지보수 작업을 안전하게 수행하기 위한 백업, 복원 및 테스트 도구를 제공합니다.

주요 목표는 작업 전/후 클러스터의 상태를 비교하고, 문제가 발생했을 때 신속하게 복구할 수 있는 명확한 절차를 제공하는 것입니다.

## 📂 프로젝트 구성

-   `redis-backup-tool/`: S3와 연동되는 논리적 백업 및 복원 도구입니다.
-   `redis-cluster-test/`: 클러스터의 상태 확인 및 부하 테스트를 위한 스크립트 모음입니다.
-   `config.json`: `local`, `dev`, `prd` 환경별 Redis 노드 주소를 중앙에서 관리하는 설정 파일입니다.

---

## 🚀 시작하기

### 1. 사전 요구사항

-   **Python 3.12 이상**: `uv`가 파이썬 프로젝트를 관리하기 위해 필요합니다. 시스템 `PATH`에 `python3.12` 또는 `python`이 등록되어 있어야 합니다.
-   **uv**: 파이썬 패키지 관리자입니다. `pip install uv` 또는 [공식 설치 가이드](https://github.com/astral-sh/uv)를 참고하세요.
-   **AWS CLI**: S3 연동을 위해 필요하며, `~/.aws/credentials`에 프로필이 설정되어 있어야 합니다.

### 2. 프로젝트 환경 설정

1.  **저장소 클론 및 의존성 설치**:

    ```bash
    git clone <repository_url>
    cd redis-cluster
    uv sync
    ```

2.  **노드 주소 설정**:

    루트 디렉토리의 `config.json` 파일을 열고, 각 환경(`local`, `dev`, `prd`)에 맞는 Redis 노드들의 IP 주소와 포트를 정확하게 수정합니다.

    ```json
    {
        "redis_nodes": {
            "local": { "nodes": ["10.101.99.145:7001", ...] },
            "dev": { "nodes": ["10.101.91.145:7001", ...] },
            "prd": { "nodes": ["10.101.99.20:6400", ...] }
        }
    }
    ```

3.  **S3 및 AWS 설정**:

    백업/복원에 필요한 S3 버킷 주소와 AWS 프로필을 `.env.local` 파일에 미리 설정해두면 편리합니다. (`.env.example` 참고)

    ```dotenv
    # .env.local
    S3_URI="s3://your-bucket-name/path/to/backups"
    AWS_PROFILE="your-aws-profile"
    ```

---

##  workflow 안전한 Redis 클러스터 유지보수 워크플로우

### 1단계: 작업 전 상태 확인 및 백업

#### A. 클러스터 상태 및 성능 테스트

대상 환경에 맞는 `make` 명령어로 클러스터의 기본 동작과 현재 성능을 측정합니다.

```bash
# Dev 환경 기본 테스트
make test-cluster-dev

# Dev 환경 부하 테스트 (60초)
make poll-cluster-dev
```

생성된 `.json` 결과 파일을 작업 후 상태와 비교하기 위해 보관합니다.

#### B. 데이터 백업

대상 환경에 맞는 `make` 명령어로 S3에 데이터를 백업합니다.

```bash
# Dev 환경 백업
make backup-dev
```

백업 완료 시 출력되는 `backup_id`를 반드시 기록해두세요.

### 2단계: Redis 클러스터 작업 수행

계획했던 유지보수 작업(예: 버전 업그레이드, 설정 변경 등)을 진행합니다.

### 3단계: 작업 후 상태 확인

1단계와 동일한 테스트를 다시 수행하여 작업 전과 동일한 결과를 얻는지, 성능 저하는 없는지 확인합니다.

### 4단계: 문제 발생 시 복구

문제가 발견되면 백업 데이터를 사용하여 클러스터를 이전 상태로 복원합니다.

#### A. 가장 최신 백업으로 복원

```bash
# Dev 환경을 가장 최신 백업으로 복원
make restore-latest-dev
```

#### B. 특정 ID의 백업으로 복원

`BACKUP_ID` 변수를 사용하여 특정 시점으로 복원합니다.

```bash
# Dev 환경을 특정 ID로 복원
make restore-id-dev BACKUP_ID="redis-backup-dev-20231027T..."
```

> **⚠️ 주의**: 복원 작업은 기본적으로 대상 클러스터의 키를 덮어씁니다 (`--overwrite`).

---

## 🛠️ 개발 및 코드 관리

코드 수정 후에는 항상 다음 명령어를 실행하여 코드 스타일을 통일하고 잠재적인 오류를 검사하세요.

1.  **코드 포맷팅**:

    ```bash
    uvx ruff format
    ```

2.  **코드 린팅**:

    ```bash
    uvx ruff check
    ```
