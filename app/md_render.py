import re
import unicodedata
from html import escape
from html.parser import HTMLParser

import markdown


def slugify(value, separator="-"):
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
    "toc": {"slugify": slugify},
    "pymdownx.tasklist": {"custom_checkbox": True},
    "pymdownx.highlight": {
        "noclasses": True,
        "pygments_style": "monokai",
        "guess_lang": False,
    },
}


def render(text):
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
    value = (value or "").strip()
    lowered = value.lower()
    if lowered.startswith(("#", "/", "./", "../", "http://", "https://", "mailto:")):
        if lowered.startswith("javascript:") or lowered.startswith("data:"):
            return None
        return value
    return None


def _safe_style(value):
    if re.search(r"(?i)url\s*\(|expression\s*\(|javascript:", value or ""):
        return None
    parts = [part.strip() for part in (value or "").split(";") if part.strip()]
    if not parts or any(not _SAFE_STYLE_PROP.match(part) for part in parts):
        return None
    return "; ".join(parts)


class _Sanitizer(HTMLParser):
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
