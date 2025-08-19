from __future__ import annotations

import os
import time
from dataclasses import dataclass

import json
from pathlib import Path

from redis import Redis
from redis.cluster import RedisCluster, ClusterNode


@dataclass
class ClusterConfig:
    env_profile: str
    nodes: list[tuple[str, int]]


def parse_nodes(nodes_str: str) -> list[tuple[str, int]]:
    nodes: list[tuple[str, int]] = []
    print(f"Parsing nodes from string: {nodes_str}")
    for item in nodes_str.split(","):
        host, port_s = item.strip().split(":", 1)
        nodes.append((host, int(port_s)))
    return nodes


def _load_nodes_from_config(env_profile: str) -> list[tuple[str, int]]:
    """../config.json 파일에서 노드 설정을 로드합니다."""
    config_path = Path(__file__).parent.parent / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found at {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    nodes_str_list = config["redis_nodes"].get(env_profile, {}).get("nodes", [])
    if not nodes_str_list:
        raise ValueError(
            f"Profile '{env_profile}' not found or has no nodes in {config_path}"
        )

    nodes = []
    for node_str in nodes_str_list:
        host, port_s = node_str.strip().split(":", 1)
        nodes.append((host, int(port_s)))
    return nodes


def build_cluster_config(
    env_profile: str | None, redis_nodes: str | None
) -> ClusterConfig:
    profile = env_profile or os.environ.get("ENV_PROFILE", "local")

    # If redis_nodes is provided as an argument or env var, it takes precedence.
    # Otherwise, load from the config file based on the profile.
    nodes_override = redis_nodes or os.environ.get("REDIS_NODES")
    if nodes_override:
        nodes = parse_nodes(nodes_override)
    else:
        nodes = _load_nodes_from_config(profile)
    print(f"Using Redis nodes: {nodes}")
    return ClusterConfig(env_profile=profile, nodes=nodes)


def make_cluster_client(cfg: ClusterConfig) -> RedisCluster:
    startup_nodes = [ClusterNode(host=h, port=p) for h, p in cfg.nodes]
    return RedisCluster(startup_nodes=startup_nodes, decode_responses=True)


def key_type(r: Redis, key: str) -> str:
    t = r.type(key)
    if isinstance(t, str):
        return t
    elif isinstance(t, bytes):
        return t.decode()
    else:
        return str(t)  # fallback for other types


def pttl_safe(r: Redis, key: str) -> int | None:
    ttl = r.pttl(key)
    if ttl is None:
        return None
    if isinstance(ttl, int):
        return ttl if ttl >= 0 else None
    try:
        # Handle bytes response
        if isinstance(ttl, bytes):
            v = int(ttl.decode())
        else:
            v = int(str(ttl))
        return v if v >= 0 else None
    except Exception:
        return None


def now_millis() -> int:
    return int(time.time() * 1000)
