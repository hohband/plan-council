"""思考档位检查：按 pi 的规则算出各模型支持的档位，以及配了无效档时 pi 实际生效的档。

运行：python3 tests/test_thinking_levels.py（不调用真实模型，用假模型库）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import council  # noqa: E402

# 形态取自 ~/.pi/agent/models-store.json（2026-10-04）
STORE = {
    "opencode-go": {"models": [
        {"id": "glm-5.3-flash", "reasoning": True, "thinkingLevelMap": {
            "off": None, "minimal": None, "low": "low", "medium": None, "high": "high", "xhigh": None, "max": "max"}},
        {"id": "gpt-6-luna", "reasoning": True, "thinkingLevelMap": {
            "off": "none", "minimal": None, "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh",
            "max": "max"}},
        {"id": "plain-reasoner", "reasoning": True},
        {"id": "no-reasoning", "reasoning": False},
    ]},
}


def agent(model, level):
    return {"cli": "pi", "model": f"opencode-go/{model}", "thinking": level}


CASES = [
    ("GLM 支持的档位", council.pi_thinking_levels("opencode-go/glm-5.3-flash", STORE), ["low", "high", "max"]),
    ("Luna 支持的档位", council.pi_thinking_levels("opencode-go/gpt-6-luna", STORE),
     ["off", "low", "medium", "high", "xhigh", "max"]),
    ("无映射表：xhigh/max 不可用", council.pi_thinking_levels("opencode-go/plain-reasoner", STORE),
     ["off", "minimal", "low", "medium", "high"]),
    ("不支持思考：只有 off", council.pi_thinking_levels("opencode-go/no-reasoning", STORE), ["off"]),
    ("查不到的模型", council.pi_thinking_levels("opencode-go/unknown", STORE), None),
    ("GLM medium 往上取 high", council.thinking_level_issues([agent("glm-5.3-flash", "medium")], STORE),
     [("pi/opencode-go/glm-5.3-flash:medium", "medium", "high", ["low", "high", "max"])]),
    ("GLM xhigh 往上取 max", [i[2] for i in council.thinking_level_issues([agent("glm-5.3-flash", "xhigh")], STORE)],
     ["max"]),
    ("无映射表配 max 往下取 high",
     [i[2] for i in council.thinking_level_issues([agent("plain-reasoner", "max")], STORE)], ["high"]),
    ("有效档不报", council.thinking_level_issues(
        [agent("glm-5.3-flash", "max"), agent("gpt-6-luna", "xhigh"), agent("glm-5.3-flash", "high")], STORE), []),
    ("同一模型同档只报一次", len(council.thinking_level_issues(
        [agent("glm-5.3-flash", "medium"), agent("glm-5.3-flash", "medium")], STORE)), 1),
    ("查不到的模型报出来", [i[2:] for i in council.thinking_level_issues([agent("unknown", "high")], STORE)],
     [(None, None)]),
]

ok = True
for name, got, want in CASES:
    passed = got == want
    ok &= passed
    print(("PASS" if passed else "FAIL"), name, "|", got if passed else f"得到 {got}，期望 {want}")
sys.exit(0 if ok else 1)
