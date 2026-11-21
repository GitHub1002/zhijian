import hashlib
from pathlib import Path

from qdrant_client.models import PointStruct

from . import chunker, config, db, documents, embedder, store

# 文档属于哪个库，只看相对 docs/ 的第一段目录名。对不上的目录归入运营库。
LIBRARY_DIRS = {
    "运维": "ops", "ops": "ops", "it": "ops",
    "人工智能": "ai", "ai": "ai", "AI知识": "ai",
    "开发": "dev", "dev": "dev", "游戏开发文档": "dev",
    "运营": "ops_business", "ops_business": "ops_business", "examples": "ops_business",
    "HR": "hr", "hr": "hr", "公司招聘": "hr",
    "common": "common",
}
# 不再按目录排除。docs 下受支持的文件都会入库，检索时按知识库权限过滤。
SKIP_INDEX_DIRS = set()


def library_for_source(source):
    first = Path(source).parts[0] if Path(source).parts else ""
    return LIBRARY_DIRS.get(first, "ops_business")


def indexable(source):
    first = Path(source).parts[0] if Path(source).parts else ""
    return first not in SKIP_INDEX_DIRS


def _build_points(source, content):
    library = library_for_source(source)
    chunks = chunker.split_markdown(content, source)
    points = []
    enriched = []
    if not chunks:
        return points, enriched
    texts = [c["text"] for c in chunks]
    vectors = embedder.embed_documents(texts)
    for c, vec in zip(chunks, vectors):
        cid = hashlib.md5(f"{source}::{c['heading']}::{c['text'][:200]}".encode()).hexdigest()
        c = {**c, "id": cid, "library": library}
        enriched.append(c)
        points.append(
            PointStruct(
                id=cid,
                vector=vec,
                payload={
                    "source": c["source"],
                    "title": c["title"],
                    "heading": c["heading"],
                    "text": c["text"],
                    "library": library,
                },
            )
        )
    return points, enriched


def run_ingest():
    doc_files = documents.iter_files(config.DOCS_DIR)
    all_chunks = []
    all_sources = set()
    for f in doc_files:
        rel = f.relative_to(config.DOCS_DIR).as_posix()
        if not indexable(rel):
            continue
        all_sources.add(rel)
        try:
            text = documents.extract_bytes(f.name, f.read_bytes())
        except documents.ExtractError:
            # 读不出来时保留已有索引，避免一次坏文件把原来的片段清掉。
            continue
        points, chunks = _build_points(rel, text)
        all_chunks.extend(chunks)
        store.replace_source(rel, points)
        db.replace_search_chunks(rel, chunks)

    with db._connect() as conn:
        stale = [row["source"] for row in conn.execute("SELECT DISTINCT source FROM search_chunks").fetchall() if row["source"] not in all_sources]
    for source in stale:
        db.delete_search_source(source)
        store.delete_source(source)
    return {"files": len(doc_files), "chunks": len(all_chunks)}


def ingest_one(source, content):
    if not indexable(source):
        delete_source(source)
        return 0
    points, chunks = _build_points(source, content)
    store.replace_source(source, points)
    db.replace_search_chunks(source, chunks)
    return len(points)


def delete_source(source):
    store.delete_source(source)
    db.delete_search_source(source)
