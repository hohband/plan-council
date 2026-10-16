"""读权限沙箱预检：起不来（如身处别的 agent 的严格沙箱）时立即停并说明原因，不让每次模型调用都失败。

运行：python3 tests/test_sandbox_preflight.py（仅 macOS；不调用模型）
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import council  # noqa: E402

if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
    print("SKIP 非 macOS 或没有 sandbox-exec")
    sys.exit(0)

checks = []
with tempfile.TemporaryDirectory() as tmp:
    ok_profile = Path(tmp) / "ok.sb"
    ok_profile.write_text("(version 1)\n(allow default)\n", encoding="utf-8")
    # deny default 连 /usr/bin/true 都执行不了，模拟严格沙箱里套不上第二层
    bad_profile = Path(tmp) / "bad.sb"
    bad_profile.write_text("(version 1)\n(deny default)\n", encoding="utf-8")

    try:
        council.check_sandbox_usable(ok_profile)
        checks.append(("沙箱可用时放行", True))
    except SystemExit:
        checks.append(("沙箱可用时放行", False))
    checks.append(("沙箱关闭时跳过", council.check_sandbox_usable(None) is None))
    try:
        council.check_sandbox_usable(bad_profile)
        checks.append(("沙箱起不来时立即停", False))
    except SystemExit as e:
        msg = str(e)
        checks.append(("沙箱起不来时立即停", True))
        checks.append(("提示说明原因与处理", "另一个 agent 的沙箱" in msg and "sandbox.enabled=false" in msg))

ok = True
for name, passed in checks:
    ok &= passed
    print(("PASS" if passed else "FAIL"), name)
sys.exit(0 if ok else 1)
