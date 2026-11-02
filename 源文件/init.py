"""创建空白文章项目，不撰写正文、不改动固定模板。"""
from pathlib import Path
import argparse
import json
import sys

from template_runtime import TEMPLATE_ID, TemplateError, check_date, verify_template


def create_project(directory, title, author="石头开会", date=None):
    verify_template()
    directory = Path(directory).resolve()
    if not title.strip() or "\n" in title or "\r" in title:
        raise TemplateError("文档名称请填写一行非空文字。")
    if not author.strip():
        raise TemplateError("作者不能为空。")
    date = check_date(date)
    if directory.exists() and any(directory.iterdir()):
        raise TemplateError("初始化只写入新文件夹或空文件夹，已有项目请直接修改配置与 Markdown。")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "assets").mkdir(exist_ok=True)
    config = {"schema_version": 1, "template_id": TEMPLATE_ID,
              "source": "文章.md", "output": "文章.html",
              "metadata": {"title": title.strip(), "author": author.strip(), "publication_date": date or None},
              "reading": {"margin_percent": 10}}
    (directory / "document.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / "文章.md").write_text(f"# {title.strip()}\n\n<!-- 按已确认的大纲撰写正文；图片保存在 assets，并用相对路径引用。 -->\n", encoding="utf-8")
    return {"project": str(directory), "config": str(directory / "document.json"), "status": "created"}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="初始化固定模板的文章项目")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default="石头开会")
    parser.add_argument("--date", default=None, help="真实发表日期；未知则省略，不填导出当天")
    args = parser.parse_args()
    try:
        print(json.dumps(create_project(**vars(args)), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        sys.exit(1)
