# plan-council

**让几个便宜的模型合出一份开发计划——分歧留给你来拍板。**

plan-council 是一个给编码 agent 用的技能（外加一个不依赖第三方库的 Python 命令行工具），Claude Code、Codex、pi、Kimi 以及其他能读 `SKILL.md` 技能的 agent 都能用。它让一个模型起草开发计划，其他模型从不同角度评审，模型引用的每一处 `文件:行号` 都由脚本对照你的代码核验；模型之间不投票表决，报告把没定论的问题交给你。

[English](README.md)

## 为什么这样设计

设计来自对真实生产代码库里历史任务的回放：用当时的代码快照让模型出计划，再拿真正上线的修复（以及后来代码评审发现的问题）给计划打分。

- **把几份草案合成一份，计划反而变差。**「三份草案 → 评审 → 综合」的流程最终 11.5/15 分，单份草案却有 13–15 分：综合把写准的代码位置概括掉了，一条评审还说服综合者否掉了正确的少数意见。所以默认流程从不改写草案，评审只做加法。
- **想推翻什么，必须拿出证据。** 每条评审意见标成「反驳 / 顾虑 / 补充」。反驳必须附可核验的反例（`文件:行号`，或一条命令及其结果），没有就降级为顾虑，计划原来的论断保留。
- **查缺陷要有运行证据，光看代码不够。** 缺陷模式下，起草者先写一张假设表（至少 3 个跨层面的假设；只有矛盾证据才能判「不成立」，缺证据就标「待查」），你可以附上日志、数据库记录或复现步骤。证据能指向现场时，一份便宜模型的草案就能找到根因；证据不到位时，所有方案都猜错了。
- **不同模型抓到的问题不同。** 缺陷模式让两个诊断评审并行（GPT 6 Luna 和 GLM，都开最高思考档），因为同一份草案、同一套指令下，它们抓到的问题几乎不重合。

## 目前的结果（样本很小，当作个例看，不是基准测试）

- **两个回放任务**，按真实提交和后续评审修复定的评分表打分：默认流程 **38/40**；最好的单个便宜模型 37/40；单个便宜模型平均约 34/40；前沿模型（Claude Opus）39/40。打分者也写了前沿模型那份对照计划，所以 39 应看作上限。
- **三个描述很粗的缺陷回放**（只有一句现象，加上当时能拿到的证据）：便宜模型的草案每次都找到了根因（17/20、18.5/20、21/21）。评审补上了草案漏掉的东西——修好后仍存在的竞态、把「请求失败」和「服务端部分降级」分开显示、另一个同样有毛病的函数。有一次，一条评审言之凿凿地「反驳」了正确的根因：引用的代码位置真实存在却不支撑结论，所附的命令输出是编的。所以现在凡是反驳草案已判「成立」的假设，都单列在报告最前面的「先核实」小节。

## 工作方式

| 模式 | 步骤 | 模型调用 | 常见耗时 |
|---|---|---|---|
| `light`（默认），改动任务 | DeepSeek 起草 → GPT 6 Luna 看约束与范围，Muse 看可验证性 | 3 次 | 10–30 分钟 |
| `light`（默认），缺陷任务 | DeepSeek 先写根因再写计划 → GPT 6 Luna 与 GLM 并行诊断，Muse 看可验证性 | 4 次 | 20–40 分钟 |
| `full`（实验） | 摸底 → 三份草案 → 评审 → 综合 → 事前验尸 → 修订 | 约 11 次 | 更久 |

一次运行产出：

- `report.md`：评审意见按「先核实 / 反驳 / 顾虑 / 补充」分组；两份诊断评审的假设复核并排对照，结论不同的标「分歧」；引用核验摘要；每次模型调用的耗时与尝试次数
- `plan.md`：草案，核验不过的引用就地标注
- `critiques/*.md`、`raw/`（每一步的完整命令与输出）、`sandbox.sb`

## 安全与可靠性

- **读权限沙箱（macOS `sandbox-exec`）。** 模型只能读运行目录里你仓库的快照——读不到正在用的工作区（没有 `.env`）、其他运行目录，也读不到各编码 agent 的会话记录。（有一次回放发现，原修复者那个 agent 的会话记录在主目录下读得到；这些目录现在默认禁读。）沙箱起不来时（比如身处另一个 agent 的严格沙箱里），运行会立即停下并说明原因。
- **按失败类型重试。** 限流、过载、接口报错、流式中断、空响应：等一会儿，把同一提示原样发给同一模型；输出格式不对：带反馈重写一次；额度用尽：直接失败。
- **思考档位检查。** 配了模型不支持的思考档位时，pi 会悄悄换成最近的档；`plan-council doctor` 和每次 `run` 都会指出。
- **运行期间不让 Mac 休眠**（`caffeinate`，运行结束自动解除；合盖仍会睡眠）。
- **可续跑。** `--resume <运行目录>` 复用已完成的步骤。

## 环境要求

- **Python 3.9+**，只用标准库。
- **[pi](https://github.com/earendil-works/pi) 编码 agent 命令行**（`npm i -g @earendil-works/pi-coding-agent`），并配好模型。默认 `council.json` 通过 pi 的 opencode-go 渠道用四个模型：DeepSeek V4.1 Flash、GPT 6 Luna、GLM-5.3-Flash、Muse Spark 1.3 Contributor。换成任何 pi 能调用的模型都行：改 `council.json`，再跑 `plan-council doctor`。
- **macOS** 才有读权限沙箱，其他系统照常运行但没有这层隔离。
- 提示词、角色卡和报告都是**中文**写的。

## 安装

```bash
git clone https://github.com/hohband/plan-council.git ~/.agents/skills/plan-council

# 让 agent 看到它（示例）
ln -s ~/.agents/skills/plan-council ~/.claude/skills/plan-council      # Claude Code
ln -s ~/.agents/skills/plan-council ~/.pi/agent/skills/plan-council    # pi

# 把命令放进 PATH
ln -s ~/.agents/skills/plan-council/bin/plan-council ~/.local/bin/plan-council

plan-council doctor   # 每个模型读出 AGENTS.md / README.md 第一行，并核对思考档位
```

## 使用

直接让 agent 用（「用 plan-council 出个计划」），或在仓库里自己运行：

```bash
plan-council run --brief task.md
plan-council run --brief bug.md --kind bug --evidence app.log --evidence repro.md
```

- 好的简报写清：要解决的问题、已知线索、验收标准、边界（不要做什么）。仓库里有任务卡就直接用任务卡。
- 一次运行 10–40 分钟。会限制命令时长的 agent 可以后台运行，再轮询 `report.md`：
  `nohup plan-council run --brief task.md --out runs/t1 > runs/t1.log 2>&1 < /dev/null &`
- `--rev <commit>` 从某次提交建快照，用来回放历史任务。回放时别把答案（之后的提交、原任务卡、你的评分表）放进运行目录或它的上一级，或者把这些路径加进 `sandbox.deny_read`。

然后读 `report.md`。改计划之前，每条反驳都要亲自复现反例——脚本只核验引用的位置存在，不核验它是否支撑结论。

## 配置（`council.json`）

- `models`：每个模型定义一次：命令行、模型名、思考档位。
- `light`：默认流程的起草者和评审视角。一个视角可以列多个模型（`[{"use": "gpt6luna", "thinking": "max"}, {"use": "glm", "thinking": "max"}]`），用同一提示并行跑。
- `roles`：实验性的 `full` 流程。
- `rate_limit.waits`、`timeouts`、`sandbox`（`deny_read`、`deny_agent_sessions`）、`keep_awake`。

## 测试

```bash
for t in tests/*.py; do python3 "$t" || echo "FAILED: $t"; done   # 不调用模型
```

## 许可证

[MIT](LICENSE)
