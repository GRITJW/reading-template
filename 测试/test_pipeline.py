from pathlib import Path
import base64
import json
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "源文件"))
from build import build_from_config, render
from init import create_project
from template_runtime import TemplateError, load_config, validate_html, verify_template
from bs4 import BeautifulSoup


class PipelineTests(unittest.TestCase):
    def setUp(self):
        test_root = (ROOT / ".test-tmp").resolve()
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        def cleanup():
            if not Path(self.temp.name).resolve().is_relative_to(test_root):
                raise RuntimeError("测试清理路径超出了预定目录。")
            self.temp.cleanup()
        self.addCleanup(cleanup)
        self.project = Path(self.temp.name) / "中文项目 with spaces"
        create_project(self.project, "关系与机制", date="2026-11-02")
        self.config = self.project / "document.json"
        self.md = self.project / "文章.md"
        self.output = self.project / "文章.html"
        self.svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="green"/></svg>'
        (self.project / "assets" / "关系 图.svg").write_bytes(self.svg)
        self.md.write_text('# 关系与机制\n\n## 原理\n\n保留这个段落。\n\n![关系图](assets/关系%20图.svg)\n\n*图 1 关系。*\n\n### 示例\n\n| 对象 | 作用 |\n| --- | --- |\n| A | B |\n\n```python\nx = 1\n```\n\n[来源](https://example.org/paper)\n', encoding="utf-8")

    def config_change(self, change):
        data = json.loads(self.config.read_text(encoding="utf-8"))
        change(data)
        self.config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_complete_embedded_image_and_repeatable_output(self):
        report = build_from_config(self.config)
        first = self.output.read_bytes()
        build_from_config(self.config)
        self.assertEqual(first, self.output.read_bytes())
        self.assertEqual(report["images"], 1)
        soup = BeautifulSoup(first, "html.parser")
        uri = soup.select_one("#article-body img")["src"]
        self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), self.svg)
        self.assertEqual(soup.select_one("pre code").get_text(), "x = 1\n")
        self.assertEqual(len(soup.select("table")), 1)
        self.assertEqual(soup.select_one('#article-body a[href^="http"]')["href"], "https://example.org/paper")
        self.assertIn("保留这个段落。", soup.select_one("#article-body").get_text())
        # 单独复制 HTML，没有 assets，仍通过同一成品校验。
        standalone = Path(self.temp.name) / "standalone.html"
        shutil.copy2(self.output, standalone)
        self.assertEqual(validate_html(standalone.read_text(encoding="utf-8"))["status"], "passed")

    def test_unknown_date_stays_unfilled(self):
        self.config_change(lambda data: data["metadata"].update(publication_date=None))
        build_from_config(self.config)
        self.assertIn("发表日期：未填写", self.output.read_text(encoding="utf-8"))

    def test_missing_image_keeps_previous_output(self):
        self.output.write_text("previous output", encoding="utf-8")
        self.md.write_text("# 关系与机制\n\n![缺图](assets/missing.png)", encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            build_from_config(self.config)
        self.assertEqual(self.output.read_text(), "previous output")

    def test_remote_image_fails_before_write(self):
        self.md.write_text("# 关系与机制\n\n![远程](https://example.org/a.png)", encoding="utf-8")
        with self.assertRaises(ValueError):
            build_from_config(self.config)
        self.assertFalse(self.output.exists())

    def test_nested_svg_resource_must_be_embedded(self):
        (self.project / "assets" / "关系 图.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="outside.png"/></svg>', encoding="utf-8")
        with self.assertRaises(TemplateError):
            build_from_config(self.config)

    def test_image_outside_assets_is_rejected(self):
        (self.project / "other.svg").write_bytes(self.svg)
        self.md.write_text("# 关系与机制\n\n![图](other.svg)", encoding="utf-8")
        with self.assertRaises(TemplateError):
            build_from_config(self.config)

    def test_metadata_and_title_must_match(self):
        self.config_change(lambda data: data["metadata"].update(title="另一篇文章"))
        with self.assertRaises(TemplateError):
            build_from_config(self.config)

    def test_config_rejects_unknown_style_field(self):
        self.config_change(lambda data: data.update(css="body {color:red}"))
        with self.assertRaises(TemplateError):
            load_config(self.config)

    def test_invalid_date_and_project_escape_are_rejected(self):
        self.config_change(lambda data: data["metadata"].update(publication_date="2026-02-30"))
        with self.assertRaises(TemplateError):
            load_config(self.config)
        self.config_change(lambda data: data["metadata"].update(publication_date=None))
        self.config_change(lambda data: data.update(output="../outside.html"))
        with self.assertRaises(TemplateError):
            load_config(self.config)

    def test_duplicate_anchor_and_extra_heading_fail(self):
        self.md.write_text('# 关系与机制\n\n<p id="article">冲突</p>', encoding="utf-8")
        with self.assertRaises(TemplateError):
            build_from_config(self.config)
        self.md.write_text('# 关系与机制\n\n# 第二个标题', encoding="utf-8")
        with self.assertRaises(ValueError):
            build_from_config(self.config)

    def test_template_drift_is_detected_without_changing_original(self):
        isolated = Path(self.temp.name) / "template"
        (isolated / "源文件").mkdir(parents=True)
        shutil.copy2(ROOT / "template-lock.json", isolated / "template-lock.json")
        for name in ("shell.html", "reader.css", "reader.js"):
            shutil.copy2(ROOT / "源文件" / name, isolated / "源文件" / name)
        verify_template(isolated)
        with (isolated / "源文件" / "reader.css").open("a", encoding="utf-8") as handle:
            handle.write("\nbody{font-size:99px}")
        with self.assertRaises(TemplateError):
            verify_template(isolated)

    def test_artifact_image_style_toc_and_word_count_tampering_fail(self):
        build_from_config(self.config)
        original = self.output.read_text(encoding="utf-8")
        edits = [
            lambda soup: soup.select_one("#article-body img").__setitem__("src", "assets/关系 图.svg"),
            lambda soup: soup.style.append("body{font-size:99px}"),
            lambda soup: soup.select_one(".toc-list a").__setitem__("href", "#not-existing"),
            lambda soup: setattr(soup.select_one("#word-count"), "string", "字数：1 字"),
        ]
        for edit in edits:
            with self.subTest(edit=edit):
                soup = BeautifulSoup(original, "html.parser")
                edit(soup)
                with self.assertRaises(TemplateError):
                    validate_html(str(soup))

    def test_legacy_call_and_inline_markdown_image_still_work(self):
        self.md.write_text('# 关系与机制\n\n前面 ![行内图](assets/关系%20图.svg) 后面。', encoding="utf-8")
        report = render(self.md, self.output, author="石头开会", date="2026-11-02")
        self.assertEqual(report["images"], 1)
        self.assertIn("后面。", BeautifulSoup(self.output.read_text(encoding="utf-8"), "html.parser").get_text())

    def test_source_and_existing_project_are_protected(self):
        before = self.md.read_bytes()
        with self.assertRaises(TemplateError):
            render(self.md, self.md)
        with self.assertRaises(TemplateError):
            create_project(self.project, "新标题")
        self.assertEqual(before, self.md.read_bytes())


if __name__ == "__main__":
    unittest.main()
