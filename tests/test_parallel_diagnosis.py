"""缺陷模式两路诊断评审：默认配置下 GPT 6 Luna 与 GLM 都以 max 并行评审，报告合并假设复核；
一路失败时记为缺席，另一路照常出报告。

运行：python3 tests/test_parallel_diagnosis.py（不调用真实模型，假的 pi 按模型名返回预制评审）
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import council  # noqa: E402

DRAFT = """## 根因

### 假设表
| 假设 | 层面 | 支持证据 | 矛盾证据 | 结论 |
|---|---|---|---|---|
| H1 刷错 store | 业务逻辑 | `src/a.js:1` | 无 | 成立 |
| H2 零日志证明请求未到达 | 运行层 | `src/a.js:2` | 无 | 成立 |
| H3 确认框没走通 | 运行层 | `src/a.js:3` | 无 | 待查 |

### 因果链
- H1 → 无反馈

### 待查
- H3：浏览器复现

## 目标
修取消。

## 影响面清单
| 位置 | 现状 | 处置 |
|---|---|---|
| `src/a.js:1` | x | y |

## 步骤
1. 改。

## 测试与验收
- 测。

## 风险与回滚
- 无。

## 未决问题
- 无。
"""

VERIFY = "## 发现\n- [P3][补充] 方案A §步骤：补一条测试\n\n## 各方案评语\n### 方案A\n- ok\n\n## 共识与分歧\n- 无\n"


def critique(finding, rows):
    table = "\n".join(f"| {r[0]} | {r[1]} | {r[2]} | 依据 |" for r in rows)
    return (f"## 发现\n{finding}\n\n## 各方案评语\n### 方案A\n- ok\n\n## 共识与分歧\n- 无\n\n"
            f"## 假设复核\n| 假设 | 方案的结论 | 你的结论 | 依据 |\n|---|---|---|---|\n{table}\n")


LUNA = critique("- [P1][补充] 方案A §步骤：按会话匹配会误停下一轮 — 依据：`src/a.js:2`\n"
                "- [P2][反驳] 方案A §根因 H3：确认框其实走通了 — 反例：`src/a.js:1`",
                [("H1 刷错 store", "成立", "成立"), ("H2 零日志证明请求未到达", "成立", "成立"),
                 ("H3 确认框没走通", "待查", "待查"), ("新增 H7：鉴权前被拒", "方案未列", "待查")])
GLM = critique("- [P1][反驳] 方案A §根因 H2：零日志不能证明未到达 — 反例：`src/a.js:3`",
               [("H1 刷错 store", "成立", "成立"), ("H2 零日志证明请求未到达", "成立", "部分成立（失败分支有日志）"),
                ("H3 确认框没走通", "待查", "待查"), ("H7（新增）请求挂起无超时", "—", "待查")])


def run_case(glm_fails):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "repo" / "src").mkdir(parents=True)
        (d / "repo" / "src" / "a.js").write_text("a\nb\nc\nd\n", encoding="utf-8")
        (d / "brief.md").write_text("---\ntype: bug\n---\n取消没反应", encoding="utf-8")
        (d / "source.json").write_text(json.dumps({"kind": "bug"}), encoding="utf-8")
        (d / "outputs").mkdir()
        (d / "outputs" / "draft.md").write_text(DRAFT, encoding="utf-8")
        (d / "outputs" / "critic-verify.md").write_text(VERIFY, encoding="utf-8")
        cfg = json.loads((ROOT / "council.json").read_text(encoding="utf-8"))
        cfg["sandbox"] = {"enabled": False}
        cfg["rate_limit"] = {"waits": []}
        seen = []

        def fake_execute(script, timeout):
            body = Path(script).read_text(encoding="utf-8")
            tag = Path(script).stem
            seen.append(body)
            rc, out = 0, ""
            if "gpt-6-luna" in body:
                out = LUNA
            elif "glm-5.3-flash" in body:
                rc, out = (124, "") if glm_fails else (0, GLM)
            (d / "raw" / f"{tag}.out").write_text(out, encoding="utf-8")
            (d / "raw" / f"{tag}.err").write_text("", encoding="utf-8")
            return rc

        council.execute = fake_execute
        run = council.Run(d, council.resolve_roles(cfg), resume=True)
        state = council.light_pipeline(run)
        council.write_report(run, state)
        report = (d / "report.md").read_text(encoding="utf-8")
        prompts = {p.name: p.read_text(encoding="utf-8") for p in (d / "prompts").glob("critic-diagnosis-*.md")}
        return state, report, seen, sorted(p.name for p in (d / "critiques").glob("*.md")), prompts


def section_items(report, heading_prefix):
    """某个 ### 小节下各条发现的定位段（「方案A §…」到第一个冒号）。"""
    lines = report.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading_prefix)), None)
    if start is None:
        return []
    out = []
    for ln in lines[start + 1:]:
        if ln.startswith("#"):
            break
        if ln.startswith("- "):
            out.append(ln.split("方案A", 1)[-1].split("：", 1)[0].join(["方案A", ""]))
    return out


checks = []
state, report, seen, files, prompts = run_case(glm_fails=False)
checks += [
    ("两路诊断都用 max 档调起", sum("--thinking max" in s for s in seen) == 2 and len(seen) == 2),
    ("两路提示词逐字节一致", len(prompts) == 2 and len(set(prompts.values())) == 1),
    ("各自落盘评审全文", files == ["diagnosis-glm-5.3-flash.md", "diagnosis-gpt-6-luna.md", "verify.md"]),
    ("无缺席", state["absent"] == []),
    ("报告有假设复核对照", "## 假设复核对照" in report),
    ("同结论标一致", any(ln.startswith("| H1 刷错 store") and ln.endswith("| 一致 |") for ln in report.splitlines())),
    ("不同结论标分歧", any(ln.startswith("| H2") and "**分歧**" in ln for ln in report.splitlines())),
    ("新增假设按来源分列", "评审-诊断（gpt-6-luna）新增的假设" in report and "H7（新增）请求挂起无超时 → 待查" in report),
    ("「新增 H7：」写法也认得", "新增 H7：鉴权前被拒 → 待查" in report),
    ("反驳成立假设单列在最前", section_items(report, "### 先核实") == ["方案A §根因 H2"]),
    ("单列的不在普通反驳里重复、反驳待查假设留在普通反驳", section_items(report, "### 反驳：") == ["方案A §根因 H3"]),
    ("发现标明来源模型", "评审-诊断（gpt-6-luna）" in report and "评审-诊断（glm-5.3-flash）：- [P1][反驳]" in report),
]
state, report, seen, files, prompts = run_case(glm_fails=True)
checks += [
    ("一路失败记缺席", state["absent"] == ["评审-诊断（glm-5.3-flash）"]),
    ("另一路照常出报告", "## 假设复核（评审-诊断（gpt-6-luna））" in report and "缺席的评审：评审-诊断（glm-5.3-flash）" in report),
]

ok = True
for name, passed in checks:
    ok &= passed
    print(("PASS" if passed else "FAIL"), name)
sys.exit(0 if ok else 1)
