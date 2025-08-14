from typing import Literal
from redis.cluster import RedisCluster
from redis.cluster import ClusterNode
from datetime import datetime
from redis.exceptions import RedisClusterException
import json

env: Literal[ "local","dev","prd"] = "local"

local_nodes = [ClusterNode("localhost", port) for port in range(7001, 7007)]
dev_nodes = [ClusterNode("10.101.91.145", port) for port in range(7001, 7007)] 
prd_nodes = [
    ClusterNode("10.101.99.20", 6400),
    ClusterNode("10.101.99.20", 6401),
    ClusterNode("10.101.99.21", 6400),
    ClusterNode("10.101.99.21", 6401),
    ClusterNode("10.101.99.22", 6400),
    ClusterNode("10.101.99.22", 6401),
]

get_cluster_nodes = lambda: local_nodes if env == "local" else dev_nodes if env == "dev" else prd_nodes

def get_cluster_key_counts(rc: RedisCluster):
    """
    Returns a dict with total key count across primaries and per-node counts.
    Tries DBSIZE first; falls back to INFO keyspace parsing.
    """
    try:
        sizes = rc.dbsize(target_nodes=RedisCluster.PRIMARIES)
        total = 0
        per_node = {}
        if isinstance(sizes, dict):
            for node, size in sizes.items():
                node_name = f"{getattr(node, 'host', node)}:{getattr(node, 'port', '')}".rstrip(":")
                per_node[node_name] = int(size)
                total += int(size)
        elif isinstance(sizes, (list, tuple)):
            total = sum(int(s) for s in sizes)
        else:
            total = int(sizes)
        return {"total": total, "per_node": per_node}
    except Exception:
        try:
            infos = rc.info("keyspace", target_nodes=RedisCluster.PRIMARIES)
            total = 0
            per_node = {}
            if isinstance(infos, dict):
                for node, info in infos.items():
                    node_name = f"{getattr(node, 'host', node)}:{getattr(node, 'port', '')}".rstrip(":")
                    db0 = info.get("db0") or {}
                    keys = int(db0.get("keys", 0))
                    per_node[node_name] = keys
                    total += keys
            else:
                db0 = infos.get("db0") or {}
                total = int(db0.get("keys", 0))
            return {"total": total, "per_node": per_node}
        except Exception:
            return {"total": None, "per_node": {}}

def main():
    """
    Connects to a local Redis cluster, performs basic tests,
    and saves the results to a JSON file.
    """    
    nodes = get_cluster_nodes()
    redis_data = {
        "connection_info": {
            "status": "pending",
            "nodes_tried": [f"{node.host}:{node.port}" for node in nodes]
        },
        "cluster_info": None,
        "cluster_nodes": None,
        "tests": {}
    }    
    rc = None
    try:
        # decode_responses=True to get strings back from Redis instead of bytes
        print("Connecting to Redis cluster...")
        rc = RedisCluster(nodes=nodes, decode_responses=True)

        print("Connected to Redis cluster.")
        print("Cluster nodes:")
        for node in rc.get_nodes():
            print(f" - {node.host}:{node.port}")
        rc.ping()
        redis_data["connection_info"]["status"] = "success"
        print("Successfully connected to the Redis cluster.")

        # Record key counts BEFORE running tests
        redis_data["key_counts"] = {"before": get_cluster_key_counts(rc)}

        # 1. Get cluster information
        redis_data["cluster_info"] = rc.cluster_info()
        redis_data["cluster_nodes"] = rc.cluster_nodes()
        print("Gathered cluster information.")

        # 2. Perform basic data tests
        # String
        print("Testing STRING operations...")
        rc.set("test:string", "hello from SP")
        str_val = rc.get("test:string")
        redis_data["tests"]["string"] = {"set": "test:string", "get": str_val}
        # rc.delete("test:string") # Will be deleted at the end

        # Hash
        print("Testing HASH operations...")
        rc.hset("test:hash", mapping={"field1": "value1", "field2": "value2"})
        hash_val = rc.hgetall("test:hash")
        redis_data["tests"]["hash"] = {"set": "test:hash", "hgetall": hash_val}
        # rc.delete("test:hash") # Will be deleted at the end

        # List
        print("Testing LIST operations...")
        rc.rpush("test:list", "item1", "item2", "item3")
        list_val = rc.lrange("test:list", 0, -1)
        redis_data["tests"]["list"] = {"rpush": "test:list", "lrange": list_val}
        # rc.delete("test:list") # Will be deleted at the end

        # Set
        print("Testing SET operations...")
        rc.sadd("test:set", "member1", "member2", "member1") # member1 is duplicate
        set_val = rc.smembers("test:set") # Returns a set
        redis_data["tests"]["set"] = {"sadd": "test:set", "smembers": list(set_val)} # convert set to list for JSON
        # rc.delete("test:set") # Will be deleted at the end

        # Multi-key (Non-atomic) operations
        print("Testing MULTI-KEY (non-atomic) operations...")
        multi_key_data = {
            "test:multi:key1": "value_mk1",
            "test:multi:key2": "value_mk2",
            "test:multi:key3": "value_mk3"
        }
        rc.mset_nonatomic(multi_key_data)
        mget_val = rc.mget_nonatomic("test:multi:key1", "test:multi:key2", "test:multi:key3")
        redis_data["tests"]["multi_key_nonatomic"] = {
            "mset_nonatomic": multi_key_data,
            "mget_nonatomic": mget_val
        }
        # Keys will be deleted at the end

        # Get all keys from cluster
        print("Getting all keys from the cluster...")
        # Use RedisCluster.ALL_NODES to query all primary nodes for keys
        all_keys = rc.keys(target_nodes=RedisCluster.ALL_NODES)
        redis_data["tests"]["all_keys_from_cluster"] = {"keys": all_keys}

        print("All tests completed successfully.")

    except RedisClusterException as e:
        error_message = f"Failed to connect to Redis cluster. Please ensure the cluster is running via 'make up'. Error: {e}"
        redis_data["connection_info"]["status"] = "error"
        redis_data["connection_info"]["error"] = error_message
        print(error_message)
    except Exception as e:
        error_message = f"An unexpected error occurred: {e}"
        redis_data["connection_info"]["status"] = "error"
        redis_data["connection_info"]["error"] = error_message
        print(error_message)
    finally:
        # Clean up all test keys
        print("Cleaning up test keys...")
        keys_to_delete = [
            "test:string",
            "test:hash",
            "test:list",
            "test:set",
            "test:multi:key1",
            "test:multi:key2",
            "test:multi:key3"
        ]
        if rc is not None:
            for key in keys_to_delete:
                try:
                    rc.delete(key)
                except Exception as e:
                    print(f"Could not delete key '{key}': {e}")
            print("Test keys cleaned up.")

            # Record key counts AFTER cleanup to assess retention
            try:
                redis_data.setdefault("key_counts", {})
                redis_data["key_counts"]["after"] = get_cluster_key_counts(rc)
            except Exception as e:
                print(f"Could not collect post-cleanup key counts: {e}")
        else:
            print("Skipping cleanup and post-cleanup key count (no active Redis connection).")

        # 3. Save all collected data to a JSON file with a timestamp
        try:
            timestamp = datetime.now().strftime("%m-%dT%H:%M")
            with open(f"cluster_info_{timestamp}.json", "w", encoding="utf-8") as f:
                json.dump(redis_data, f, indent=4, ensure_ascii=False)
            print(f"Results have been saved to cluster_info_{timestamp}.json")
        except Exception as e:
            print(f"Failed to write results to out.json. Error: {e}")

if __name__ == "__main__":
    main()
