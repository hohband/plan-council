"""运行期间阻止空闲睡眠：caffeinate 盯住调用进程，进程退出即自动解除；配置可关。

运行：python3 tests/test_keep_awake.py（仅 macOS 实测；不调用模型）
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import council  # noqa: E402

checks = []
if sys.platform != "darwin" or not shutil.which("caffeinate"):
    print("SKIP 非 macOS 或没有 caffeinate")
    sys.exit(0)

checks.append(("配置关闭时不启动", council.keep_awake({"keep_awake": {"enabled": False}}) is None))

# 子进程模拟一次 run：调用 keep_awake 后把 caffeinate 的 pid 告诉父进程，再停一会儿退出
child = subprocess.Popen(
    [sys.executable, "-c",
     "import sys, time; sys.path.insert(0, sys.argv[1]); import council; "
     "p = council.keep_awake({}); print(p.pid, flush=True); time.sleep(3)",
     str(ROOT / "scripts")],
    stdout=subprocess.PIPE, text=True)
caf_pid = int(child.stdout.readline())
time.sleep(0.5)
assertions = subprocess.run(["pmset", "-g", "assertions"], capture_output=True, text=True).stdout
checks.append(("运行中持有阻止空闲睡眠的断言", any(f"pid {caf_pid}(caffeinate)" in ln and "PreventUserIdleSystemSleep" in ln
                                       for ln in assertions.splitlines())))
args = subprocess.run(["ps", "-o", "args=", "-p", str(caf_pid)], capture_output=True, text=True).stdout
checks.append(("盯住的是调用进程", f"-w {child.pid}" in args))
child.wait()
for _ in range(20):  # caffeinate -w 在被盯进程退出后很快退出
    if subprocess.run(["kill", "-0", str(caf_pid)], capture_output=True).returncode != 0:
        break
    time.sleep(0.25)
checks.append(("调用进程退出后自动解除", subprocess.run(["kill", "-0", str(caf_pid)], capture_output=True).returncode != 0))

ok = True
for name, passed in checks:
    ok &= passed
    print(("PASS" if passed else "FAIL"), name)
sys.exit(0 if ok else 1)
