from fastembed import TextEmbedding

from . import config

_model = None


def get_model():
    # 首次调用会下载模型并缓存到本地；进程内复用单例，避免每次请求重新加载。
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=config.EMBED_MODEL)
    return _model


# bge 对查询和正文使用不同前缀：入库用 embed，检索必须用 query_embed。
# 混用会降低召回。查询侧带检索指令，文档侧不要套同一条指令。
def embed_documents(texts):
    model = get_model()
    return [list(v) for v in model.embed(texts)]


def embed_query(text):
    model = get_model()
    return list(model.query_embed(text))[0]
