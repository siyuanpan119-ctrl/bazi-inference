# 下一轮最小执行协议：冻结旧版与本次修订版

目前为 `awaiting_questions`；[机器可读计划](../assets/next-trial.json)没有正式题、答案、运行目录、内容哈希或成绩。用户下一步只需交新题，保留题干、出生资料、观察年份及**全部原选项**，先不交答案。普通作答 agent 不需要跑实验脚本，以下由维护者组织。

仅比较 0.4.1 与 0.4.2 的一个组合包 `symmetric-candidate-review-and-input-precision`（对称候选审查＋输入时间精度），不得把组合结果归因到其中一条规则。每版一次，不挑最好重复。默认不启用无盘臂；如要启用，必须在任何作答前另行冻结设计，并使用 [controlled-trial](controlled-trial.md) 的隔离要求，不能看完结果再加基线。

## 新题到达后

1. 创建全新私有 `run_root`，答案保管位置在该根及作答环境之外。旧版从已保存 Git 对象 `8621f4623580184822ef1c6cc26d543687332eae` 导出（公开对应基线 `bb3631c2e2fe5019e618a256620caa28b06df30d`），不得复制当前修订工作树冒充旧版；新版在修订完成后导出。分别放 `snapshots/old`、`snapshots/new`；两臂输出分别放 `outputs/old`、`outputs/new`，不能嵌入技能快照或混为同一目录。现在不建运行目录。
2. 保存原始题面并单独记哈希；无答案的 `inputs/questions.json` 为对象，`questions` 列表中的每题含 `question_id`、稳定 `person_id`、`stem`、`observation_year`、原始选项字典 `options` 和实际出生资料。缺失年份用 `null` 并说明限制，不补造。人工核对原文与转录没有遗漏阴性条件或复合事实。已知答案的旧人物登记到 `development_person_ids`，只作开发；本配对批次只收未见答案的新人物，同一人物不得跨数据分区。
3. 两臂逐字共享题面、年份、全部选项和基础资料；共同候选/原子结构也在作答前固定，仅转录题意，不先判断选项真假。每个 `candidate.text` 保存该选项全文。把本组合包说明保存为 `policy/change-package.md`，不同时调整其他规则。使用 `trial_preflight.file_manifest` / `skill_manifest` 计算实际输入与完整技能哈希，以 `benchmark.create_new` 在新 `prepared.json` 中不可覆盖地保存计划、清单及哈希；每臂声明填真实 `input_sha256`、`skill_sha256`。
4. 真实模型、revision、推理设置、输出预算和 sampling 逐项照实记录，不可见就保持 `unknown`。两臂尽量保持可控设置相同；未知或不同设置允许继续描述性配对评分，但不能宣称隔离了技能效果，不要求用户解决服务不公开的版本信息。
5. 各臂在独立、无历史答案、无其他臂回答的上下文中，只加载对应技能快照和相同题面。管理员清单、旧题答案、答案键、另一臂记录不得交给作答 agent；不联网查人或题。自然语言泄漏需人工检查；程序只能拒绝常见答案字段，无法认证模型预训练未见过公开题。

## 揭晓前

沿用 `event_rules` / `benchmark` 的完整记录格式，每题增存 `original_stem`、`observation_year`，每候选增存 `text`。`selection` 必须显式含 `primary`、`backup`、`status`、`unresolved`、`rationale`；无首选/备选用 `null`，未决用布尔值，强猜沿用 `forced_guess`，弃答沿用 `abstain`。未决题可以有强猜首选，两类不是互斥分区。备选不能与首选相同。证据和七项 `trace` 写真实理由；不能为了通过检查补造区分依据。

两臂均完成后，将计划复制到实际 run 根，填真实题目映射、文件路径、人物名单及宿主声明，状态改为 `predictions_frozen`。`TRIAL_ROOT` 是维护者本次实际创建的私有根，不是本仓库：

```bash
python maintainer/scripts/trial_preflight.py --root "$TRIAL_ROOT" --plan plan.json --output "$TRIAL_ROOT/preflight-check.json"
```

配对入口仅在 `paired-version-preflight-1.0` 下启用，历史三臂接口不变。它检查原题/年份/原选项、备选/未决冻结、独立输出路径、输入与技能内容身份。宿主未知返回 `descriptive_ready`，不阻塞原始评分；结构缺项返回 `process_incomplete`，不能删题过关或揭晓后补写旧依据。先核对实际输入/技能与 `prepared.json` 未变。

在两份 `benchmark` 输入的 `evaluation_plan` 冻结同一个真实 `experiment_id`、输入/技能哈希、真实新人物来源、开发人物排除声明和 `preflight_comparable_protocol_declared`（照抄预检布尔值，不能把 false 改为 true）。元数据补齐后重做一次预检到新文件 `preflight.json`（不覆盖检查稿）；此后不再改输入、计划、技能或答卷。依 [iteration](iteration.md) 的完整输入封装使用已有冻结器，两个 batch ID 不同、共用一个保留的私有 registry：

```bash
python maintainer/scripts/trial_preflight.py --root "$TRIAL_ROOT" --plan plan.json --output "$TRIAL_ROOT/preflight.json"
python maintainer/scripts/benchmark.py freeze --input "$TRIAL_ROOT/outputs/old/submission.json" --rules "$TRIAL_ROOT/policy/old-rules.json" --registry "$TRIAL_ROOT/registry" --out "$TRIAL_ROOT/outputs/old/frozen.json"
python maintainer/scripts/benchmark.py freeze --input "$TRIAL_ROOT/outputs/new/submission.json" --rules "$TRIAL_ROOT/policy/new-rules.json" --registry "$TRIAL_ROOT/registry" --out "$TRIAL_ROOT/outputs/new/frozen.json"
```

规则快照沿用实际维护规则格式（含匹配 `version`），不能以规则卡哈希替代完整技能哈希。两臂全部注册后，才向用户交付逐题首选/备选/未决/强猜表及冻结哈希，仍不收答案。存在真实外部提交记录时按既有 `register_receipt` 登记；没有就保留缺失，不虚构地址。本地哈希不认证外部时间。

## 揭晓后

维护者先确认两臂注册齐全，再接收完整答案键；单臂评分器本身不执行此跨臂闸门。用 `benchmark.py score` 分别生成 `outputs/old/score.json`、`outputs/new/score.json`，随后运行：

```bash
python maintainer/scripts/compare_versions.py --old-frozen "$TRIAL_ROOT/outputs/old/frozen.json" --old-score "$TRIAL_ROOT/outputs/old/score.json" --new-frozen "$TRIAL_ROOT/outputs/new/frozen.json" --new-score "$TRIAL_ROOT/outputs/new/score.json" --registry "$TRIAL_ROOT/registry" --out "$TRIAL_ROOT/comparison.json"
```

主成绩为首选正确数 / **整批全部题数**；弃答留在分母，备选不补分子。报告覆盖率、已答正确率、按命例的题数/正确数/变化、旧错新对与旧对新错，以及未决/强猜/弃答分组（`by_decision_status_eligible` 可重叠）。同一人的多题不是多个独立命例。泄漏题不能悄悄删除：报告全部原始题数、排除数与独立的开发描述成绩，不计入前瞻提升。

哈希、软件测试、旧题回放及单批正差都不验证真实预测准确率。宿主未知、外部时序未核验或样本不足时，明确写描述性结果与限制；不宣称显著、普适提升或单条规则因果贡献。当前没有正式成绩，必须待新题、完整冻结、再揭晓后才能评分。
