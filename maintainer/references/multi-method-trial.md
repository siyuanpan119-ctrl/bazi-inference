# 开发者：验证紫微是否带来增益

本流程仅供维护者验证方法，不是普通算命用户的输入要求。旧答卷保持原样，继续按原始首选计分；不能补写旧证据，让它看起来通过了新检查。

## 事前固定三组

- `v020-bazi`：保存的 0.2.0 八字方法。
- `v030-bazi`：修订后的八字方法，用来分离执行改进的效果。
- `v030-bazi-ziwei`：相同新版八字加独立紫微判断；另存紫微原始首选作诊断。

同一道题、同一观察时点、同一基础资料、同一宿主模型与推理设置。三组在独立上下文作答；紫微先保留自己的判断，再执行事先写定的融合规则，不能先看八字选择再附会。命题人的流派不能代替命盘资料，也不能作为事后挑选术数的理由。

融合文件须提前写明：一致时怎么处理；分歧时采用哪一条固定规则；紫微资料不齐时如何保留八字首选；是否弃答。保持整批不变。未经独立验证，不自行赋予两套规则数值权重，不把一致解释成统计独立的两份证据。

## 保留人物隔离和完整分母

以人物为单位区分开发案例与未见答案的验证案例，同一人的题不能跨两组。开发者或模型已知答案的案例只能作回顾示例；重新换题号并不使它变成新人物。不同方法的题干和候选内容保持一致，避免后一个方法得到更多事实。

预先固定：只比较首选；整批全部题目为分母（40 题批次就保留 40）；报告作答覆盖率；弃答不算正确。分别统计三组的正确数，不能把备选命中补入分子。比较新增正确题和原本正确却被改错的题，并给出净变化；按人物和问题领域展示波动，不把同一人的五题当五个独立样本。

本轮答对率、软件检查通过率、独立性和统计显著性是不同判断。单批的上升只描述该批，不能宣称真实命理准确率已获验证。正确选项也可能源于错误推理，应另审其依据是否有效。

## 对实际文件作预检

`trial_preflight.py`读取计划和真实产物，生成新文件清单；它不替代计算，不判断解释为真，不认证外部时间戳，也不修改既有冻结与评分脚本。

计划最小结构（下面全为合成占位标识，无真实生平）：

```json
{
  "trial_id": "new-unseen-batch",
  "expected_question_count": 40,
  "question_persons": {"q01": "unseen-person-01"},
  "development_person_ids": ["development-person-01"],
  "evaluation_person_ids": ["unseen-person-01"],
  "scoring_policy": {
    "primary_only": true,
    "retain_all_questions": true,
    "report_coverage": true
  },
  "fusion_policy_file": "trial/fusion.md",
  "arms": {
    "v020-bazi": {
      "skill_root": "snapshots/v020",
      "records_file": "trial/v020-records.json",
      "host": {
        "model_id": "ACTUAL_MODEL_ID",
        "model_version": "ACTUAL_MODEL_VERSION",
        "reasoning_effort": "ACTUAL_SETTING",
        "instructions_version": "ACTUAL_HOST_INSTRUCTIONS_REVISION"
      }
    }
  }
}
```

示意仅列一个题目和一组，使用前须填全 40 题映射及三组，路径均相对 `--root`。模型字段填真实已知版本；不知道就填 `unknown`，允许保存原始答案，但预检不会判可比较。若服务不公开模型修订号，明确保留该限制，不伪造版本。宿主指令版本也固定；技能变化由真实文件摘要记录。

每组记录文件可以是列表或含 `records` 的对象。每条需含：

- `question_id`、`seen_answers: false`、实际 `candidates`、`selection.primary`（允许 null 表示弃答）。
- 每个选项的 `atoms` 写实际 `subject`、`domain`、`action`、`year`；无年份的事件用 null。复合选项拆成所有组成事实，否定题保留否定含义。不要写“原题选项A”或“命题所问对象”等占位。
- `evidence` 优先沿用现有 event-audit 结构：原始依据有 `id`、`statement`、`source_group`；传统假设有 `kind: traditional_hypothesis`、`statement`、实际 `basis_ids`、`warrant`。其他现有字段照留，仍可交原事件审计检查关联、去重及循环。简写形式 `id`、`claim`、`source_ref` 也可作本预检输入，但不声称它替代旧事件审计。标明实际计算位置、已知题干事实或传统来源；空证据保留原始猜测计分，但过程不完整。真实短语“命主”“母亲”“结婚”可以通过，明显占位词不能。
- `trace` 逐项写 `natal_premise`、`target`、`luck_context`、`supporting_condition`、`competing_explanation`、`differentiator`、`counter_condition`。若无法区分，明确写“该依据同样支持另一选项，无法区分”，不要补造差别。预检只检查结构和明显占位，不能辨别这句话是否诚实、方法是否正确。
- 组合组额外写 `ziwei_status`（ready/unavailable）与 `ziwei_raw_choice`；不可排盘时必须是 unavailable/null。此时不能把组合回答冒充紫微贡献。

```bash
python maintainer/scripts/trial_preflight.py --root /absolute/trial-root --plan trial/plan.json --output /absolute/trial-root/trial/preflight-before.json
python maintainer/scripts/trial_preflight.py --root /absolute/trial-root --verify /absolute/trial-root/trial/preflight-before.json
```

输出文件必须不存在，不覆盖旧快照。程序对实际技能源文件、计划、融合文件、回答文件计算确定性 SHA-256；技能清单排除缓存、node_modules、git 和已约定的私有目录（registry、answers、predictions、submissions、reviews、reports、local-data、private-data 等）。它不自动识别任意名称下的隐私，维护者仍须将真实生平产物放到技能目录外。明确声明的回答文件单独哈希，用于检测答卷变化，不把它纳入技能内容清单。不使用声明版本代替实际内容。验证会检测之后的内容变化。快照是本地内容身份记录；如需外部事前提交证明，另行保存真实可核验的提交凭据，不能自行填写一个哈希便宣称外部证明。

模型身份、推理设置和 trace 是维护者声明；即使字段齐全，程序也不能证明它们属实。未知设置会标作不可比较，填入看似精确的虚构字符串也不会因此获得真实的外部证明。

`process_incomplete` 不删题、不删答案：原始首选仍可计分，但需将“做了什么”与“按完整流程完成”分开报告。所有真实题目、答案、出生信息及过程记录保留在私有评估位置；公开仓库仅放合成示例、通用方法和汇总结果。
