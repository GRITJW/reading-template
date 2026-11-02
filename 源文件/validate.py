"""重新检查已有的单文件 HTML；可选配置会额外核对文章信息。"""
from pathlib import Path
import argparse
import json
import sys

from template_runtime import load_config, validate_html


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="检查固定模板、完整内嵌图片、目录与字数")
    parser.add_argument("html", type=Path, nargs="?")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    try:
        expected = {}
        if args.config:
            config = load_config(args.config)
            path = args.html.resolve() if args.html else config["output"]
            expected = {"expected_title": config["expected_title"], "expected_author": config["author"],
                        "expected_date": config["date"], "expected_margin": config["margin"]}
        elif args.html:
            path = args.html.resolve()
        else:
            parser.error("请提供 HTML 路径或 --config document.json。")
        report = validate_html(path.read_text(encoding="utf-8-sig"), **expected)
        print(json.dumps({"file": str(path), **report}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
