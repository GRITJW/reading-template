"""把 Markdown 与本地图片装进一个可离线阅读的 HTML。

依赖：Markdown、beautifulsoup4。内容视为作者可信输入，不能用于渲染陌生人的 HTML。
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import markdown
from bs4 import BeautifulSoup

from template_runtime import (TemplateError, check_date, check_image_uri,
                              load_config, validate_html, verify_template)

HERE = Path(__file__).resolve().parent


def render(source: Path, output: Path, layout="clean", subtitle="", category="知识文档", meta="个人学习与知识整理", margin=None, author="石头开会", date="", omit_opening_line=None, expected_title=None, asset_root=None):
    files = verify_template()
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise TemplateError("输出文件不能覆盖原始 Markdown。")
    if output.suffix.lower() != ".html":
        raise TemplateError("输出文件必须使用 .html 扩展名。")
    date = check_date(date)
    # 旧的 layout 参数只映射初始留白比例，不再限制正文最大宽度。
    margin = {"clean": 10, "compact": 0, "book": 20}.get(layout, 10) if margin is None else margin
    if type(margin) is not int or not 0 <= margin <= 40:
        raise ValueError("左右各留白的比例必须在 0—40 之间。")
    raw = source.read_text(encoding="utf-8-sig")
    soup = BeautifulSoup(markdown.markdown(raw, extensions=["extra", "sane_lists"], output_format="html"), "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else source.stem
    if expected_title is not None and (h1 is None or title != expected_title):
        raise TemplateError("Markdown 的唯一一级标题必须与 document.json 中的 title 一致。")
    if h1:
        h1.decompose()
    if soup.find("h1"):
        raise ValueError("正文只能有一个一级标题；章节请使用二级标题。")
    if subtitle:
        for h2 in soup.find_all("h2"):
            if h2.get_text(strip=True) == subtitle:
                h2.decompose()
                break
    # 仅省略作者明确指定的开篇展示说明，不修改原始 Markdown 或正文后部。
    omitted_opening = []
    for node in list(soup.find_all(recursive=False)):
        if node.name in ("h2", "h3", "h4"):
            break
        if node.name == "p" and node.get_text(strip=True) in (omit_opening_line or []):
            omitted_opening.append(node.get_text(strip=True))
            node.decompose()
    # 原稿有手写目录时，用同一组标题自动生成目录，避免维护两份结构。
    for h2 in soup.find_all("h2"):
        if h2.get_text(strip=True) in ("目录", "本文目录"):
            following = h2.find_next_sibling()
            if following and following.name in ("ul", "ol"):
                following.decompose()
            h2.decompose()

    used_ids = set()
    for node in soup.find_all(id=True):
        if node["id"] in used_ids:
            raise ValueError(f"原稿包含重复的锚点：{node['id']}")
        used_ids.add(node["id"])
    headings = soup.find_all(["h2", "h3", "h4"])
    for index, heading in enumerate(headings, 1):
        if heading.get("id"):
            continue
        previous = heading.find_previous_sibling()
        anchor = previous if previous and previous.name == "a" and previous.get("id") and not previous.get_text(strip=True) else None
        if anchor:
            heading["id"] = anchor["id"]
            anchor.decompose()
        else:
            slug = f"section-{index:03d}"
            while slug in used_ids:
                slug += "-x"
            heading["id"] = slug
            used_ids.add(slug)

    image_count = 0
    for image in list(soup.find_all("img")):
        src = image.get("src", "")
        if not src:
            raise ValueError("图片缺少地址。")
        if not src.startswith("data:"):
            parsed = urlparse(src)
            if parsed.scheme or parsed.netloc:
                raise ValueError(f"离线输出要求本地图片，请先保存图片再转换：{src}")
            image_path = (source.parent / unquote(parsed.path)).resolve()
            if asset_root is not None and not image_path.is_relative_to(Path(asset_root).resolve()):
                raise TemplateError(f"项目图片必须保存在 assets 文件夹内：{src}")
            if not image_path.is_file():
                raise FileNotFoundError(f"找不到图片：{image_path}")
            mime = "image/svg+xml" if image_path.suffix.lower() == ".svg" else mimetypes.guess_type(image_path.name)[0]
            if not mime or not mime.startswith("image/"):
                raise ValueError(f"不支持的图片类型：{image_path.name}")
            image["src"] = f"data:{mime};base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")
        check_image_uri(image["src"], image.get("alt") or "图片")
        image["decoding"] = "async"
        image_count += 1
        p = image.parent
        if p and p.name == "p" and len(p.contents) == 1:
            figure = soup.new_tag("figure")
            if image_count == 1 and not image.find_previous("h2"):
                figure["class"] = "hero-figure"
            p.replace_with(figure)
            button = soup.new_tag("button", attrs={"type": "button", "class": "image-button", "aria-label": "放大图片：" + image.get("alt", "图示")})
            button.append(image.extract())
            figure.append(button)
            following = figure.find_next_sibling()
            caption_text = image.get("alt", "")
            if following and following.name == "p" and following.find("em") and following.get_text(strip=True).startswith("图"):
                caption_text = following.get_text(strip=True)
                following.decompose()
            caption = soup.new_tag("figcaption")
            caption.string = caption_text
            hint = soup.new_tag("span", attrs={"class": "figure-hint"})
            hint.string = "点击查看大图"
            caption.append(hint)
            figure.append(caption)
    for table in soup.find_all("table"):
        wrapper = soup.new_tag("div", attrs={"class": "table-scroll", "tabindex": "0", "role": "region", "aria-label": "表格，可横向滚动"})
        table.wrap(wrapper)
    for link in soup.find_all("a", href=True):
        if link["href"].startswith(("http://", "https://")):
            link["rel"] = "noopener noreferrer"

    toc_items = []
    parent_id = ""
    h2_count = 0
    for heading in headings:
        if heading.name == "h4":
            continue
        ident = heading["id"]
        label = html.escape(heading.get_text(" ", strip=True))
        if heading.name == "h2":
            parent_id = ident
            h2_count += 1
            attrs = 'class="toc-main"'
        else:
            attrs = f'class="toc-sub" data-parent="{html.escape(parent_id, quote=True)}"'
        toc_items.append(f'<li {attrs}><a href="#{html.escape(ident, quote=True)}">{label}</a></li>')
    toc = '<ol class="toc-list">' + "".join(toc_items) + "</ol>"
    content = str(soup)
    count_soup = BeautifulSoup(content, "html.parser")
    for node in count_soup.select(".figure-hint,script,style"):
        node.decompose()
    word_count = len(re.sub(r"\s+", "", count_soup.get_text()))
    desc = soup.get_text(" ", strip=True)[:140]
    replacements = {
        "TITLE": html.escape(title), "DESCRIPTION": html.escape(desc, quote=True),
        "MARGIN": str(margin), "AUTHOR": html.escape(author),
        "DATE": f'<time datetime="{date}">{date}</time>' if date else "未填写",
        "WORD_COUNT": f"{word_count:,}", "SECTION_COUNT": str(h2_count),
        "CSS": files["reader.css"],
        "JS": files["reader.js"],
        "TOC": toc, "CONTENT": content,
    }
    shell = files["shell.html"]
    # 单次替换，避免原文中的类似占位符被二次解释。
    result = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: replacements[m.group(1)], shell)
    report = validate_html(result, expected_title=title, expected_author=author,
                           expected_date=date, expected_margin=margin)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=output.parent,
                                         prefix=".html-build-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(result)
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {**report, "file": str(output), "headings": len(headings), "chapters": h2_count, "images": image_count, "words": word_count, "omitted_opening": omitted_opening, "bytes": output.stat().st_size}


def build_from_config(config_path: Path):
    return render(**load_config(config_path))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Markdown → 单文件知识文档 HTML")
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--config", type=Path, help="推荐入口：项目的 document.json")
    parser.add_argument("--layout", choices=["clean", "book", "compact"])
    parser.add_argument("--margin", type=int, choices=range(0, 41), help="左右每侧留白百分比：0 为满宽，40 为窄栏")
    parser.add_argument("--subtitle")
    parser.add_argument("--category")
    parser.add_argument("--meta")
    parser.add_argument("--author", help="作者署名")
    parser.add_argument("--date", help="固定的发表日期 YYYY-MM-DD；不会自动使用导出当天")
    parser.add_argument("--omit-opening-line", dest="omit_opening_line", action="append", help="省略明确指定的开篇展示说明，可重复提供")
    args = vars(parser.parse_args())
    config_path = args.pop("config")
    try:
        if config_path:
            if any(value is not None for value in args.values()):
                parser.error("--config 不与位置参数或旧版选项混用；文章信息统一写入配置。")
            report = build_from_config(config_path)
        else:
            if args["source"] is None or args["output"] is None:
                parser.error("请提供 --config document.json，或同时提供 Markdown 与 HTML 路径。")
            report = render(**{key: value for key, value in args.items() if value is not None})
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        print(f"生成失败：{exc}", file=sys.stderr)
        sys.exit(1)
