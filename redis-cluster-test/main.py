from datetime import datetime
from redis.cluster import RedisCluster
from redis.exceptions import RedisClusterException
from redis_common import (
    Environment,
    create_redis_cluster,
    get_cluster_key_counts,
    get_cluster_info,
    print_cluster_nodes,
    cleanup_keys,
    save_json_results,
    format_nodes_list,
    DEFAULT_TEST_KEYS,
)

import argparse


def run_data_tests(rc: RedisCluster) -> dict:
    """기본 데이터 타입 테스트를 실행합니다."""
    tests = {}

    # STRING 테스트
    print("Testing STRING operations...")
    rc.set("test:string", "hello from SP")
    tests["string"] = {
        "operation": "SET/GET",
        "key": "test:string",
        "value": rc.get("test:string"),
    }

    # HASH 테스트
    print("Testing HASH operations...")
    rc.hset("test:hash", mapping={"field1": "value1", "field2": "value2"})
    tests["hash"] = {
        "operation": "HSET/HGETALL",
        "key": "test:hash",
        "value": rc.hgetall("test:hash"),
    }

    # LIST 테스트
    print("Testing LIST operations...")
    rc.rpush("test:list", "item1", "item2", "item3")
    tests["list"] = {
        "operation": "RPUSH/LRANGE",
        "key": "test:list",
        "value": rc.lrange("test:list", 0, -1),
    }

    # SET 테스트
    print("Testing SET operations...")
    rc.sadd("test:set", "member1", "member2", "member1")  # member1 중복
    try:
        set_members = rc.smembers("test:set")
        # Handle different response types safely
        if hasattr(set_members, "__await__"):
            set_value = "awaitable_response"
        elif isinstance(set_members, set):
            set_value = sorted(list(set_members))
        else:
            # Try to convert safely with type ignore for dynamic types
            try:
                set_value = list(set_members)  # type: ignore
            except (TypeError, AttributeError):
                set_value = str(set_members)
    except Exception as e:
        set_value = f"error: {e}"

    tests["set"] = {
        "operation": "SADD/SMEMBERS",
        "key": "test:set",
        "value": set_value,
    }

    # 멀티키 테스트
    print("Testing MULTI-KEY operations...")
    multi_data = {
        "test:multi:key1": "value1",
        "test:multi:key2": "value2",
        "test:multi:key3": "value3",
    }
    rc.mset_nonatomic(multi_data)
    tests["multi_key"] = {
        "operation": "MSET/MGET (non-atomic)",
        "keys": list(multi_data.keys()),
        "values": rc.mget_nonatomic(*multi_data.keys()),
    }

    return tests


def main():
    """Redis 클러스터에 연결하여 테스트를 실행하고 결과를 저장합니다."""
    parser = argparse.ArgumentParser(description="Redis 클러스터 기본 테스트")
    parser.add_argument(
        "--env",
        choices=["local", "dev", "prd"],
        default="local",
        help="실행할 환경 (기본값: local)",
    )
    args = parser.parse_args()
    env: Environment = args.env

    result = {
        "timestamp": datetime.now().isoformat(),
        "connection": {"status": "pending", "nodes": format_nodes_list(env)},
        "cluster_info": {},
        "tests": {},
        "key_counts": {},
    }

    rc = None
    try:
        # 클러스터 연결
        print(f"🔗 Connecting to Redis cluster ({env} environment)...")
        rc = create_redis_cluster(env)
        rc.ping()

        print("✅ Connected successfully!")
        print_cluster_nodes(rc)

        result["connection"]["status"] = "success"

        # 테스트 전 키 개수 확인
        result["key_counts"]["before"] = get_cluster_key_counts(rc)
        print(f"📊 Keys before tests: {result['key_counts']['before']}")

        # 클러스터 정보 수집
        print("📋 Gathering cluster information...")
        result["cluster_info"] = get_cluster_info(rc)

        # 데이터 타입 테스트 실행
        print("🧪 Running data type tests...")
        result["tests"] = run_data_tests(rc)

        # 전체 키 목록 조회
        print("🔍 Getting all keys from cluster...")
        all_keys = rc.keys(target_nodes=RedisCluster.ALL_NODES)
        # Handle different response types for keys
        try:
            if hasattr(all_keys, "__len__"):
                key_count = len(all_keys)  # type: ignore
            else:
                key_count = 0
        except (TypeError, AttributeError):
            key_count = 0

        result["tests"]["all_keys"] = {
            "operation": "KEYS *",
            "count": key_count,
            "keys": all_keys,
        }

        print("✅ All tests completed successfully!")

    except RedisClusterException as e:
        error_msg = f"Redis cluster connection failed: {e}"
        result["connection"] = {"status": "error", "error": error_msg}
        print(f"❌ {error_msg}")

    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        result["connection"] = {"status": "error", "error": error_msg}
        print(f"❌ {error_msg}")

    finally:
        # 정리 작업
        if rc is not None:
            cleanup_keys(rc, DEFAULT_TEST_KEYS)

            # 테스트 후 키 개수 확인
            try:
                result["key_counts"]["after"] = get_cluster_key_counts(rc)
                print(f"📊 Keys after cleanup: {result['key_counts']['after']}")
            except Exception as e:
                print(f"⚠️  Could not get post-cleanup key count: {e}")
        else:
            print("⚠️  Skipping cleanup (no active connection)")

        # 결과 저장
        try:
            save_json_results(result, f"cluster-info-{env}")
        except Exception as e:
            print(f"❌ Failed to save results: {e}")


if __name__ == "__main__":
    main()
