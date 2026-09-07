# 具体判断的简短底稿

在比较具体事件的完整选项、多个年份或合参改票时使用。先按正常命理流程完成命局与岁运，再保存判断依据；本工具不代替推演，也不要求用户提供答案或填写数据。无候选的普通整体解读无需逐段建立记录。

## 从问题写到记录

合成格式见 `assets/decision-record.example.json`。每个问题一份JSON；八字、紫微分别保存，合参记录引用两份原件。字段只服务实际判断，不为凑齐而补造未知事实。

| 字段 | 填什么 |
|---|---|
| `schema_version` | 固定整数`1` |
| `target` | `subject`主体、`event_stage`事项阶段、`time_scope`实际时间范围 |
| `candidates` | 全部候选，每项的`id`和`claims`；复合叙述拆成最小子事实 |
| `claims[].state` | `known`用户明确给定；`supported`传统解释相容；`unknown`未确定；`contradicted`与已核验事实或声明结构冲突 |
| `claims[].evidence_ids` | 对应实际依据；不能拿“未知”当已不存在 |
| `evidence` | 每项含`id`、`kind`、`scope`、`source_ref`、`statement` |
| `evidence[].kind` | `calculation`可复算事实；`user_fact`已提供生平；`traditional_interpretation`从符号到事件的解释假设 |
| `evidence[].scope` | `background`多个候选共有；`discriminator`声明有区别，但还须人工审查它是否确实区分 |
| `primary`、`strongest_alternative` | 暂定首选及最强竞争解释；不是已知事实 |
| `comparison` | `against`列所有其余候选；`discriminator_ids`、`why_distinguishes`、`counterevidence`及`required_unknowns`分别列区分、反向与未满足前提 |
| `decision_mode` | `conditional`有条件判断；用户要求唯一选项而无法区分时为`forced_choice` |
| `temporal_branches` | 实际分析过的分支`id`及其`primary`，可选`note`记录日期/时辰说明 |
| `expected_temporal_branch_ids` | 计算层发现会影响本题的完整分支清单；用于检查有没有漏掉某段 |
| `fusion` | 两系统各自的`primary`和`record_ref`，另列`override_reason`与`discriminator_ids`；原件保留各自备选和理由 |

这里的`known`只表示用户提供了该事实，不表示我们做过外部核验；`supported`不表示事件已经发生。不要用计算的命盘字段给疾病、财产数量或法律状态盖“已知”标签。依据的引用应指向实际文件与字段，或者明确的传统取法，不写“综合分析”作为来源。

每个候选的子句按完整叙述审查。例：“创业、拥有数套房、净资产达某金额”有三个不同主张，不能只给经营主题就全标支持；未知金额也不能反向证明较小金额选项成立。

## 检查并回到实际判断

```bash
python scripts/decision_record.py --input /absolute/path/judgment.json --output /absolute/path/judgment-check.json
```

格式错误先修正。结果为未决时，回到原始计算与真实前提，查看缺的是哪条区别；有资料可补则补，没有则保留未决。用户要求全答时仍给出一个字母，并保留强制排序状态，不能删掉困难选项或把备用项算作答对。

程序只验证声明的字段、引用关系、候选和分支覆盖，不核实古籍、外部文件内容、自然语言真实性或现实预测效度。把“财动”错误地写成`discriminator`仍可能通过；必须人工再问：它是否也支持另一候选？若是，改为共有背景。结构检查通过不能标“高准确率”。

同理，保存两个`record_ref`不证明宿主真正隔离过上下文。独立执行应先形成原记录，后交给合参步骤；同一上下文顺序完成时如实说明。`fusion.agreement_as_confidence`若为真，表示错误地以同票提升确定性，应撤回这项提升。

## 具体推演的三个裁决要点

1. **先比较阶段，再比较强弱。** 关系机会、共同责任、法律登记各需不同前提；财务活动、取得收入、保留净资产也分开。只出现强烈变化时，先保留主题，不直接决定事件。
2. **只保留不会被时间分支推翻的全期表述。** 公历月跨节、年度跨交运时分别判读；分支给出不同首选，结论就带日期条件。计算锚点不作实际事件日期。
3. **复合叙述按最弱的未证实部分控制精度。** 学习倾向与已完成学历、社交能力与社交意愿、职业方式与具体行业分别讲；不能把相容叙述累加成一个已确定的人生故事。

以上提高的是可检查性与解释的一致性，是否提高事件预测命中率仍未验证。日常输出仍先回答用户问题，再用少量关键依据说明，不把完整JSON或维护评测流程塞给普通用户。
