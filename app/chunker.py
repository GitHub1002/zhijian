"""按 Markdown 标题切块，供向量库和全文索引共用。

遇到 # 到 ###### 就结束上一节。一节超过 MAX_CHUNK_CHARS 时按整行再切，
相邻块不重叠。块正文前会加上标题路径，回答时用它标出处。
"""
import re
from pathlib import Path

MAX_CHUNK_CHARS = 1200
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _split_by_len(body):
    # 只在超长时按整行切；单行本身超过上限时仍整体保留，
    # 避免把表格行或长句切成难以阅读的碎片。
    if len(body) <= MAX_CHUNK_CHARS:
        return [body]
    parts = []
    cur = []
    cur_len = 0
    for line in body.splitlines():
        if cur_len + len(line) > MAX_CHUNK_CHARS and cur:
            parts.append("\n".join(cur))
            cur = []
            cur_len = 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        parts.append("\n".join(cur))
    return parts


def split_markdown(text, source):
    lines = text.splitlines()
    chunks = []
    heading_stack = []
    buffer = []

    def emit(buf):
        if not buf:
            return
        heading_path = " > ".join(h[1] for h in heading_stack)
        title = heading_stack[-1][1] if heading_stack else Path(source).stem
        body = "\n".join(buf).strip()
        if not body:
            return
        # 前缀会进入正文，被嵌入和 BM25 一起索引。不要在这里加时间戳之类
        # 每次都会变的内容，否则同一篇文档每次重建都会得到不同向量。
        for piece in _split_by_len(body):
            chunks.append(
                {
                    "text": f"[{heading_path}]\n{piece}" if heading_path else piece,
                    "title": title,
                    "heading": heading_path,
                    "source": source,
                }
            )

    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            emit(buffer)
            buffer = []
            level = len(m.group(1))
            # 维护从一级到当前级的标题路径：遇到同级或更高级标题时先弹栈，
            # 因此每个块只归属一个明确的标题路径。
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, m.group(2).strip()))
        else:
            buffer.append(line)
    emit(buffer)
    return chunks
