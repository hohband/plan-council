"""「先核实」挑选规则：[反驳] 点名了草案判为「成立」的假设。
定位段（第一个冒号前）点名即算；论断段（冒号后、「 — 」证据前）明确判它「不成立 / 未裁决」等也算。

运行：python3 tests/test_refute_established.py（纯函数，不调用模型）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import council  # noqa: E402

EST = ["H1", "H2"]  # 草案判为成立的假设
CASES = [
    # (说明, 评审原文, 期望是否挑出)
    ("定位段点名成立假设（GLM 实跑写法）",
     "- [P1][反驳] 方案A §根因 H1：「fetch() 收到非 AbortSignal 即抛」未裁决 — 反例：`a.js:1`", True),
    ("论断段判成立假设不成立（LongCat 实跑写法）",
     "- [P1][反驳] 方案A §因果链：「Agent对话」取消后无可见变化 ← H1（刷错 store）不成立 — 反例：`a.js:1`", True),
    ("论断段判成立假设未裁决",
     "- [P2][反驳] 方案A §根因：H2 的结论未裁决，缺现场证据 — 反例：`a.js:1`", True),
    ("定位段点名多个，其中一个成立",
     "- [P1][反驳] 方案A §根因 H4/H2（推论部分）：说法过满 — 反例：`a.js:1`", True),
    ("定位段点名待查假设", "- [P2][反驳] 方案A §根因 H3：确认框其实走通了 — 反例：`a.js:1`", False),
    ("论断段判的是方案本就排除的假设", "- [P2][反驳] 方案A §因果链：H3 不成立的论证缺一环 — 反例：`a.js:1`", False),
    ("只在正文提到成立假设，没有否定判断", "- [P1][反驳] 方案A §步骤3：只修 H1 仍不能保证即时刷新 — 反例：`a.js:1`", False),
    ("否定判断只出现在证据段", "- [P1][反驳] 方案A §步骤4：缺回滚 — 反例：`a.js:1` 显示若 H1 不成立则需另修", False),
    ("证据段用「——」分隔时同样不算", "- [P1][反驳] 方案A §步骤4：缺回滚——反例：`a.js:1` 显示若 H1 不成立则需另修", False),
    ("组件名里的 H3 不当假设编号", "- [P1][反驳] 方案A §边界 H3TaskCard 不动：不成立 — 反例：`a.js:1`", False),
    ("不是反驳", "- [P1][补充] 方案A §根因：H1 不成立时还要补一条 — 依据：`a.js:1`", False),
]

ok = True
for name, text, want in CASES:
    kind = next((k for k in ("反驳", "顾虑", "补充") if f"[{k}]" in text), "未分类")
    got = council.refutes_established({"type": kind, "text": text}, EST)
    ok &= got == want
    print(("PASS" if got == want else "FAIL"), name, "|", got)
sys.exit(0 if ok else 1)
