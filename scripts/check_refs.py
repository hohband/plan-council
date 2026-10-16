#!/usr/bin/env python3
"""机械核验 Markdown 里的代码引用：path:line、npm 脚本、测试文件、ADR 编号、符号。

plan-council 每一步都用它；也可单独跑：

    check_refs.py plan.md --repo <仓库或快照根> [--strict-symbols] [--json]

级别：
- hard：引用的文件不存在却给了行号、行号超出文件长度、ADR 编号不存在 —— 必须剔除或更正
- warn：行号漂移（同一行提到的符号在该文件里，但不在引用行附近）、npm 脚本不存在、
        严格模式下代码里不存在的符号
- info：不带行号的路径不存在（可能是计划新增）、测试文件不存在、非严格模式下的未知符号
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next",
             ".cache", "coverage", ".turbo", ".pytest_cache"}
MAX_TEXT_BYTES = 1024 * 1024
# 引用常指向函数体内部，函数名在上方较远处，所以向上看得更远
DRIFT_ABOVE = 30
DRIFT_BELOW = 10

CODE_EXT = r"(?:js|mjs|cjs|ts|tsx|jsx|vue|py|json|md|ya?ml|sql|sh|toml|css|scss|html)"
LINE_SPEC = r"(\d+(?:\s*[-–~]\s*\d+)?(?:,\d+(?:[-–~]\d+)?)*)"
PATH_RE = re.compile(
    r"(?<![\w/.@-])((?:\.{1,2}/)?(?:[\w.@-]+/)*[\w@-][\w.@-]*\." + CODE_EXT + r")"
    r"(?::" + LINE_SPEC + r")?(?![\w/])"
)
BARE_LINE_RE = re.compile(r"`:" + LINE_SPEC + r"`")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
CODE_LIKE_RE = re.compile(r"[a-z][A-Z]|_|^[A-Z][a-z]+[A-Z]")
NPM_RE = re.compile(r"npm\s+(?:--prefix[ =](\S+)\s+)?(?:run|run-script)\s+([\w:.-]+)")
CD_RE = re.compile(r"cd\s+([\w./-]+)\s*&&")
TEST_RE = re.compile(r"(?:[\w.-]+/)*__tests__/[\w.-]+\.test\.[jt]sx?")
ADR_RE = re.compile(r"ADR[\s-]*#?(\d{1,4})\b", re.I)
STOP_IDENTS = {"node_modules", "__tests__", "__dirname", "__filename"}


@dataclass
class Finding:
    line: int
    ref: str
    kind: str
    level: str
    message: str


@dataclass
class Report:
    findings: list = field(default_factory=list)
    path_refs: int = 0
    path_ok: int = 0

    def add(self, line, ref, kind, level, message):
        self.findings.append(Finding(line, ref, kind, level, message))

    def count(self, level=None, kind=None):
        return sum(1 for f in self.findings
                   if (level is None or f.level == level) and (kind is None or f.kind == kind))

    def counts(self):
        return {
            "path_refs": self.path_refs,
            "path_ok": self.path_ok,
            "hard": self.count("hard"),
            "missing": self.count(kind="MISSING"),
            "bad_line": self.count(kind="BAD_LINE"),
            "drift": self.count(kind="DRIFT"),
            "no_script": self.count(kind="NO_SCRIPT"),
            "bad_adr": self.count(kind="BAD_ADR"),
            "unknown_symbol": self.count(kind="UNKNOWN_SYMBOL"),
        }


class RepoIndex:
    """仓库（或快照）里的文件、行、符号与 npm 脚本，按需加载并缓存。"""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.files = set()
        self.by_name = defaultdict(list)
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                rel = Path(dirpath, name).relative_to(self.root).as_posix()
                self.files.add(rel)
                self.by_name[name].append(rel)
        self._lines = {}
        self._symbols = None
        self._scripts = {}

    def resolve(self, ref):
        ref = re.sub(r"^(\./)+", "", ref)
        if ref in self.files:
            return [ref]
        name = ref.rsplit("/", 1)[-1]
        return sorted(f for f in self.by_name.get(name, []) if f == ref or f.endswith("/" + ref))

    def lines(self, rel):
        if rel not in self._lines:
            try:
                self._lines[rel] = (self.root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                self._lines[rel] = []
        return self._lines[rel]

    def symbols(self):
        if self._symbols is None:
            found = set()
            for rel in self.files:
                path = self.root / rel
                try:
                    if path.stat().st_size > MAX_TEXT_BYTES:
                        continue
                    data = path.read_bytes()
                except OSError:
                    continue
                if b"\0" in data[:4096]:
                    continue
                found.update(IDENT_RE.findall(data.decode("utf-8", errors="replace")))
            self._symbols = found
        return self._symbols

    def scripts(self, pkg_dir):
        key = pkg_dir.strip("/") or "."
        if key not in self._scripts:
            pkg = self.root / key / "package.json"
            try:
                self._scripts[key] = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
            except (OSError, ValueError):
                self._scripts[key] = None
        return self._scripts[key]


def parse_ranges(spec):
    ranges = []
    for part in spec.split(","):
        nums = [int(n) for n in re.findall(r"\d+", part)]
        if nums:
            ranges.append((nums[0], nums[-1] if len(nums) > 1 else nums[0]))
    return ranges


def code_idents(md_line, exclude):
    """反引号里、看起来像代码标识符的名字（驼峰、下划线、常量码）。"""
    idents = []
    for span in BACKTICK_RE.findall(md_line):
        if PATH_RE.fullmatch(span.strip()):
            continue
        for tok in IDENT_RE.findall(span):
            if len(tok) >= 4 and tok not in STOP_IDENTS and tok not in exclude and CODE_LIKE_RE.search(tok):
                idents.append(tok)
    return list(dict.fromkeys(idents))


def check_location(report, index, line_no, segment, ref, spec):
    """segment：这条引用前后、到相邻引用为止的文字，里面的符号用来判断行号是否漂移。"""
    report.path_refs += 1
    candidates = index.resolve(ref)
    if not candidates:
        if spec:
            report.add(line_no, f"{ref}:{spec}", "MISSING", "hard", "文件不存在")
        else:
            report.add(line_no, ref, "NOT_FOUND", "info", "文件不存在（若为计划新增可忽略）")
        return
    if not spec:
        report.path_ok += 1
        return
    ranges = parse_ranges(spec)
    path_parts = set(IDENT_RE.findall(ref))
    idents = code_idents(segment, path_parts)
    best = None
    for rel in candidates:
        lines = index.lines(rel)
        if any(b > len(lines) for _, b in ranges):
            best = best or ("BAD_LINE", rel, f"`{rel}` 只有 {len(lines)} 行")
            continue
        present = [t for t in idents if any(t in ln for ln in lines)]
        if not present:
            best = ("OK", rel, "")
            break
        near = any(
            t in ln
            for a, b in ranges
            for ln in lines[max(0, a - 1 - DRIFT_ABOVE):b + DRIFT_BELOW]
            for t in present
        )
        if near:
            best = ("OK", rel, "")
            break
        where = [i + 1 for i, ln in enumerate(lines) if present[0] in ln][:3]
        best = best if best and best[0] == "DRIFT" else (
            "DRIFT", rel, f"`{present[0]}` 不在 :{spec} 附近，实际出现在 " + "、".join(f":{w}" for w in where))
    kind, rel, msg = best
    if kind == "OK":
        report.path_ok += 1
    elif kind == "BAD_LINE":
        report.add(line_no, f"{ref}:{spec}", "BAD_LINE", "hard", "行号超出文件长度：" + msg)
    else:
        report.add(line_no, f"{ref}:{spec}", "DRIFT", "warn", "行号漂移：" + msg)


def check_text(text, index, strict_symbols=False):
    report = Report()
    adr_numbers = {m.group(1).lstrip("0") for f in index.files
                   if f.startswith("docs/adr/") for m in [re.match(r"docs/adr/(\d+)", f)] if m}
    unknown_seen = set()
    for line_no, md_line in enumerate(text.splitlines(), 1):
        cites = []  # (start, end, ref, spec)
        for m in PATH_RE.finditer(md_line):
            if "://" in md_line[max(0, m.start() - 8):m.start()]:
                continue
            cites.append((m.start(), m.end(), m.group(1), m.group(2)))
        for m in BARE_LINE_RE.finditer(md_line):
            if any(a <= m.start() < b for a, b, _, _ in cites):
                continue
            before = sorted((c for c in cites if c[1] <= m.start()), key=lambda c: -c[1])
            if before:
                # `:819` 续接同一行里它前面的路径：先试最近的；行号放不下时依次试更早的，
                # 都放不下才按最近的报错（作者常在同一行里切换上下文）
                ranges = parse_ranges(m.group(1))
                fits = [c for c in before
                        if any(all(b <= len(index.lines(rel)) for _, b in ranges) for rel in index.resolve(c[2]))]
                cites.append((m.start(), m.end(), (fits or before)[0][2], m.group(1)))
        cites.sort()
        for i, (start, end, ref, spec) in enumerate(cites):
            seg_from = cites[i - 1][1] if i else 0
            seg_to = cites[i + 1][0] if i + 1 < len(cites) else len(md_line)
            check_location(report, index, line_no, md_line[seg_from:seg_to], ref, spec)

        for m in NPM_RE.finditer(md_line):
            prefix, script = m.group(1), m.group(2)
            if prefix is None:
                cds = [c for c in CD_RE.finditer(md_line) if c.end() <= m.start()]
                prefix = cds[-1].group(1) if cds else "."
            scripts = index.scripts(prefix)
            if scripts is not None and script not in scripts:
                report.add(line_no, f"npm run {script}", "NO_SCRIPT", "warn",
                           f"`{prefix}/package.json` 没有脚本 `{script}`（若为计划新增可忽略）")

        for m in TEST_RE.finditer(md_line):
            if not index.resolve(m.group(0)):
                report.add(line_no, m.group(0), "TEST_NOT_FOUND", "info", "测试文件不存在（新增或幻觉）")

        for m in ADR_RE.finditer(md_line):
            if adr_numbers and m.group(1).lstrip("0") not in adr_numbers:
                report.add(line_no, m.group(0), "BAD_ADR", "hard", "docs/adr 下没有这个编号")

        symbols = None
        for tok in code_idents(md_line, set()):
            if tok in unknown_seen and not strict_symbols:
                continue
            symbols = symbols if symbols is not None else index.symbols()
            if tok not in symbols:
                unknown_seen.add(tok)
                report.add(line_no, tok, "UNKNOWN_SYMBOL", "warn" if strict_symbols else "info",
                           "代码里不存在这个名字" + ("" if strict_symbols else "（计划新增的名字可忽略）"))
    return report


def annotate(text, report, drop_hard=False):
    """把核验结果写回文档：hard 行剔除（drop_hard）或行尾标注，warn 行尾标注。"""
    by_line = defaultdict(list)
    for f in report.findings:
        if f.level in ("hard", "warn"):
            by_line[f.line].append(f)
    out, dropped = [], []
    for line_no, md_line in enumerate(text.splitlines(), 1):
        items = by_line.get(line_no)
        if not items:
            out.append(md_line)
            continue
        hard = [f for f in items if f.level == "hard"]
        if hard and drop_hard:
            dropped.append(f"- {md_line.strip()} 【{'；'.join(f.ref + ' ' + f.message for f in hard)}】")
            continue
        notes = "；".join(f"{f.ref} {f.message}" for f in items)
        tag = "核验失败" if hard else "核验警告"
        out.append(f"{md_line} 【{tag}：{notes}】")
    if dropped:
        out += ["", "## 已剔除（脚本核验失败）", *dropped]
    return "\n".join(out) + "\n"


def summary(report):
    c = report.counts()
    return (f"路径引用 {c['path_refs']} 条：通过 {c['path_ok']}，缺失 {c['missing']}，行号越界 {c['bad_line']}，"
            f"行号漂移 {c['drift']}；npm 脚本缺失 {c['no_script']}；ADR 编号错误 {c['bad_adr']}；"
            f"代码中不存在的名字 {c['unknown_symbol']}")


def render(report, title):
    lines = [f"# 引用核验：{title}", "", summary(report), ""]
    for level, heading in (("hard", "硬错误（必须剔除或更正）"), ("warn", "警告"), ("info", "信息")):
        items = [f for f in report.findings if f.level == level]
        if items:
            lines += [f"## {heading}", ""]
            lines += [f"- L{f.line} `{f.ref}` — {f.kind}：{f.message}" for f in items]
            lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="要核验的 Markdown 文件")
    parser.add_argument("--repo", default=".", help="仓库或快照根目录（默认当前目录）")
    parser.add_argument("--strict-symbols", action="store_true", help="代码里不存在的名字记为警告")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    text = Path(args.file).read_text(encoding="utf-8")
    report = check_text(text, RepoIndex(args.repo), strict_symbols=args.strict_symbols)
    if args.json:
        print(json.dumps({"counts": report.counts(), "findings": [asdict(f) for f in report.findings]},
                         ensure_ascii=False, indent=2))
    else:
        print(render(report, args.file))
    return 1 if report.count("hard") else 0


if __name__ == "__main__":
    sys.exit(main())
