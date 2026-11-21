"""把上传文件转成可切分的文本。

在线新建和编辑仍只针对 Markdown 与 TXT。Word、PDF 按原文件保存，
预览和检索使用提取出的文字。扫描版 PDF 没有文字层时无法读取。
所有格式最终都会转成 Markdown 文本再交给 chunker；
原始字节只在上传和同步时落盘，作为源文件保留，预览和检索都使用提取文本。
"""
from io import BytesIO
from pathlib import Path

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".docx", ".pdf"}
EDITABLE_SUFFIXES = {".md", ".markdown", ".txt"}
MAX_BYTES = 20 * 1024 * 1024


class ExtractError(Exception):
    pass


def is_supported(suffix):
    return suffix.lower() in SUPPORTED_SUFFIXES


def is_editable(suffix):
    return suffix.lower() in EDITABLE_SUFFIXES


def iter_files(root):
    base = Path(root)
    return sorted(path for path in base.rglob("*") if path.is_file() and is_supported(path.suffix))


def extract_bytes(filename, raw):
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        shown = suffix or "该"
        raise ExtractError(f"不支持 {shown} 格式，请使用 Markdown、TXT、Word（.docx）或 PDF")
    if not raw:
        raise ExtractError("文件是空的")
    if len(raw) > MAX_BYTES:
        raise ExtractError("文件超过 20MB")
    if suffix in EDITABLE_SUFFIXES:
        text = _decode_text(raw)
    elif suffix == ".docx":
        text = _docx_to_markdown(raw)
    else:
        text = _pdf_to_markdown(raw)
    if not text.strip():
        raise ExtractError("没有提取到文字")
    return text


def _decode_text(raw):
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractError("文本编码无法识别，请另存为 UTF-8")


def _heading_level(style_name):
    for prefix in ("Heading ", "标题 "):
        if style_name.startswith(prefix):
            number = style_name[len(prefix):].strip()
            if number.isdigit() and 1 <= int(number) <= 6:
                return int(number)
    return 0


def _docx_to_markdown(raw):
    # 按 body 的原始子元素顺序遍历，段落和表格不会互相错位。
    # Word 标题依赖样式名（英文 Heading N / 中文“标题 N”），样式不规范时退化为普通段落。
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise ExtractError("服务器还不能读取 Word 文档") from exc
    try:
        document = Document(BytesIO(raw))
    except Exception as exc:
        raise ExtractError("无法读取这个 Word 文档") from exc

    lines = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            level = _heading_level(paragraph.style.name if paragraph.style is not None else "")
            lines.append(f"{'#' * level} {text}" if level else text)
        elif child.tag == qn("w:tbl"):
            rows = []
            for row in Table(child, document).rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                lines.extend(["", *rows, ""])
    return "\n".join(lines).strip()


def _pdf_to_markdown(raw):
    # 每页加“## 第 N 页”作为可引用标题；扫描版没有文字层时 extract_text 为空，
    # 最终报“没有提取到文字”，而不是静默入库空文档。
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractError("服务器还不能读取 PDF") from exc
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise ExtractError("PDF 已加密，无法读取")
        parts = []
        for index, page in enumerate(reader.pages, start=1):
            body = (page.extract_text() or "").strip()
            if body:
                parts.append(f"## 第 {index} 页\n\n{body}")
    except ExtractError:
        raise
    except Exception as exc:
        raise ExtractError("无法读取这个 PDF") from exc
    if not parts:
        raise ExtractError("没有提取到文字。扫描版 PDF 需要先做文字识别")
    return "\n\n".join(parts)
