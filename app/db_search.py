"""全文索引与 BM25 检索。

从 db.py 拆出；入库时由 replace_search_chunks 增量维护 FTS。
"""
import re

from . import db


def _connect():
    return db._connect()


def _fts_terms(value):
    """将中文拆成二元词，避免 SQLite unicode61 把整段中文当成一个词。"""
    terms = []
    for part in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", (value or "").lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            if len(part) == 1:
                terms.append(part)
            else:
                terms.extend(part[i:i + 2] for i in range(len(part) - 1))
        else:
            terms.append(part)
    return list(dict.fromkeys(terms))


def _fts_index_text(value):
    return " ".join(_fts_terms(value))


def _fts_query(value):
    terms = _fts_terms(value)
    return " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)


def _rebuild_fts_index(conn):
    """手动全量重建 FTS，用于索引版本升级或排查不一致。"""
    conn.execute("DELETE FROM search_chunks_fts")
    rows = conn.execute("SELECT chunk_id, source, title, heading, text, library FROM search_chunks").fetchall()
    conn.executemany(
        """INSERT INTO search_chunks_fts(chunk_id, source, title, heading, text, library)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (row["chunk_id"], _fts_index_text(row["source"]), _fts_index_text(row["title"]),
             _fts_index_text(row["heading"]), _fts_index_text(row["text"]), row["library"])
            for row in rows
        ],
    )


def rebuild_fts():
    """显式重建全文索引；正常入库由 replace_search_chunks 增量维护。"""
    with _connect() as conn:
        _rebuild_fts_index(conn)


def replace_search_chunks(source, chunks):
    with _connect() as conn:
        conn.execute(
            "DELETE FROM search_chunks_fts WHERE chunk_id IN (SELECT chunk_id FROM search_chunks WHERE source = ?)",
            (source,),
        )
        conn.execute("DELETE FROM search_chunks WHERE source = ?", (source,))
        for chunk in chunks:
            row = {
                "chunk_id": chunk["id"], "source": chunk["source"], "title": chunk.get("title", ""),
                "heading": chunk.get("heading", ""), "text": chunk.get("text", ""),
                "library": chunk.get("library", "ops_business"),
            }
            conn.execute(
                "INSERT OR REPLACE INTO search_chunks(chunk_id, source, title, heading, text, library) VALUES (:chunk_id, :source, :title, :heading, :text, :library)",
                row,
            )
            conn.execute(
                "INSERT INTO search_chunks_fts(chunk_id, source, title, heading, text, library) VALUES (?, ?, ?, ?, ?, ?)",
                (row["chunk_id"], _fts_index_text(row["source"]), _fts_index_text(row["title"]),
                 _fts_index_text(row["heading"]), _fts_index_text(row["text"]), row["library"]),
            )


def delete_search_source(source):
    with _connect() as conn:
        conn.execute(
            "DELETE FROM search_chunks_fts WHERE chunk_id IN (SELECT chunk_id FROM search_chunks WHERE source = ?)",
            (source,),
        )
        conn.execute("DELETE FROM search_chunks WHERE source = ?", (source,))


def search_bm25(query, libraries, limit=20):
    if not libraries:
        return []
    match = _fts_query(query)
    if not match:
        return []
    placeholders = ",".join("?" for _ in libraries)
    sql = f"""SELECT f.chunk_id, c.source, c.title, c.heading, c.text, c.library,
                      bm25(search_chunks_fts) AS bm25_score
               FROM search_chunks_fts AS f
               JOIN search_chunks AS c ON c.chunk_id = f.chunk_id
               WHERE search_chunks_fts MATCH ? AND c.library IN ({placeholders})
               ORDER BY bm25_score ASC LIMIT ?"""
    with _connect() as conn:
        # 先多取 max(limit*4, 40)，因为下面的首尾锚点过滤会丢掉一部分，最后再截到 limit。
        rows = conn.execute(sql, [match, *libraries, max(limit * 4, 40)]).fetchall()
    rows = [dict(row) for row in rows]
    # 中文 FTS 使用二元词。要求命中查询首/尾锚点，避免“完全不存在的词”
    # 仅因包含一个常见二元词而被当成有效证据。
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", query.lower())
    anchors = {run[:2] for run in cjk_runs if len(run) >= 2} | {run[-2:] for run in cjk_runs if len(run) >= 2}
    if anchors:
        rows = [row for row in rows if anchors.intersection(_fts_terms(row["text"]))]
    return rows[:limit]
