from __future__ import annotations

import os
import time
from dataclasses import dataclass

from redis import Redis
from redis.cluster import RedisCluster, ClusterNode


@dataclass
class ClusterConfig:
    env_profile: str
    nodes: list[tuple[str, int]]


def parse_nodes(nodes_str: str) -> list[tuple[str, int]]:
    nodes: list[tuple[str, int]] = []
    for item in nodes_str.split(","):
        host, port_s = item.strip().split(":", 1)
        nodes.append((host, int(port_s)))
    return nodes


def default_nodes_for_profile(env_profile: str) -> list[tuple[str, int]]:
    if env_profile == "local":
        return [("localhost", p) for p in range(7001, 7007)]
    raise ValueError(
        "Only ENV_PROFILE=local has built-in defaults. Provide REDIS_NODES for others."
    )


def build_cluster_config(
    env_profile: str | None, redis_nodes: str | None
) -> ClusterConfig:
    profile = env_profile or os.environ.get("ENV_PROFILE", "local")
    nodes = (
        parse_nodes(redis_nodes) if redis_nodes else default_nodes_for_profile(profile)
    )
    return ClusterConfig(env_profile=profile, nodes=nodes)


def make_cluster_client(cfg: ClusterConfig) -> RedisCluster:
    startup_nodes = [ClusterNode(host=h, port=p) for h, p in cfg.nodes]
    return RedisCluster(startup_nodes=startup_nodes, decode_responses=True)


def key_type(r: Redis, key: str) -> str:
    t = r.type(key)
    return t if isinstance(t, str) else t.decode()  # defensive


def pttl_safe(r: Redis, key: str) -> int | None:
    ttl = r.pttl(key)
    if ttl is None:
        return None
    if isinstance(ttl, int):
        return ttl if ttl >= 0 else None
    try:
        v = int(ttl)
        return v if v >= 0 else None
    except Exception:
        return None


def now_millis() -> int:
    return int(time.time() * 1000)
