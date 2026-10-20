# plan-council

**Several cheaper models, one development plan — with the disagreements left for you to decide.**

plan-council is a skill (plus a small, dependency-free Python CLI) for coding agents such as Claude Code, Codex, pi, Kimi and anything else that reads `SKILL.md` skills. One model drafts a development plan; other models critique it from different angles; every `file:line` the models cite is checked mechanically against your code; and instead of letting models out-vote each other, the report hands the open questions to you.

[中文说明](README.zh-CN.md)

## Why it is built this way

The design came from replaying real tasks from a production codebase and scoring the plans against the fixes that actually shipped (and the bugs later code reviews found in them).

- **Merging drafts made plans worse.** A "three drafts → critics → synthesis" council scored 11.5/15 while the individual drafts scored 13–15: the synthesis summarized away precise locations, and one critic talked it out of a correct minority view. So the default flow never rewrites the draft. Critics only add.
- **Overturning anything requires evidence.** Every finding is tagged *refutation*, *concern* or *addition*. A refutation must carry a counterexample someone can check (`file:line`, or a command and its result). Without one it is downgraded to a concern, and the plan's claim stands.
- **Bugs need runtime evidence, not just code.** In bug mode the drafter first writes a competing-hypotheses table (at least three hypotheses across layers; a hypothesis is "ruled out" only by contradicting evidence, otherwise it stays "to check"), and you can attach logs, database rows or repro notes. When the evidence pointed at the scene, even a single cheap draft found the root cause. When it did not, every plan guessed wrong.
- **Different models catch different bugs.** Bug mode runs two diagnosis critics in parallel (GPT 6 Luna and DeepSeek V4.1 Flash, both at maximum thinking) because, given the same draft and the same prompt, they catch different bugs: DeepSeek finds the most issues without false refutations (fake test doubles, state not persisted after an error), while only Luna has caught the lifecycle and blast-radius bugs (a session match that stops the next turn, a fix that still skips the expiry check, a cleanup that touches every user's records). DeepSeek also drafts; same-model self-review may share blind spots, which is what Luna is there for.

## Results so far (small samples — read as anecdotes, not benchmarks)

- **Two replayed tasks**, scored against a rubric built from the real commits and later review fixes: the default flow scored **38/40**; the best single cheap model 37/40; single cheap models averaged about 34/40; a frontier model (Claude Opus) 39/40. The grader also wrote the frontier baseline, so treat that 39 as an upper bound.
- **Three replays of vaguely described bugs** (a one-line symptom plus whatever evidence existed at the time): the cheap draft found the root cause each time (17/20, 18.5/20 and 21/21). Critics added what the drafts missed — a race that survives the fix, telling "the request failed" apart from "the server is partially degraded", a second function with the same bug. Once, a critic confidently "refuted" a correct root cause with real but irrelevant citations and an invented command output. That is why refutations of hypotheses the draft marked as established now appear first, in a separate **verify first** section.

## How it works

| Mode | Steps | Model calls | Typical time |
|---|---|---|---|
| `light` (default), change task | DeepSeek drafts → GPT 6 Luna checks constraints and scope, Muse checks verifiability | 3 | 10–30 min |
| `light` (default), bug task | DeepSeek drafts root cause + plan → GPT 6 Luna and DeepSeek diagnose in parallel, Muse checks verifiability | 4 | 15–25 min |
| `full` (experimental) | scout → 3 drafts → critics → synthesis → pre-mortem → revision | about 11 | longer |

A run produces:

- `report.md` — findings grouped as *verify first* / refutations / concerns / additions, a side-by-side hypothesis review from both diagnosis critics (disagreements flagged), the reference-check summary and a table of every model call
- `plan.md` — the draft, with unverifiable references annotated inline
- `critiques/*.md`, `raw/` (exact commands and outputs for each step), `sandbox.sb`

## Safety and reliability

- **Read sandbox (macOS `sandbox-exec`).** Models read a snapshot of your repository inside the run directory — not your live checkout (no `.env`), not other runs, and not other coding agents' session logs. (A replay once found that the original fix's agent session log was readable from the home directory; those directories are now blocked by default.) If the sandbox cannot be applied — for example inside another agent's strict sandbox — the run stops immediately and says why.
- **Retries that match the failure.** Rate limits, overloads, API errors, dropped streams and empty replies: wait, then resend the same prompt to the same model. Malformed output: one rewrite with feedback. Exhausted quota: fail fast.
- **Thinking-level check.** pi silently replaces a thinking level a model does not support with the nearest one; `plan-council doctor` and every `run` flag such mismatches.
- **Keeps the Mac awake** during a run (`caffeinate`, released automatically when the run ends; closing the lid still sleeps).
- **Resumable.** `--resume <run dir>` reuses every step that already finished.

## Requirements

- **Python 3.9+** — standard library only.
- **[pi](https://github.com/earendil-works/pi) coding agent CLI** (`npm i -g @earendil-works/pi-coding-agent`) with models configured. The default `council.json` uses four models through pi's opencode-go provider (DeepSeek V4.1 Flash, GPT 6 Luna, GLM-5.3-Flash, Muse Spark 1.3 Contributor) plus MiniMax-M3.1-Flash through pi's minimax-cn provider (defined but not used by default). Use any models pi can reach: edit `council.json`, then run `plan-council doctor`.
- **macOS** for the read sandbox. Elsewhere it runs without that isolation.
- The prompts, role cards and reports are written in **Chinese**. Models handle them fine; translate `roles/` if you want English output.

## Install

```bash
git clone https://github.com/hohband/plan-council.git ~/.agents/skills/plan-council

# make it visible to your agents (examples)
ln -s ~/.agents/skills/plan-council ~/.claude/skills/plan-council      # Claude Code
ln -s ~/.agents/skills/plan-council ~/.pi/agent/skills/plan-council    # pi

# put the command on PATH
ln -s ~/.agents/skills/plan-council/bin/plan-council ~/.local/bin/plan-council

plan-council doctor   # every model reads AGENTS.md / README.md's first line; thinking levels are checked
```

## Use

Ask your agent ("plan this with plan-council"), or run it yourself from inside your repository:

```bash
plan-council run --brief task.md
plan-council run --brief bug.md --kind bug --evidence app.log --evidence repro.md
```

- A good brief states the problem, what is already known, acceptance criteria and boundaries ("what not to do"). If your repo keeps task cards, pass the card.
- Runs can take 10–40 minutes. Agents that cap command time can run it detached and poll for `report.md`:
  `nohup plan-council run --brief task.md --out runs/t1 > runs/t1.log 2>&1 < /dev/null &`
- `--rev <commit>` builds the snapshot from a commit, for replaying history. When replaying, keep the answer (later commits, the original task card, your scoring notes) out of the run directory and its parent, or add those paths to `sandbox.deny_read`.

Then read `report.md`. Reproduce every refutation yourself before changing the plan — the script verifies that a cited location exists, not that it supports the argument.

## Configuration (`council.json`)

- `models` — each model once: CLI, model id, thinking level.
- `light` — drafter and critic lenses for the default flow. A lens may list several models (`[{"use": "gpt6luna", "thinking": "max"}, {"use": "deepseek", "thinking": "max"}]`), which run in parallel with the same prompt.
- `roles` — the experimental `full` pipeline.
- `rate_limit.waits`, `timeouts`, `sandbox` (`deny_read`, `deny_agent_sessions`), `keep_awake`.

## Tests

```bash
for t in tests/*.py; do python3 "$t" || echo "FAILED: $t"; done   # no model calls
```

## License

[MIT](LICENSE)
