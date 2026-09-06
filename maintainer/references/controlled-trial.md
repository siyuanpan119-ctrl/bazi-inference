# 维护者：四种方法与扰动对照（v0.4.0）

普通使用者仍只需出生时间、性别、出生地和问题。本文件及 `scripts/controlled_trial.py` 只用于维护者比较方法；脚本复用现有 `benchmark.py` 的哈希、不可覆盖注册、完整分母及按人拆分工具，不替代模型推理、排盘或已存在的历史评分。

本轮已公布答案的全部命例只能标为 `known_development`，放入 `training`。回放不计入未知答案测试；更换题号、生日、选项顺序或打开一个新对话，不会自动产生新人物或新标签。命盘扰动使用原来真实/合成记录的命盘与原始选项，仅作输入依赖诊断；绝不能把“新生日＋旧答案”包装为新的训练命例。

## 冻结的实验

`prepare` 一次生成并注册以下四臂，每臂运行 `original`、`shuffled_charts`、`shuffled_options` 三个条件。重复次数、随机种子、方法文件、融合策略和宿主设置在揭晓答案前固定。共有 `4 × 3 × repetitions` 个运行，不能揭晓后只选择表现最好的重复。

| 方法 | 模型可见内容 | 检验目的 |
|---|---|---|
| `stem_only` | 脱敏题干、选项；没有出生资料及命盘 | 常识、措辞、选项信息能回答多少 |
| `bazi` | 同样题干、选项及八字计算结果 | 八字的附加信息 |
| `ziwei` | 同样题干、选项及紫微计算结果 | 紫微的附加信息 |
| `fusion` | 同样题干、选项及两套计算结果 | 固定融合策略的附加效果 |

维护者在独立上下文执行各臂；无盘臂不加载命理 Skill，也不能由人物身份、题干里的生日或网络检索恢复命盘。融合臂依 Skill 先形成各自候选再执行已冻结融合规则，不先读取其他臂答卷。为了保留真正无盘对照，维护者需从题干中去掉出生日期、命盘、人物姓名等身份线索；脚本要求 `stem_has_no_birth_or_chart: true` 的诚实声明，不能自动理解文本是否仍泄漏。选项包含的现实信息在所有臂保留一致。

`shuffled_charts` 在同一数据分区内以人为单位循环交换命盘，保证每人都拿到别人的盘，同一人的所有题使用同一个供盘人。每个分区至少两人；不跨开发/测试交换。`shuffled_options` 改变每个选项展示字母，并保存展示字母到原始语义 ID 的映射，评分时还原；原始题意和答案语义不改变。四臂使用相同扰动映射。可见 JSON 及文件名只含不透明 `view_id`，不暴露是原盘、换盘或选项扰动；管理员的 `run_id` 与映射只留在私有清单。命盘载荷仍需去掉人物姓名等无关身份标记。

宿主 `model_id`、`model_version`、`reasoning_effort`、`instructions_version`、输出预算和采样设置全组一致。不知道真实模型修订号时，不能为了通过检查编造字符串；已有原始回答仍可使用旧版描述性评分工具，但不作为该四臂严格对照。这里控制的是声明及文件一致性，程序不能证明外部服务真实执行了所声明的模型或采样配置。

## 输入及私有目录

`prepare` 输入无答案对象：

```json
{
  "schema_version": "controlled-trial-1.0",
  "trial_id": "private-prospective-001",
  "skill_root": "snapshots/v040",
  "fusion_policy_file": "policy/fusion.md",
  "seed": 41,
  "repetitions": 2,
  "scoring_policy": {
    "all_repetitions": true,
    "retain_all_questions": true,
    "primary_only": true,
    "report_coverage": true
  },
  "context_policy": "isolated_no_keys_no_other_arms",
  "host": {
    "model_id": "ACTUAL_MODEL_ID",
    "model_version": "ACTUAL_MODEL_REVISION",
    "reasoning_effort": "ACTUAL_SETTING",
    "instructions_version": "ACTUAL_HOST_REVISION",
    "max_output_tokens": 12000,
    "sampling": {"temperature": 0}
  },
  "known_development_person_ids": ["previous-person-stable-id"],
  "person_provenance": {
    "heldout-person-01": "unseen_declared",
    "heldout-person-02": "unseen_declared"
  },
  "questions": [
    {
      "id": "q01", "person_id": "heldout-person-01", "partition": "test",
      "stem": "实际已去掉生日和身份信息的问题",
      "stem_has_no_birth_or_chart": true,
      "options": {"option-one": "实际选项一全文", "option-two": "实际选项二全文"}
    },
    {
      "id": "q02", "person_id": "heldout-person-02", "partition": "test",
      "stem": "另一命主的实际问题",
      "stem_has_no_birth_or_chart": true,
      "options": {"option-one": "实际选项一全文", "option-two": "实际选项二全文"}
    }
  ],
  "charts": {
    "heldout-person-01": {"bazi": {"实际计算字段": "实际结果"}, "ziwei": {"实际计算字段": "实际结果"}},
    "heldout-person-02": {"bazi": {"实际计算字段": "实际结果"}, "ziwei": {"实际计算字段": "实际结果"}}
  }
}
```

这只是格式说明，生产运行必须替换示意文本和命盘。题目选项用稳定的**语义 ID**，可以沿用原始 A/B/C/D，但它与扰动后展示的 A/B/C/D 是两套映射。每题可有 2 至 26 个选项；阴性题、复合事实应完整保留原文。真实排盘及事件链审计仍由普通 Skill 和既有 `event_rules.py` 负责，四臂构建器不会把有字典字段当成“算出了可靠命盘”。

同一人的题不能在 `training`、`validation`、`test` 之间拆开。`known_development_person_ids` 包含先前批次已知命主的稳定 ID；他们不能重贴 `unseen_declared` 标签。`synthetic` 用于软件测试，无论字段分区如何都不会进入未知答案成绩。

维护者的私有根目录应与提供给作答 agent 的目录隔开。`bundle/manifest.json`、输入计划、注册表和答案文件只交给实验管理员；作答 agent 仅得到它对应的 `bundle/views/<view_id>.json`、已冻结且适用于该臂的方法指令。物理隔离、独立上下文和禁止跨臂查看由宿主负责；单个脚本不能隔离同一个人/进程已经记住的答案，也不能排除模型预训练时见过公开题库。

## 可执行命令

所有路径和注册记录放私有目录。计划内技能与策略路径相对 `--root`：

```bash
python maintainer/scripts/controlled_trial.py prepare --input /absolute/private/plan.json --root /absolute/private --out /absolute/private/bundle --registry /absolute/private/registry
```

它对实际完整 Skill 文件清单、融合策略、计划、所有可见视图和展示映射生成哈希，注册同名实验的第一份计划。已注册实验不能换个输出文件重做；导出失败可从注册表恢复原产物，不能重跑挑种子。不要把完整私有清单发给作答 agent。

每个视图生成一次回答，首选使用**该视图展示字母**或 `null`，所有题必须齐全。维护者的提交封装形如：

```json
{
  "host": {"与冻结计划完全一致": "实际宿主设置"},
  "skill_sha256": "manifest.body.skill_snapshot.sha256",
  "view_sha256": "对应可见视图的规范JSON SHA256",
  "records": [
    {"question_id": "q01", "primary": "B", "rationale": "实际判断及最强竞争解释"},
    {"question_id": "q02", "primary": null, "rationale": "两个候选没有可区分依据，保留弃答"}
  ]
}
```

上面两个哈希需填真实计算值：`view_sha256` 使用 `benchmark.digest(view_object)`；不是复制字段名的文字。提交时检测实际技能、融合策略、可见题目是否与注册时相同；哈希只说明文件身份，不证明解释真实有效。

```bash
python maintainer/scripts/controlled_trial.py submit --manifest /absolute/private/bundle/manifest.json --run-id r001/original/bazi --input /absolute/private/submission.json --registry /absolute/private/registry
```

所有 12 × 重复次数运行全部注册后，才允许评分程序读取单独的答案文件。答案文件格式为原始题号到**原始选项语义 ID**：`{"q01":"option-two","q02":"option-one"}`。`prepare` 和 `submit` 均没有答案参数，并拒绝常见答案键字段；自然语言里夹带答案仍需人工检查。

```bash
python maintainer/scripts/controlled_trial.py score --manifest /absolute/private/bundle/manifest.json --answers /absolute/curator-only/keys.json --registry /absolute/private/registry --out /absolute/private/score.json
```

## 看哪些结果

- 每臂每条件每次重复都报告全题命中率、覆盖率、已答正确率；弃答保留在全题分母。
- `all_rows_descriptive` 含开发与合成样本，明确只作描述；`declared_unseen_test` 只包含声明未见答案且为 test 的人物。
- 按人给出成绩和人物平均正确率。同一人的五题属于一个人物簇；重复两轮仍是原来的人数，不能声称样本翻倍。
- `comparisons_descriptive_all_rows` 保存融合相对三个单臂/基线的改对、改错、净变化及按人变化，也保存扰动相对原始条件的正确性变化和语义选择变化。它含全部数据，不能拿已知旧题的数字当未见答案增益；`comparisons_declared_unseen_test` 单列声明未见答案测试的相同对照。
- `all_predeclared_repetitions` 与 `declared_unseen_test_all_repetitions` 使用预先固定的全部重复，报告平均全题命中率、覆盖率及人物平均正确率，不输出 best-of 主成绩。
- 合参只有在独立新人物上相对最佳单系统持续净增益时，才值得调整默认策略。与无盘相比没有增益，或换错命盘仍同样准确，都是需要调查的反例。输入依赖检测也不能单独证明命理因果。

程序始终保留 `prediction_accuracy_validated: false`、外部独立性未认证和未做显著性检验标记。样本很少或题库公开时，单批百分比只能描述那批，不代表普通用户年度报告的准确率。哈希应在揭晓前发送到可核验的外部位置；本地注册不能认证外部时间戳。换实验 ID 或删注册目录仍可能绕过“首次提交”，所以保留完整研究记录，不能挑选最终最好的一份报告。

软件验收使用 2 个虚构人物、3 道虚构问题，含 A–D 选项扰动、部分弃答、两次重复及一次 CLI 全流程；它不包含真实出生资料或私人答案，也不宣称命理有效：

```bash
python -m unittest discover -s maintainer/scripts -p test_controlled_trial.py -v
```

旧版 `trial_preflight.py`、`benchmark.py`、`compare_versions.py` 和 `iteration.py` 接口继续保留，历史三臂冻结产物无需迁移或补写。
