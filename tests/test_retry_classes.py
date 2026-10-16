"""模拟 pi 的几种失败形态，核对 _call_one 的分流：接口报错原样重试（不附「请重写」）、格式不合格带反馈重试。

运行：python3 tests/test_retry_classes.py（不调用真实模型）
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import council  # noqa: E402

GOOD = "## 发现\n- [P2][补充] x\n\n## 各方案评语\n### 方案A\n- ok\n\n## 共识与分歧\n- 无\n"
STREAM_ERR = "Streaming response failed: [server_error] upstream service timeout\n"

# 每个场景：依次返回的 (rc, stdout, stderr)；期望：最终成功与否、各次尝试的首条 problem 前缀、第二次 prompt 是否带「请重写」
SCENARIOS = {
    "流式中断 rc=1 → 接口报错原样重试": ([(1, "", STREAM_ERR), (0, GOOD, "")], True, ["接口报错"], False),
    "空响应 rc=0 → 接口报错原样重试": ([(0, "", ""), (0, GOOD, "")], True, ["接口报错"], False),
    "格式不合格 → 带反馈重试": ([(0, "随便写写", ""), (0, GOOD, "")], True, ["缺少"], True),
    "额度用尽 → 直接失败": ([(1, "", "usage limit reached")], False, ["额度用尽"], None),
    "连续空响应 → 等待用尽后失败": ([(0, "", "")] * 3, False, ["接口报错", "接口报错", "接口报错"], False),
}


def run_scenario(name, outcomes, expect_ok, expect_prefixes, expect_rewrite):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "repo").mkdir()
        (d / "brief.md").write_text("b", encoding="utf-8")
        cfg = json.loads((ROOT / "council.json").read_text(encoding="utf-8"))
        cfg["sandbox"] = {"enabled": False}
        cfg["rate_limit"] = {"waits": [0, 0]}
        run = council.Run(d, cfg, resume=False)
        queue = list(outcomes)

        def fake_execute(script, timeout):
            tag = Path(script).stem
            rc, out, err = queue.pop(0)
            (d / "raw" / f"{tag}.out").write_text(out, encoding="utf-8")
            (d / "raw" / f"{tag}.err").write_text(err, encoding="utf-8")
            return rc

        council.execute = fake_execute
        agent = council.resolve_roles(cfg)["light"]["critics"]["verify"]
        text = run._call_one("critic-verify", "critic-verify", "critic", agent, "PROMPT", False)
        rows = [json.loads(l) for l in (d / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        prefixes = [r["problems"][0] for r in rows if r["problems"]]
        prompts = sorted((d / "prompts").glob("*.md"))
        rewrite = ("上一次输出不合格" in prompts[1].read_text(encoding="utf-8")) if len(prompts) > 1 else None
        ok = (text is not None) == expect_ok and len(prefixes) == len(expect_prefixes) \
            and all(p.startswith(e) for p, e in zip(prefixes, expect_prefixes)) and rewrite == expect_rewrite \
            and not queue
        print(("PASS" if ok else "FAIL"), name, "|", prefixes, "| 第二次带请重写:", rewrite)
        return ok


def check_variant_timeouts():
    """格式变体沿用基础角色超时：诊断评审曾因 critic_diagnosis 不在 timeouts 里被按默认 1800s 截断。"""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "repo").mkdir()
        (d / "brief.md").write_text("b", encoding="utf-8")
        cfg = json.loads((ROOT / "council.json").read_text(encoding="utf-8"))
        cfg["sandbox"] = {"enabled": False}
        run = council.Run(d, cfg, resume=False)
        t = cfg["timeouts"]
        got = {k: run.timeout(k) for k in ("critic_diagnosis", "drafter_bug", "critic")}
        # 显式配了 critic_diagnosis 就用它，否则回落到 critic
        ok = got == {"critic_diagnosis": t.get("critic_diagnosis", t["critic"]), "drafter_bug": t["drafter"],
                     "critic": t["critic"]}
        cfg["timeouts"].pop("critic_diagnosis", None)
        run.cfg = cfg
        ok &= run.timeout("critic_diagnosis") == t["critic"]
        print(("PASS" if ok else "FAIL"), "格式变体沿用基础角色超时 |", got)
        return ok


results = [run_scenario(n, *s) for n, s in SCENARIOS.items()] + [check_variant_timeouts()]
sys.exit(0 if all(results) else 1)
