"""把 Markdown 渲染成可以安全插入页面的 HTML。

模型回答和文档预览都会经过这里，所以除了 Markdown 扩展，还做一层白名单清洗：
丢弃 script/style/iframe/form，href 只允许 #、/、./、../ 开头或 http(s)/mailto: 前缀的链接，
style 只保留少量排版属性。

标题 id 由 toc 扩展的 slugify 生成；app/rag.py 生成来源 anchor 时使用的是同一个
函数，两边必须保持一致，否则“点击来源跳转”会失效。
"""
import re
import unicodedata
from html import escape
from html.parser import HTMLParser

import markdown


def slugify(value, separator="-"):
    # 与来源锚点共用：ASCII 转小写，保留中文，标点移除，空白转连字符。
    # 修改这里会让已保存回答里的 anchor 失效。
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[^\w\s-]", "", value)
    value = value.strip().lower()
    return re.sub(r"[-\s]+", separator, value)


EXTENSIONS = [
    "tables",
    "sane_lists",
    "attr_list",
    "def_list",
    "footnotes",
    "abbr",
    "admonition",
    "md_in_html",
    "toc",
    "pymdownx.tasklist",
    "pymdownx.superfences",
    "pymdownx.tilde",
    "pymdownx.mark",
    "pymdownx.caret",
    "pymdownx.details",
    "pymdownx.magiclink",
    "pymdownx.smartsymbols",
    "pymdownx.highlight",
    "pymdownx.inlinehilite",
]

EXTENSION_CONFIGS = {
    # toc 用这里指定的 slugify 生成标题 id；app/rag.py 的 anchor 也调用同一函数，
    # 两边不一致会导致“点击来源”定位失败。
    "toc": {"slugify": slugify},
    "pymdownx.tasklist": {"custom_checkbox": True},
    "pymdownx.highlight": {
        "noclasses": True,
        "pygments_style": "monokai",
        "guess_lang": False,
    },
}


def render(text):
    # 模型输出和文档预览都会经过这里，脚本和事件属性会被去掉。
    html = markdown.markdown(
        text or "",
        extensions=EXTENSIONS,
        extension_configs=EXTENSION_CONFIGS,
        output_format="html5",
    )
    return _sanitize(html)


_ALLOWED_TAGS = {
    "a", "p", "br", "ul", "ol", "li", "strong", "em", "code", "pre", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr", "th", "td",
    "hr", "del", "ins", "sup", "sub", "span", "div", "label", "details", "summary",
}
_SKIP_TAGS = {"script", "style", "iframe", "object", "embed", "form"}
_SAFE_CLASS = re.compile(r"^[\w:\- ]+$")
_SAFE_ID = re.compile(r"^[\w\-]+$")
_SAFE_STYLE_PROP = re.compile(
    r"(?i)^(color|background-color|background|font-weight|font-style|text-decoration)\s*:\s*[^;{}]+$"
)


def _safe_href(value):
    # 白名单：以 #、/、./、../ 开头，或以 http://、https://、mailto: 开头。
    # 注意以 / 开头的 //host/path 是协议相对外链，目前也会通过。
    # javascript:/data: 不在白名单内；下面的显式判断只是兜底，正常不会命中。
    value = (value or "").strip()
    lowered = value.lower()
    if lowered.startswith(("#", "/", "./", "../", "http://", "https://", "mailto:")):
        if lowered.startswith("javascript:") or lowered.startswith("data:"):
            return None
        return value
    return None


def _safe_style(value):
    # 样式只允许少量排版属性；出现 url()/expression()/javascript: 时整条丢弃。
    if re.search(r"(?i)url\s*\(|expression\s*\(|javascript:", value or ""):
        return None
    parts = [part.strip() for part in (value or "").split(";") if part.strip()]
    if not parts or any(not _SAFE_STYLE_PROP.match(part) for part in parts):
        return None
    return "; ".join(parts)


class _Sanitizer(HTMLParser):
    # 逐标签重建而不是用正则过滤：只输出白名单内的标签和属性，
    # 未知标签保留文本、丢弃标签，避免漏掉某种畸形写法。
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, close=False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, close=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            if self.skip:
                self.skip -= 1
            return
        if self.skip or tag not in _ALLOWED_TAGS:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(escape(data))

    def _start(self, tag, attrs, close):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            if not close:
                self.skip += 1
            return
        if tag == "input":
            rendered = _render_attrs(tag, attrs)
            if rendered:
                self.parts.append(f"<input{rendered}>")
            return
        if self.skip or tag not in _ALLOWED_TAGS:
            return
        rendered = _render_attrs(tag, attrs)
        if rendered is None:
            return
        if tag in {"br", "hr"} or (tag == "input" and close):
            self.parts.append(f"<{tag}{rendered}>")
            return
        self.parts.append(f"<{tag}{rendered}>")


def _render_attrs(tag, attrs):
    if tag == "input":
        values = {key.lower(): value for key, value in attrs}
        if values.get("type", "").lower() != "checkbox":
            return None
        checked = " checked" if values.get("checked") is not None else ""
        return f' type="checkbox" disabled{checked}'
    kept = []
    for key, value in attrs:
        key = key.lower()
        if key.startswith("on"):
            continue
        if key == "href" and tag == "a":
            href = _safe_href(value)
            if href:
                kept.append(f' href="{escape(href, quote=True)}"')
        elif key == "title" and tag == "a":
            kept.append(f' title="{escape(value or "", quote=True)}"')
        elif key in {"colspan", "rowspan"} and tag in {"td", "th"} and str(value).isdigit():
            kept.append(f' {key}="{int(value)}"')
        elif key == "class" and _SAFE_CLASS.match(value or ""):
            kept.append(f' class="{escape(value, quote=True)}"')
        elif key == "id" and _SAFE_ID.match(value or ""):
            kept.append(f' id="{escape(value, quote=True)}"')
        elif key == "style":
            style = _safe_style(value)
            if style:
                kept.append(f' style="{escape(style, quote=True)}"')
    return "".join(kept)


def _sanitize(html):
    parser = _Sanitizer()
    parser.feed(html or "")
    parser.close()
    return "".join(parser.parts)
