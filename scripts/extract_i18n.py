#!/usr/bin/env python3
"""翻訳キーの抽出・更新ツール (Qt の pylupdate 代替)。

ソース中の ``tr("...")`` / ``self.tr("...")`` 呼び出しの文字列リテラルを ast で
収集し、`i18n/<locale>.json` を更新する:

  - コードに在るが JSON に無いキー  -> 空訳 "" を追加（未翻訳として）
  - JSON に在るがコードに無いキー    -> 「未使用」として報告（削除はしない）
  - 既存の訳は保持

リテラルでない引数（f-string・変数渡し）は静的に拾えないため警告する。

使い方:
    python3 scripts/extract_i18n.py            # i18n/ja.json を更新
    python3 scripts/extract_i18n.py --locale en
    python3 scripts/extract_i18n.py --check    # 変更が必要なら非0終了（CI用）
"""

import argparse
import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 走査対象外。翻訳対象は実行コードのみ（テスト/依存/ツール自身は除外）。
EXCLUDE_DIRS = {".venv", ".git", ".claude", "tests", "scripts", "i18n", "__pycache__"}


def _iter_py_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _is_tr_call(node: ast.Call) -> bool:
    """tr(...) もしくは <obj>.tr(...) の呼び出しか。"""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "tr"
    if isinstance(func, ast.Attribute):
        return func.attr == "tr"
    return False


class _Collector(ast.NodeVisitor):
    """tr() 呼び出しの文字列リテラルを収集する。

    ``def tr`` 自体の本体（i18n.tr へ委譲するラッパ ``return tr(message)`` 等）は
    翻訳サイトではないので走査対象から外す。
    """

    def __init__(self, rel: str):
        self.rel = rel
        self.keys: set = set()
        self.warnings: list = []

    def visit_FunctionDef(self, node):
        if node.name == "tr":
            return  # 委譲ラッパ。中の tr(message) は翻訳サイトではない。
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        if _is_tr_call(node) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self.keys.add(first.value)
            else:
                self.warnings.append(
                    f"{self.rel}:{node.lineno}: tr() に非リテラル引数（抽出不可）"
                )
        self.generic_visit(node)


def collect(root: str):
    """(翻訳キー集合, 動的引数の警告リスト) を返す。"""
    keys: set = set()
    warnings: list = []
    for path in _iter_py_files(root):
        with open(path, encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read(), filename=path)
            except SyntaxError as e:
                warnings.append(f"{path}: parse error: {e}")
                continue
        collector = _Collector(os.path.relpath(path, root))
        collector.visit(tree)
        keys |= collector.keys
        warnings.extend(collector.warnings)
    return keys, warnings


def update(locale: str, check: bool) -> int:
    keys, warnings = collect(ROOT)
    path = os.path.join(ROOT, "i18n", f"{locale}.json")
    existing = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)

    merged = {k: existing.get(k, "") for k in sorted(keys)}
    unused = sorted(set(existing) - keys)
    added = sorted(k for k in keys if k not in existing)

    changed = merged != existing
    if check:
        if changed:
            print(
                "i18n: 更新が必要です。`python3 scripts/extract_i18n.py` を実行してください。"
            )
        for k in added:
            print(f"  + 新規キー（未翻訳）: {k!r}")
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        print(f"i18n: {path} を更新（{len(merged)} キー, 新規 {len(added)}）")

    for k in unused:
        print(f"  - 未使用（コードに無い）: {k!r}")
    for w in warnings:
        print(f"  ! {w}")

    untranslated = [k for k, v in merged.items() if not v]
    if untranslated:
        print(f"i18n: 未翻訳 {len(untranslated)} キー")

    return 1 if (check and changed) else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--locale", default="ja")
    p.add_argument("--check", action="store_true", help="変更が必要なら非0終了（CI用）")
    args = p.parse_args()
    return update(args.locale, args.check)


if __name__ == "__main__":
    sys.exit(main())
