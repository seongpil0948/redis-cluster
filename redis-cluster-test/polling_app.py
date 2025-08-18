#!/usr/bin/env python3
"""
Redis 클러스터 무중단 업데이트 테스트를 위한 폴링 애플리케이션

여러 샤드/파티션에 분산된 키들을 1초마다 SET/GET하여
클러스터 가용성과 데이터 일관성을 모니터링합니다.
"""

import time
import json
import signal
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

# 공통 모듈 import
from redis_common import (
    Environment,
    create_redis_cluster,
    print_cluster_nodes,
    save_json_results,
    POLLING_KEY_PATTERNS,
)

# 환경 설정
env: Environment = "local"


@dataclass
class PollingResult:
    """폴링 테스트 결과"""

    timestamp: str
    cycle: int
    success_count: int
    error_count: int
    total_operations: int
    avg_response_time_ms: float
    errors: List[str]
    shard_results: Dict[str, Dict]


class RedisClusterPoller:
    """Redis 클러스터 폴링 테스트 관리자"""

    def __init__(self, test_key_count: int = 50):
        """
        Args:
            test_key_count: 테스트할 키의 개수 (여러 샤드에 분산됨)
        """
        self.test_key_count = test_key_count
        self.rc = None
        self.running = False
        self.cycle_count = 0
        self.total_stats = {
            "total_cycles": 0,
            "total_successes": 0,
            "total_errors": 0,
            "start_time": None,
            "errors_log": [],
        }

    def connect(self) -> bool:
        """Redis 클러스터에 연결"""
        try:
            print(f"🔗 Connecting to Redis cluster ({env} environment)...")
            self.rc = create_redis_cluster(
                env, health_check_interval=5, socket_connect_timeout=2, socket_timeout=2
            )
            self.rc.ping()

            print("✅ Connected successfully!")
            print_cluster_nodes(self.rc, "Available nodes")

            return True

        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False

    def generate_test_data(self, cycle: int) -> Dict[str, str]:
        """테스트용 키-값 데이터 생성 (여러 샤드에 분산)"""
        data = {}
        timestamp = datetime.now(timezone.utc).isoformat()

        for i in range(self.test_key_count):
            pattern = POLLING_KEY_PATTERNS[i % len(POLLING_KEY_PATTERNS)]
            key = pattern.format(
                user_id=f"u{i:04d}",
                session_id=f"s{i:04d}",
                cache_id=f"c{i:04d}",
                counter_id=f"cnt{i:04d}",
                config_id=f"cfg{i:04d}",
                log_id=f"log{i:04d}",
                metric_id=f"m{i:04d}",
                temp_id=f"tmp{i:04d}",
            )

            value = json.dumps(
                {
                    "cycle": cycle,
                    "timestamp": timestamp,
                    "index": i,
                    "test_data": f"polling_test_cycle_{cycle}_item_{i}",
                }
            )

            data[key] = value

        return data

    def run_polling_cycle(self, cycle: int) -> PollingResult:
        """단일 폴링 사이클 실행"""
        success_count = 0
        error_count = 0
        errors = []
        shard_results = {}
        response_times = []

        # 테스트 데이터 생성
        test_data = self.generate_test_data(cycle)

        print(f"\n🔄 Cycle #{cycle} - Testing {len(test_data)} keys across shards...")

        # SET 작업
        for key, value in test_data.items():
            try:
                op_start = time.time()
                self.rc.set(key, value, ex=300)  # 5분 TTL
                op_time = (time.time() - op_start) * 1000
                response_times.append(op_time)
                success_count += 1

                # 샤드별 통계 수집
                slot = self.rc.keyslot(key)
                node_info = f"slot_{slot}"
                if node_info not in shard_results:
                    shard_results[node_info] = {
                        "set_count": 0,
                        "get_count": 0,
                        "errors": 0,
                    }
                shard_results[node_info]["set_count"] += 1

            except Exception as e:
                error_count += 1
                error_msg = f"SET {key}: {str(e)}"
                errors.append(error_msg)
                print(f"  ⚠️  {error_msg}")

        # GET 작업 (검증)
        for key in test_data.keys():
            try:
                op_start = time.time()
                retrieved_value = self.rc.get(key)
                op_time = (time.time() - op_start) * 1000
                response_times.append(op_time)

                if retrieved_value:
                    success_count += 1
                    # 데이터 무결성 검증
                    try:
                        data = json.loads(retrieved_value)
                        if data.get("cycle") != cycle:
                            error_count += 1
                            errors.append(f"GET {key}: cycle mismatch")
                    except json.JSONDecodeError:
                        error_count += 1
                        errors.append(f"GET {key}: invalid JSON")
                else:
                    error_count += 1
                    errors.append(f"GET {key}: key not found")

                # 샤드별 통계 수집
                slot = self.rc.keyslot(key)
                node_info = f"slot_{slot}"
                if node_info in shard_results:
                    shard_results[node_info]["get_count"] += 1

            except Exception as e:
                error_count += 1
                error_msg = f"GET {key}: {str(e)}"
                errors.append(error_msg)
                print(f"  ⚠️  {error_msg}")

                # 샤드별 에러 통계
                try:
                    slot = self.rc.keyslot(key)
                    node_info = f"slot_{slot}"
                    if node_info in shard_results:
                        shard_results[node_info]["errors"] += 1
                except Exception:
                    pass

        # 결과 계산
        total_operations = len(test_data) * 2  # SET + GET
        avg_response_time = (
            sum(response_times) / len(response_times) if response_times else 0
        )

        result = PollingResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            cycle=cycle,
            success_count=success_count,
            error_count=error_count,
            total_operations=total_operations,
            avg_response_time_ms=round(avg_response_time, 2),
            errors=errors,
            shard_results=shard_results,
        )

        # 상태 출력
        success_rate = (
            (success_count / total_operations) * 100 if total_operations > 0 else 0
        )
        print(
            f"✅ Success: {success_count}/{total_operations} ({success_rate:.1f}%) | "
            f"⏱️  Avg: {avg_response_time:.1f}ms | "
            f"🎯 Shards: {len(shard_results)}"
        )

        if errors:
            print(f"❌ Errors: {error_count}")

        return result

    def save_results(self, results: List[PollingResult]):
        """결과를 JSON 파일로 저장"""
        output_data = {
            "test_info": {
                "environment": env,
                "test_key_count": self.test_key_count,
                "total_cycles": len(results),
                "start_time": self.total_stats["start_time"],
                "end_time": datetime.now(timezone.utc).isoformat(),
            },
            "summary": {
                "total_operations": sum(r.total_operations for r in results),
                "total_successes": sum(r.success_count for r in results),
                "total_errors": sum(r.error_count for r in results),
                "overall_success_rate": 0,
                "avg_response_time_ms": 0,
            },
            "cycles": [asdict(result) for result in results],
        }

        # 전체 통계 계산
        if output_data["summary"]["total_operations"] > 0:
            output_data["summary"]["overall_success_rate"] = round(
                (
                    output_data["summary"]["total_successes"]
                    / output_data["summary"]["total_operations"]
                )
                * 100,
                2,
            )

        if results:
            output_data["summary"]["avg_response_time_ms"] = round(
                sum(r.avg_response_time_ms for r in results) / len(results), 2
            )

        try:
            save_json_results(output_data, "polling_results")
        except Exception as e:
            print(f"❌ Failed to save results: {e}")

    def run(self, duration_seconds: Optional[int] = None):
        """폴링 테스트 실행"""
        if not self.connect():
            return

        self.running = True
        self.total_stats["start_time"] = datetime.now(timezone.utc).isoformat()
        results = []

        print("\n🚀 Starting Redis cluster polling test...")
        print(f"📊 Testing {self.test_key_count} keys per cycle")
        if duration_seconds:
            print(f"⏰ Duration: {duration_seconds} seconds")
        print("💡 Press Ctrl+C to stop gracefully\n")

        start_time = time.time()

        try:
            while self.running:
                self.cycle_count += 1

                try:
                    result = self.run_polling_cycle(self.cycle_count)
                    results.append(result)

                    # 전체 통계 업데이트
                    self.total_stats["total_cycles"] += 1
                    self.total_stats["total_successes"] += result.success_count
                    self.total_stats["total_errors"] += result.error_count

                except Exception as e:
                    print(f"❌ Cycle #{self.cycle_count} failed: {e}")
                    self.total_stats["total_errors"] += self.test_key_count * 2

                # 지속시간 체크
                if duration_seconds and (time.time() - start_time) >= duration_seconds:
                    print(f"\n⏰ Reached duration limit ({duration_seconds}s)")
                    break

                # 1초 대기
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n⏹️  Stopping gracefully...")

        finally:
            self.running = False

            # 최종 통계 출력
            print("\n📈 Final Statistics:")
            print(f"   Cycles completed: {self.total_stats['total_cycles']}")
            print(
                f"   Total operations: {self.total_stats['total_successes'] + self.total_stats['total_errors']}"
            )
            print(f"   Successful operations: {self.total_stats['total_successes']}")
            print(f"   Failed operations: {self.total_stats['total_errors']}")

            if (
                self.total_stats["total_successes"] + self.total_stats["total_errors"]
                > 0
            ):
                success_rate = (
                    self.total_stats["total_successes"]
                    / (
                        self.total_stats["total_successes"]
                        + self.total_stats["total_errors"]
                    )
                ) * 100
                print(f"   Overall success rate: {success_rate:.2f}%")

            # 결과 저장
            if results:
                self.save_results(results)


def main():
    """메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="Redis 클러스터 폴링 테스트")
    parser.add_argument(
        "--keys", type=int, default=50, help="테스트할 키 개수 (기본값: 50)"
    )
    parser.add_argument(
        "--duration", type=int, help="테스트 지속시간(초). 미지정시 무한 실행"
    )
    parser.add_argument(
        "--env",
        choices=["local", "dev", "prd"],
        default="local",
        help="환경 선택 (기본값: local)",
    )

    args = parser.parse_args()

    # 전역 환경 변수 설정
    global env
    env = args.env

    # 우아한 종료를 위한 시그널 핸들러
    poller = RedisClusterPoller(test_key_count=args.keys)

    def signal_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}, stopping...")
        poller.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 폴링 시작
    poller.run(duration_seconds=args.duration)


if __name__ == "__main__":
    main()
