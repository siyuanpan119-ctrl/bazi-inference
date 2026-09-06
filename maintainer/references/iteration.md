# 做题、核对与规则迭代

仅供本仓库维护者在收到命例答案、评估候选改动和发布新版本时使用。普通使用者安装 `skills/bazi-inference` 后直接进行算命、问答或年度报告，无须加载本目录，也无须提供考题或答案。维护者由 AI 在私有工作目录生成运行记录；公开仓库仅保存通用方法、代码及合成测试。

## 先固定解释，再看答案

1. 为整套题分配稳定 `batch_id`，每个人分配跨批次稳定的 `person_id`，每题分配 `question_id`。同一人改名、改题号、换一套题，仍是同一人。同一人的所有题放在同一个数据分区，不能随机拆成训练题和测试题。
2. 校验出生资料和排盘，保留未决时柱。每个选项拆成人物、事项、年份、细节等原子命题。先用统一的传统分析流程比较全部选项，再记录首选、备选及反证；不用公布后的答案倒选规则。
3. 每题保存 `event-audit-1.0` 记录。算得出的干支关系标为 `computed_relation`；从关系到人生解释的环节标为 `traditional_hypothesis`，写明所用规则和条件。一般关系可以支持方向性假设，不能自动成为具体人生事实。
4. 整套预测用 `trial` 一次注册。把输出 hash 发给用户，连同首选答案一并提交，之后才接收答案。`receipt` 记录这条真实外部消息或提交的引用。
5. 答案放在独立 JSON 文件，用 `reveal` 评分；错误、弃答、低把握题均不从原定分母删除。已知答案、题干已披露答案的题不算盲测。
6. `review` 产生候选规则，记录支持、反例、适用范围及具体改动。规则默认 `proposed`，不因能解释一个旧答案而自动生效。

不能靠这些检查恢复遗失的旧预测。旧题已有答案但没有原预测时，保留“无法计算原命中率”；重做结果只能用作 `hindsight_review`。

## 命题和证据格式

`maintainer/scripts/event_rules.py` 提供 `RULE_DECLARATION` 与 `SCHEMA_VERSION`。导入常量组装记录，避免重复手写术语。最小字段：

```json
{
  "schema_version": "event-audit-1.0",
  "question_id": "batch-unique-question",
  "mode": "blind",
  "seen_answers": false,
  "terminology": "由 AI 填入 RULE_DECLARATION 对象，不能用这段字符串",
  "assumptions": ["时间、地点、换日及已知资料口径"],
  "applied_rule_ids": ["all-candidate-years-comparison"],
  "candidates": [
    {"id": "A", "atoms": [{"id": "A.event", "subject": "命主", "domain": "career", "action": "change_job", "year": null, "detail": null}]},
    {"id": "B", "atoms": [{"id": "B.event", "subject": "命主", "domain": "career", "action": "remain_in_job", "year": null, "detail": null}]}
  ],
  "evidence": [],
  "selection": {"primary": "A", "backup": "B", "status": "forced_guess", "rationale": "填写对比理由和未被区分的部分"}
}
```

这是一份字段说明，不是默认选择 A 的指令。AI 根据实际题目建立记录；`maintainer/scripts/test_event_rules.py` 中的 `example_record()` 是可直接运行的完全合成示例。

证据字段：

| 类型 | 必填证据属性 | 用途 |
|---|---|---|
| `computed_relation` | `id`、`source_group`、`statement`、`direction:"context"`、`target_atoms:[]` | 记录计算得到的形式关系 |
| `traditional_hypothesis` | `id`、`statement`、`direction`、`target_atoms`、`basis_ids`、`warrant`、`validation_status:"unvalidated"` | 明确从什么关系、在什么前提下提出什么解释 |
| `prompt_fact` | `id`、`source_group`、`statement`、`direction`、`target_atoms`、`prompt_excerpt`、`source_role:"question_stem"` | 用户题干已经明示的事实；选项或答案键不算题干事实 |

同一冲关系分别叫“夫妻宫受冲”“日支冲”“根气受动”，仍须归入同一个 `source_group`。支持证据的条数不是独立证据数，更不是概率。没有支持不等于存在反证。

`selection.status` 用 `forced_guess`、`abstain` 或 `stated_in_prompt`。`forced_guess` 表示对未确证的选项提交首选，保留传统推理功能；不是禁止回答。`abstain` 的 `primary` 必须为 `null`。不要把不能区分某个病名扩展为拒绝整个年度报告。

`mode:"hindsight_review"` 允许复盘已知案例，但其原子解释仍与答案键分离。复盘新增规则标记 `origin:"hindsight_review"`，且不得覆盖旧记录。

## 可执行流程

以下命令从 GitHub 仓库根目录运行。`PRIVATE_DIR` 是当前用户的私有工作目录；由 AI 选用实际路径，不要将它放进公开仓库。默认保留一份长期注册表，而非每次新建注册表绕过重复检查。

```bash
python maintainer/scripts/iteration.py record --input "$PRIVATE_DIR/record.json" --out "$PRIVATE_DIR/record-frozen.json"
python maintainer/scripts/iteration.py trial --input "$PRIVATE_DIR/batch.json" --rules "$PRIVATE_DIR/rules-next.json" --registry "$PRIVATE_DIR/registry" --out "$PRIVATE_DIR/submission.json"
python maintainer/scripts/iteration.py receipt --registry "$PRIVATE_DIR/registry" --batch-id batch-001 --reference '实际已发送 hash 的对话消息或提交引用'
python maintainer/scripts/iteration.py reveal --frozen "$PRIVATE_DIR/submission.json" --answers "$PRIVATE_DIR/answers.json" --registry "$PRIVATE_DIR/registry" --out "$PRIVATE_DIR/score.json"
python maintainer/scripts/iteration.py review --input "$PRIVATE_DIR/rule-review.json" --out "$PRIVATE_DIR/proposed-rule.json"
```

单题 `record` 只是原子分析留档；整套正式评分以 `trial` 首次注册的快照为准。`batch.json` 格式：

```json
{
  "batch_id": "batch-001",
  "expected_question_ids": ["q1", "q2"],
  "question_persons": {"q1": "person-a", "q2": "person-a"},
  "records": ["由 AI 放入两份完整事件记录对象"],
  "evaluation_plan": null
}
```

`answers.json` 仅为 `{"q1":"B","q2":"A"}`。加载器拒绝重复 JSON 键、重复题号、缺题、额外题和无效答案。`rules-next.json` 保存完整规则快照，顶层含 `version` 和 `rules`；默认规则来自 `maintainer/assets/rule-registry.json`，每次规则内容修改应更新版本。

按 `batch_id` 的注册文件通过排他原子创建写入。同一注册表中，另换输出文件也不能第二次提交同一批次；同一批次只接受一次答案注册。若导出失败但注册已成功，取回注册文件，不重跑预测或删掉注册记录。

本地注册表可被其所有者删除或篡改，也不能检测脑中已知答案，因此它不是可信第三方。外部事前 hash 承诺仍必要，不能靠另换注册表或 batch_id 挑选高分版本。一个 hash 只证明内容一致，不证明内容在何时生成、是否看过答案。

## 复盘生成规则卡

`review` 接受以下字段并产生一份新卡：

- `id`、`title`、`source_ids`：稳定规则标识、名称及典籍/研究来源标识。
- `prerequisites`、`structure_chain`：前提和逐步结构关系。
- `observable_claims`：可以在给答案后明确核对的命题，避免“运势有变化”等无法失败的描述。
- `alternative_explanations`：同样结构还可能支持哪些不同事件。
- `support`、`counterexamples`：支持案例和反例，空列表表示尚未收集；私有版本可存匿名案例引用。
- `scope`：至少包含 `domains`，另列条件和排除项。
- `origin`：`hindsight_review`、`traditional_source` 或 `prospective_design`。

`review` 始终输出 `status:"proposed"`。传统工作规则使用 `experimental` 与 `evidence_status:"traditional_unvalidated"`，只是可试用的传统解释，不表示已验证。已证明无法单独区分事件的简化规则用 `retired`，其原来的形式关系仍可作为完整分析的一个因素。

更新时一次只改可解释的有限机制，例如补足“财生官但有无日主承载”的前提，或移除“见日支冲直接锁定离婚”的单因素决策。不要每错一题就新增一条只能匹配该生日的例外。

## 何时允许规则升级

可先自由试用和复盘，但若要声称新样本支持某条改进，须在 `trial` 前把该 `proposed` 卡加入新版本规则快照，并声明 `evaluation_plan`：

```json
{
  "schema_version": "evaluation-plan-1.0",
  "rule_id": "要检验的 proposed 规则 id",
  "candidate_sha256": "该规则对象按 benchmark.digest 算出的 64 位摘要",
  "scope": {"domains": ["marriage"], "conditions": [], "exclusions": []},
  "min_new_persons": 20,
  "min_questions": 20,
  "min_accuracy_full": 0.5,
  "min_coverage": 1.0,
  "training_person_ids": ["过去看过答案或用于改规则的人物 id"],
  "person_provenance": {"每位测试人物 id": "new_person_no_answers_seen"},
  "claim": "prospective_support_in_scope"
}
```

上面的门槛数字仅示意格式，不是推荐样本量或经校准的成功标准。AI 根据要验证的具体主张和样本计划事前声明门槛；看完分数不能下调门槛。`scope` 必须与被测卡完全一致。每份事件记录的 `applied_rule_ids` 都要包含被测规则 id，不能把未使用的规则也算成获支持。

对于旧人物，`person_provenance` 应为 `training_or_answer_seen`，记录须为 hindsight；这些资料不能用来升级。别名能否映射为同一人物须由 AI 检查，软件不能从匿名 id 自动识别人。

核实实际外部提交的 hash 早于答案公开后，再执行：

```bash
python maintainer/scripts/iteration.py promote --candidate "$PRIVATE_DIR/proposed-rule.json" --frozen "$PRIVATE_DIR/submission.json" --score "$PRIVATE_DIR/score.json" --registry "$PRIVATE_DIR/registry" --external-receipt-verified --out "$PRIVATE_DIR/experimental-rule.json"
```

`--external-receipt-verified` 表示调用者确实检查过外部消息或提交，不是为了让命令成功而添加的开关。程序同时校验快照、规则 hash、候选状态、预声明门槛、全新人物、答案未披露及全分母成绩。

通过后仅升级为 `experimental` + `prospective_trial_supported`，保留样本范围和原评分。没有 `universally_validated:true`，也不自动改权重。测试中的“全部通过”只验证软件约束，合成测试不能作为命理准确率样本。

## 如何判断准确率是否真的提高

同时记录宿主AI的提供商、模型版本、推理设置和输入上下文版本。比较技能版本时尽量固定这些条件；若模型或提示方式也改变，结果只能评价整体配置，不能把差异都归因于技能规则。

展示总题数、排除及原因、全分母正确率、答题覆盖率、已回答正确率和逐人物结果。新题更容易、选项更少、只回答有把握的题、挑选最佳批次，都会造成假提升。

比较版本时，在答案未知的同一批新人物上事前固定旧版与新版，两份提交用共同实验标识、不同版本批次 id 同时作外部 hash 承诺，并预先写好配对比较方法。两版各自只允许一次提交；答案揭晓后保持同一题目集合和分母。报告人物间波动，不能把同一人物的五道题当作五个独立人物。当前脚本提供单批次评分、配对描述性比较及规则试用门槛，不自动给出统计显著性或“新版优于旧版”的认证。

所有真人出生时间、家人病史、婚姻、犯罪指控、原题、答案和私有提交记录留在私有工作区。要发布规则更新，只发布去除个人信息后的通用改动、合成回归测试及经核对的汇总结论。

已注册的旧版、新版可直接生成配对报告：

```bash
python maintainer/scripts/compare_versions.py --old-frozen "$PRIVATE_DIR/old-submission.json" --old-score "$PRIVATE_DIR/old-score.json" --new-frozen "$PRIVATE_DIR/new-submission.json" --new-score "$PRIVATE_DIR/new-score.json" --registry "$PRIVATE_DIR/registry" --out "$PRIVATE_DIR/comparison.json"
```

程序要求两版题号、人物、候选原子命题、答案、选项数及盲测资格完全一致，输出全分母正确率差、覆盖率差、`n01`（旧错/弃答、新对）、`n10`（旧对、新错/弃答）和逐人物变化。两份冻结 `evaluation_plan` 可添加同一 `experiment_id`；只有双方同时保留全新人物声明、训练人物排除、全盲资格且实际双份外部提交已核查时，才添加 `--external-receipts-checked`。这个标志不能补造缺失的事前实验计划。

缺少任何一项时报告明确为 `nonprospective_descriptive`，只能作描述性比较；两边同样的 hindsight 题另列，不进入盲测分母。即使记录满足前瞻设计，程序仍不计算显著性、不宣布已经提升。API 为 `compare_versions(old_frozen, old_score, new_frozen, new_score, registry_dir, external_receipts_checked=False)`（最后参数仅接受关键字）。

## API 与验证

- `event_rules.audit_record(record)`：原子事实、同源证据和可辨别性审计。
- `benchmark.freeze_batch(..., registry_dir=..., rule_snapshot=...)`：冻结完整规则与完整题集，返回 SHA256。
- `benchmark.score_batch(..., registry_dir=...)`：另存一次揭晓评分。
- `benchmark.validate_person_split(question_persons, question_partitions)`：拒绝同人跨分区。
- `iteration.propose_rule(request)`：候选卡。
- `iteration.trial(request, rules, destination, registry_dir)`：冻结可选评估计划。
- `iteration.promote_rule(...)`：校验门槛并返回有限范围的实验规则卡。

```bash
python maintainer/run_checks.py
```
