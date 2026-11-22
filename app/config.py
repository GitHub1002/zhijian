import os
from pathlib import Path

from dotenv import load_dotenv

# HuggingFace 镜像和下载开关：国内或内网环境默认走 hf-mirror，
# 避免首次加载嵌入模型时连接官方源超时。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
EMBED_DIM = int(os.getenv("EMBED_DIM", "512"))

QDRANT_PATH = os.getenv("QDRANT_PATH", str(BASE_DIR / "data" / "qdrant"))
DOCS_DIR = os.getenv("DOCS_DIR", str(BASE_DIR / "docs"))
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "knowledge.db"))
DAILY_ASK_LIMIT = int(os.getenv("DAILY_ASK_LIMIT", "10"))
SESSION_COOKIE = "kb_session"
SESSION_SECURE = os.getenv("SESSION_SECURE", "0").lower() in {"1", "true", "yes"}

COLLECTION_NAME = "knowledge_docs"
# 混合检索先各取 HYBRID_TOP_K 条，融合后再重排，最后只把 RERANK_TOP_K 段交给模型。
# MIN_VECTOR_SCORE 是余弦相似度门槛。改写次数限制在 0 或 1，默认不改写。
# RRF_K=60 是常用经验值；MIN_VECTOR_SCORE 针对 bge-small-zh 的相似度分布，
# 更换嵌入模型后需要重新标定。
# MIN_RERANK_SCORE 是重排模型 logits 门槛，只有模型重排生效时才使用；
# 词面兜底分不可跨批比较，仍走向量/BM25 门槛。
TOP_K = int(os.getenv("TOP_K", "5"))
HYBRID_TOP_K = int(os.getenv("HYBRID_TOP_K", "12"))
RRF_K = int(os.getenv("RRF_K", "60"))
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "3"))
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "1").lower() not in {"0", "false", "no"}
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
MIN_VECTOR_SCORE = float(os.getenv("MIN_VECTOR_SCORE", "0.35"))
MIN_RERANK_SCORE = float(os.getenv("MIN_RERANK_SCORE", "0.0"))
RAG_QUERY_REWRITE_LIMIT = max(0, min(int(os.getenv("RAG_QUERY_REWRITE_LIMIT", "0")), 1))

# 反馈编辑窗口与轨迹保留期。反馈只做轻量校验，不在这里调用大模型。
FEEDBACK_EDIT_WINDOW_HOURS = int(os.getenv("FEEDBACK_EDIT_WINDOW_HOURS", "168"))
FEEDBACK_DAILY_LIMIT = int(os.getenv("FEEDBACK_DAILY_LIMIT", "50"))
TRACE_RETENTION_DAYS = int(os.getenv("TRACE_RETENTION_DAYS", "180"))

# 相对路径统一按项目根目录解析，保证从任何工作目录启动都能找到 data/ 和 docs/。
QDRANT_PATH = (BASE_DIR / QDRANT_PATH) if not os.path.isabs(QDRANT_PATH) else Path(QDRANT_PATH)
DOCS_DIR = (BASE_DIR / DOCS_DIR) if not os.path.isabs(DOCS_DIR) else Path(DOCS_DIR)
DB_PATH = (BASE_DIR / DB_PATH) if not os.path.isabs(DB_PATH) else Path(DB_PATH)
QDRANT_PATH = str(QDRANT_PATH)
DOCS_DIR = str(DOCS_DIR)
DB_PATH = str(DB_PATH)
