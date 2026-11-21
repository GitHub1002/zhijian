from fastembed import TextEmbedding

from . import config

_model = None


def get_model():
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=config.EMBED_MODEL)
    return _model


# bge 对查询和正文使用不同前缀：入库用 embed，检索必须用 query_embed。
def embed_documents(texts):
    model = get_model()
    return [list(v) for v in model.embed(texts)]


def embed_query(text):
    model = get_model()
    return list(model.query_embed(text))[0]
