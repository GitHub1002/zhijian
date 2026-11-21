from app.ingest import indexable, library_for_source
from app.md_render import render


def test_sample_directories_enter_the_index_and_keep_their_libraries():
    assert indexable("股票知识/设计.md")
    assert indexable("游戏开发文档/方案.md")
    assert indexable("公司招聘/面试.md")
    assert indexable("AI知识/概念.md")
    assert indexable("测试/立项.md")
    assert indexable("测试目录/备份.md")
    assert indexable("测试上传目录/命名.md")
    assert indexable("hr/请假制度.md")
    assert indexable("common/公司简介.md")
    assert library_for_source("common/公司简介.md") == "common"
    assert library_for_source("AI知识/概念.md") == "ai"
    assert library_for_source("公司招聘/面试.md") == "hr"
    assert library_for_source("游戏开发文档/方案.md") == "dev"
    assert library_for_source("股票知识/设计.md") == "ops_business"


def test_rendered_markdown_drops_executable_html():
    html = render("你好\n\n<script>alert(1)</script>\n\n[点我](javascript:alert(1))")
    lowered = html.lower()
    assert "你好" in html
    assert "<script" not in lowered
    assert "javascript:" not in lowered
    assert "alert" not in lowered
