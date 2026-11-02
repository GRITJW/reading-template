"""固定模板、文章配置与离线输出的共同校验。"""
from __future__ import annotations

import base64
import binascii
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
TEMPLATE_ROOT = HERE.parent
TEMPLATE_ID = "knowledge-reader-v5"
TEMPLATE_VERSION = "1.0.0"
VISUAL_FILES = ("shell.html", "reader.css", "reader.js")


class TemplateError(ValueError):
    """可以直接显示给作者的输入或成品问题。"""


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TemplateError(f"JSON 中存在重复字段：{key}")
        result[key] = value
    return result


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_object_pairs)
    except json.JSONDecodeError as exc:
        raise TemplateError(f"JSON 格式错误：{path.name} 第 {exc.lineno} 行。") from exc


def check_date(value):
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise TemplateError("发表日期须为 YYYY-MM-DD，未知时填写 null。")
    try:
        datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise TemplateError(f"发表日期不是有效日期：{value}") from exc
    return value


def verify_template(template_root: Path = TEMPLATE_ROOT):
    lock = read_json(template_root / "template-lock.json")
    if (lock.get("template_id"), lock.get("version")) != (TEMPLATE_ID, TEMPLATE_VERSION):
        raise TemplateError("模板标识或版本不符，请使用整套已确认的模板文件。")
    if set(lock.get("sha256", {})) != set(VISUAL_FILES):
        raise TemplateError("模板锁定清单不完整。")
    files = {}
    for name in VISUAL_FILES:
        path = template_root / "源文件" / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != lock["sha256"][name]:
            raise TemplateError(f"固定模板被改动：{name}。请恢复已确认的版本；生成正文时不要修改模板。")
        files[name] = path.read_text(encoding="utf-8")
    return files


def _keys(value, allowed, required, label):
    if not isinstance(value, dict):
        raise TemplateError(f"{label} 必须是 JSON 对象。")
    missing, extra = required - value.keys(), value.keys() - allowed
    if missing:
        raise TemplateError(f"{label} 缺少字段：{', '.join(sorted(missing))}")
    if extra:
        raise TemplateError(f"{label} 含有未知字段：{', '.join(sorted(extra))}")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise TemplateError(f"{label} 须为非空文字。")
    return value.strip()


def _project_path(base, value, suffix, label):
    value = _text(value, label)
    path = Path(value)
    if path.is_absolute() or path.drive or re.match(r"^(?:[A-Za-z]:|[\\/]{2})", value):
        raise TemplateError(f"{label} 请使用相对于 document.json 的路径。")
    resolved = (base / path).resolve()
    if not resolved.is_relative_to(base):
        raise TemplateError(f"{label} 不得指向项目文件夹之外。")
    if resolved.suffix.lower() != suffix:
        raise TemplateError(f"{label} 须使用 {suffix} 扩展名。")
    return resolved


def load_config(config_path: Path):
    config_path = config_path.resolve()
    data = read_json(config_path)
    required = {"schema_version", "template_id", "source", "output", "metadata"}
    _keys(data, required | {"$schema", "reading"}, required, "文章配置")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise TemplateError("schema_version 必须为 1。")
    if data["template_id"] != TEMPLATE_ID:
        raise TemplateError(f"template_id 必须为 {TEMPLATE_ID}。")
    metadata = data["metadata"]
    fields = {"title", "author", "publication_date"}
    _keys(metadata, fields, fields, "metadata")
    title = _text(metadata["title"], "文档名称")
    author = _text(metadata["author"], "作者")
    if metadata["publication_date"] == "":
        raise TemplateError("未知发表日期请填写 null，不填写空字符串。")
    date = check_date(metadata["publication_date"])
    reading = data.get("reading", {})
    _keys(reading, {"margin_percent"}, set(), "reading")
    margin = reading.get("margin_percent", 10)
    if type(margin) is not int or not 0 <= margin <= 40:
        raise TemplateError("margin_percent 须为 0—40 的整数。")
    base = config_path.parent
    source = _project_path(base, data["source"], ".md", "source")
    output = _project_path(base, data["output"], ".html", "output")
    if not source.is_file():
        raise TemplateError(f"找不到 Markdown：{source}")
    return {"source": source, "output": output, "expected_title": title,
            "author": author, "date": date, "margin": margin,
            "asset_root": base / "assets"}


def _check_resource_css(text, label, depth):
    if re.search(r"@import\b", text, re.I):
        raise TemplateError(f"{label} 不得导入外部样式。")
    for match in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", text, re.I | re.S):
        value = match.group(2).strip()
        if value.startswith("#"):
            continue
        check_image_uri(value, label, depth + 1)


def check_image_uri(uri, label="图片", depth=0):
    if depth > 6:
        raise TemplateError(f"{label} 的嵌套图片层数过多。")
    match = re.fullmatch(r"data:(image/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)", uri or "")
    if not match:
        raise TemplateError(f"{label} 必须是完整的 base64 内嵌图片，不能引用文件或网址。")
    try:
        payload = base64.b64decode(re.sub(r"\s+", "", match.group(2)), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise TemplateError(f"{label} 的 base64 数据无效。") from exc
    if not payload:
        raise TemplateError(f"{label} 没有图片内容。")
    mime = match.group(1).lower()
    if mime == "image/svg+xml":
        try:
            svg = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise TemplateError(f"{label} 的 SVG 结构无效。") from exc
        if svg.tag.rsplit("}", 1)[-1] != "svg":
            raise TemplateError(f"{label} 不是 SVG 图片。")
        for node in svg.iter():
            if node.tag.rsplit("}", 1)[-1] in {"script", "foreignObject"}:
                raise TemplateError(f"{label} 请使用静态 SVG 图片。")
            for attr, value in node.attrib.items():
                name = attr.rsplit("}", 1)[-1]
                if name in {"href", "src"} and not value.startswith("#"):
                    check_image_uri(value, f"{label} 内部资源", depth + 1)
                if "url(" in value.lower() or "@import" in value.lower():
                    _check_resource_css(value, label, depth)
            if node.tag.rsplit("}", 1)[-1] == "style":
                _check_resource_css("".join(node.itertext()), label, depth)
    return payload


def count_words(body):
    copy = BeautifulSoup(str(body), "html.parser")
    for node in copy.select(".figure-hint,script,style"):
        node.decompose()
    return len(re.sub(r"\s+", "", copy.get_text()))


def validate_html(text, *, expected_title=None, expected_author=None,
                  expected_date=None, expected_margin=None, template_root=TEMPLATE_ROOT):
    files = verify_template(template_root)
    soup = BeautifulSoup(text, "html.parser")
    body = soup.select_one("#article-body")
    if body is None:
        raise TemplateError("HTML 缺少正文区域。")
    if len(soup.select("h1")) != 1 or not soup.select_one(".article-header > h1"):
        raise TemplateError("HTML 必须只有一个位于首页的一级标题。")
    title = soup.h1.get_text(" ", strip=True)
    if expected_title is not None and title != expected_title:
        raise TemplateError("HTML 标题与文章配置不一致。")
    if soup.title is None or soup.title.get_text() != title:
        raise TemplateError("浏览器标题与首页名称不一致。")
    styles = soup.select("style")
    if len(styles) != 1 or styles[0].get_text().strip() != files["reader.css"].strip():
        raise TemplateError("HTML 样式与固定模板不一致。")
    scripts = soup.select("script")
    bootstrap = BeautifulSoup(files["shell.html"], "html.parser").script.get_text().strip()
    if len(scripts) != 2 or scripts[0].get_text().strip() != bootstrap or scripts[-1].get_text().strip() != files["reader.js"].strip():
        raise TemplateError("HTML 阅读功能脚本与固定模板不一致。")
    if soup.select('script[src],link,iframe,object,embed,audio,video,source,[srcset]'):
        raise TemplateError("HTML 不得依赖外部样式、脚本、嵌入页面或额外媒体资源。")
    for node in body.select("[style]"):
        if node.name != "svg" and node.find_parent("svg") is None:
            raise TemplateError("正文不得另写行内样式；请使用现成内容组件或 assets 图片。")
    for node in body.find_all(True):
        if any(name.lower().startswith("on") for name in node.attrs):
            raise TemplateError("正文不得添加额外交互脚本。")
    image_count = 0
    for image in soup.select("img"):
        if image.get("id") == "zoom-image" and not image.get("src"):
            continue
        check_image_uri(image.get("src"), image.get("alt") or "图片")
        image_count += 1
    for svg in body.select("svg"):
        uri = "data:image/svg+xml;base64," + base64.b64encode(str(svg).encode("utf-8")).decode("ascii")
        check_image_uri(uri, "正文 SVG")
    if body.select("form,input,button,select,textarea"):
        # 图片按钮由生成器统一添加，是正文中唯一的按钮组件。
        if body.select("form,input,select,textarea") or any("image-button" not in node.get("class", []) for node in body.select("button")):
            raise TemplateError("正文只支持静态知识内容与现成组件，不添加表单或自定义交互。")
    ids = [node["id"] for node in soup.select("[id]")]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise TemplateError(f"HTML 锚点重复：{', '.join(duplicates)}")
    ids = set(ids)
    for anchor in soup.select('a[href^="#"]'):
        if anchor["href"][1:] not in ids:
            raise TemplateError(f"目录或链接没有目标：{anchor['href']}")
    headings = body.select("h2[id],h3[id]")
    expected_toc = [("#" + node["id"], node.get_text(" ", strip=True)) for node in headings]
    lists = soup.select(".toc-list")
    if len(lists) != 2:
        raise TemplateError("HTML 必须保留桌面与手机两份自动目录。")
    for nav in lists:
        actual = [(node.get("href"), node.get_text(" ", strip=True)) for node in nav.select("a")]
        if actual != expected_toc:
            raise TemplateError("HTML 目录与正文标题不一致。")
    metadata = soup.select(".doc-meta > span")
    if len(metadata) != 3:
        raise TemplateError("首页信息只保留作者、发表日期、字数。")
    if expected_author is not None and metadata[0].get_text(strip=True) != "作者：" + expected_author:
        raise TemplateError("HTML 作者与文章配置不一致。")
    if expected_date is not None:
        wanted = "发表日期：" + (expected_date or "未填写")
        if metadata[1].get_text(strip=True) != wanted:
            raise TemplateError("HTML 发表日期与文章配置不一致。")
    words = count_words(body)
    if metadata[2].get_text(strip=True) != f"字数：{words:,} 字":
        raise TemplateError("HTML 字数与正文实际统计不一致。")
    for selector in (".toolbar", ".toc-rail", "#reader-settings", "#image-dialog", "#toolbar-title", "#font-range", "#margin-range"):
        if soup.select_one(selector) is None:
            raise TemplateError(f"HTML 缺少固定阅读组件：{selector}")
    font_range = soup.select_one("#font-range")
    if (font_range.get("min"), font_range.get("max")) != ("16", "36"):
        raise TemplateError("正文字号范围必须为 16—36。")
    if soup.select_one("#reader-settings").has_attr("open"):
        raise TemplateError("阅读设置应默认隐藏。")
    if expected_margin is not None and soup.body.get("data-margin") != str(expected_margin):
        raise TemplateError("HTML 初始留白与文章配置不一致。")
    return {"status": "passed", "template_id": TEMPLATE_ID, "template_version": TEMPLATE_VERSION,
            "title": title, "images": image_count, "words": words,
            "headings": len(body.select("h2,h3,h4")), "external_resource_count": 0}
