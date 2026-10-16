"""沙箱默认禁读各编码助手的会话记录：回放历史任务时原修复会话可能就在里面（实测出现过原修复的 codex 会话）。
用临时 HOME 造假会话记录和 pi 配置，在真实 sandbox-exec 下核对：会话读不到，运行目录与 pi 配置照常可读。

运行：python3 tests/test_sandbox_sessions.py（仅 macOS 做读权限实测；不调用模型）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import council  # noqa: E402


def readable(profile, path):
    return subprocess.run(["sandbox-exec", "-f", str(profile), "cat", str(path)],
                          capture_output=True).returncode == 0


checks = []
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp).resolve()
    home = tmp / "home"
    session = home / ".codex" / "sessions" / "2026" / "10" / "03" / "rollout.jsonl"
    claude_log = home / ".claude" / "projects" / "p" / "s.jsonl"
    pi_config = home / ".pi" / "agent" / "models-store.json"
    for f in (session, claude_log, pi_config):
        f.parent.mkdir(parents=True)
        f.write_text("x", encoding="utf-8")
    run_dir = tmp / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "plan.md").write_text("ok", encoding="utf-8")
    (run_dir / "source.json").write_text(json.dumps({"repo": str(tmp / "repo")}), encoding="utf-8")

    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        cfg = {"sandbox": {"enabled": True, "deny_read": []}}
        profile = council.write_sandbox_profile(run_dir, cfg)
        text = profile.read_text(encoding="utf-8") if profile else ""
        checks.append(("默认规则列出会话目录", f'(deny file-read* (subpath "{home / ".codex/sessions"}"))' in text
                       and f'(subpath "{home / ".claude/projects"}")' in text))
        checks.append(("不封 pi 的配置目录", f'(subpath "{home / ".pi/agent"}")' not in text))
        if sys.platform == "darwin" and shutil.which("sandbox-exec"):
            checks.append(("codex 会话读不到", not readable(profile, session)))
            checks.append(("Claude 对话记录读不到", not readable(profile, claude_log)))
            checks.append(("运行目录可读", readable(profile, run_dir / "plan.md")))
            checks.append(("pi 配置可读", readable(profile, pi_config)))
        off = council.write_sandbox_profile(run_dir, {"sandbox": {"enabled": True, "deny_agent_sessions": False}})
        checks.append(("关闭开关时不封会话", ".codex/sessions" not in off.read_text(encoding="utf-8")))
        if sys.platform == "darwin" and shutil.which("sandbox-exec"):
            checks.append(("关闭开关后会话可读", readable(off, session)))
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home

ok = True
for name, passed in checks:
    ok &= passed
    print(("PASS" if passed else "FAIL"), name)
sys.exit(0 if ok else 1)
