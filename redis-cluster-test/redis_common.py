"""
Redis 클러스터 공통 설정 및 유틸리티 함수

이 모듈은 main.py와 polling_app.py에서 공통으로 사용하는
노드 설정, 연결 함수, 유틸리티 함수들을 제공합니다.
"""

from typing import Literal, List, Optional
from redis.cluster import RedisCluster, ClusterNode
from redis.exceptions import RedisClusterException
import json

# 환경 타입 정의
Environment = Literal["local", "dev", "prd"]

# 환경별 노드 설정
CLUSTER_NODES = {
    "local": [ClusterNode("10.101.99.145", port) for port in range(7001, 7007)],
    "dev": [ClusterNode("10.101.91.145", port) for port in range(7001, 7007)],
    "prd": [
        ClusterNode("10.101.99.20", 6400),
        ClusterNode("10.101.99.20", 6401),
        ClusterNode("10.101.99.21", 6400),
        ClusterNode("10.101.99.21", 6401),
        ClusterNode("10.101.99.22", 6400),
        ClusterNode("10.101.99.22", 6401),
    ]
}

def get_cluster_nodes(env: Environment) -> List[ClusterNode]:
    """환경에 따른 클러스터 노드 목록 반환"""
    return CLUSTER_NODES[env]

def create_redis_cluster(env: Environment, **kwargs) -> RedisCluster:
    """
    Redis 클러스터 연결 생성
    
    Args:
        env: 환경 ('local', 'dev', 'prd')
        **kwargs: RedisCluster에 전달할 추가 매개변수
    
    Returns:
        RedisCluster: 연결된 Redis 클러스터 객체
    
    Raises:
        RedisClusterException: 연결 실패 시
    """
    nodes = get_cluster_nodes(env)
    
    # 기본 설정
    default_config = {
        "startup_nodes": nodes,
        "decode_responses": True,
        "health_check_interval": 30,
        "socket_connect_timeout": 5,
        "socket_timeout": 5
    }
    
    # 사용자 설정으로 덮어쓰기
    default_config.update(kwargs)
    
    return RedisCluster(**default_config)

def get_cluster_key_counts(rc: RedisCluster) -> int:
    """
    클러스터의 총 키 개수를 반환
    
    Args:
        rc: Redis 클러스터 객체
    
    Returns:
        int: 총 키 개수
    """
    try:
        sizes = rc.dbsize(target_nodes=RedisCluster.PRIMARIES)
        if isinstance(sizes, dict):
            return sum(int(size) for size in sizes.values())
        elif isinstance(sizes, (list, tuple)):
            return sum(int(s) for s in sizes)
        else:
            return int(sizes)
    except Exception:
        return 0

def get_cluster_info(rc: RedisCluster) -> dict:
    """
    클러스터 정보 수집
    
    Args:
        rc: Redis 클러스터 객체
    
    Returns:
        dict: 클러스터 정보와 노드 정보
    """
    return {
        "info": rc.cluster_info(),
        "nodes": rc.cluster_nodes()
    }

def print_cluster_nodes(rc: RedisCluster, title: str = "Cluster nodes") -> None:
    """
    클러스터 노드 목록을 예쁘게 출력
    
    Args:
        rc: Redis 클러스터 객체
        title: 출력 제목
    """
    print(f"📍 {title}:")
    for node in rc.get_nodes():
        print(f"   - {node.host}:{node.port}")

def test_connection(env: Environment, verbose: bool = True) -> Optional[RedisCluster]:
    """
    Redis 클러스터 연결 테스트
    
    Args:
        env: 환경
        verbose: 상세 출력 여부
    
    Returns:
        RedisCluster: 성공시 연결 객체, 실패시 None
    """
    try:
        if verbose:
            print(f"🔗 Connecting to Redis cluster ({env} environment)...")
        
        rc = create_redis_cluster(env)
        rc.ping()
        
        if verbose:
            print("✅ Connected successfully!")
            print_cluster_nodes(rc)
        
        return rc
        
    except RedisClusterException as e:
        if verbose:
            print(f"❌ Connection failed: {e}")
        return None
    except Exception as e:
        if verbose:
            print(f"❌ Unexpected error: {e}")
        return None

def cleanup_keys(rc: RedisCluster, keys: List[str], verbose: bool = True) -> int:
    """
    지정된 키들을 삭제
    
    Args:
        rc: Redis 클러스터 객체
        keys: 삭제할 키 목록
        verbose: 상세 출력 여부
    
    Returns:
        int: 삭제된 키 개수
    """
    if verbose:
        print("Cleaning up keys...")
    
    deleted_count = 0
    for key in keys:
        try:
            if rc.delete(key):
                deleted_count += 1
        except Exception as e:
            if verbose:
                print(f"  ⚠️  Failed to delete '{key}': {e}")
    
    if verbose:
        print(f"✅ Cleaned up {deleted_count}/{len(keys)} keys")
    
    return deleted_count

def save_json_results(data: dict, filename_prefix: str, verbose: bool = True) -> str:
    """
    결과를 JSON 파일로 저장
    
    Args:
        data: 저장할 데이터
        filename_prefix: 파일명 접두사
        verbose: 상세 출력 여부
    
    Returns:
        str: 생성된 파일명
    """
    from datetime import datetime
    
    timestamp = datetime.now().strftime("%m-%dT%H-%M")
    filename = f"{filename_prefix}_{timestamp}.json"
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        if verbose:
            print(f"💾 Results saved to {filename}")
        
        return filename
        
    except Exception as e:
        if verbose:
            print(f"❌ Failed to save results: {e}")
        raise

def format_nodes_list(env: Environment) -> List[str]:
    """
    환경에 따른 노드 목록을 문자열 리스트로 반환
    
    Args:
        env: 환경
    
    Returns:
        List[str]: "host:port" 형식의 노드 목록
    """
    nodes = get_cluster_nodes(env)
    return [f"{node.host}:{node.port}" for node in nodes]

# 상수 정의
DEFAULT_TEST_KEYS = [
    "test:string",
    "test:hash", 
    "test:list",
    "test:set",
    "test:multi:key1",
    "test:multi:key2", 
    "test:multi:key3"
]

# 폴링 테스트용 키 패턴
POLLING_KEY_PATTERNS = [
    "user:{user_id}:profile",
    "session:{session_id}:data", 
    "cache:{cache_id}:value",
    "counter:{counter_id}:count",
    "config:{config_id}:settings",
    "log:{log_id}:entry",
    "metric:{metric_id}:data",
    "temp:{temp_id}:storage"
]
