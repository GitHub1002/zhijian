from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, FilterSelector, MatchAny, MatchValue, VectorParams

from . import config

_client = None


def get_client():
    # Qdrant local 模式在进程内读写 data/qdrant，同一时间只允许一个进程打开。
    # 因此 uvicorn 只能用单 worker；要多进程或多实例部署必须换成 Qdrant server。
    # 进程内的 _client 单例同时避免重复打开文件锁。
    global _client
    if _client is None:
        _client = QdrantClient(path=config.QDRANT_PATH)
    return _client


def close():
    """显式关闭本地 Qdrant 客户端，避免解释器退出时再触发析构异常。"""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def ensure_collection():
    client = get_client()
    if not client.collection_exists(config.COLLECTION_NAME):
        client.create_collection(
            collection_name=config.COLLECTION_NAME,
            vectors_config=VectorParams(size=config.EMBED_DIM, distance=Distance.COSINE),
        )


def upsert(points):
    client = get_client()
    ensure_collection()
    client.upsert(collection_name=config.COLLECTION_NAME, points=points)


def search(query_vector, top_k, libraries=None):
    # library 过滤在 Qdrant 侧完成，无权限的片段不会进入候选集。
    client = get_client()
    ensure_collection()
    query_filter = None
    if libraries:
        query_filter = Filter(must=[FieldCondition(key="library", match=MatchAny(any=list(libraries)))])
    res = client.query_points(
        collection_name=config.COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    )
    return res.points


def delete_source(source):
    client = get_client()
    ensure_collection()
    client.delete(
        collection_name=config.COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="source", match=MatchValue(value=source))])
        ),
    )


def replace_source(source, points):
    # 先按 source 删除再插入，保证文档删改后不残留旧片段。
    delete_source(source)
    if points:
        upsert(points)
