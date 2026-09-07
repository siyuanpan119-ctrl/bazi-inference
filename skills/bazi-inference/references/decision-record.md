# 具体判断的简短底稿

在比较具体事件的完整选项、多个年份或合参裁决时使用，保留原首选也不例外。先按正常命理流程完成命局与岁运，再保存判断依据；本工具不代替推演，也不要求用户提供答案或填写数据。无候选的普通整体解读无需逐段建立记录。

## 从问题写到记录

合成格式见 `assets/decision-record.example.json`。每个问题一份JSON；八字、紫微分别保存，合参记录引用两份原件。字段只服务实际判断，不为凑齐而补造未知事实。

| 字段 | 填什么 |
|---|---|
| `schema_version` | 新记录用整数`2`。兼容旧版`1`；v1也可加入`candidate_reviews`启用同样的对称检查 |
| `target` | `subject`主体、`event_stage`事项阶段、`time_scope`实际时间范围 |
| `candidates` | 全部候选，每项的`id`和`claims`；复合叙述拆成最小子事实 |
| `claims[].state` | `known`用户明确给定；`supported`传统解释相容；`unknown`未确定；`contradicted`与已核验事实或声明结构冲突 |
| `claims[].evidence_ids` | 对应实际依据；不能拿“未知”当已不存在 |
| `evidence` | 每项含`id`、`kind`、`scope`、`source_ref`、`statement` |
| `evidence[].kind` | `calculation`可复算事实；`user_fact`已提供生平；`traditional_interpretation`从符号到事件的解释假设 |
| `evidence[].scope` | `background`多个候选共有；`discriminator`声明有区别，但还须人工审查它是否确实区分 |
| `evidence[].status` | 可选，默认`available`（有这条声明，不代表已验证）；明确未知标`unknown`，只缺正面支持标`missing_support`。后两者不能作为支持、反证或区分依据 |
| `primary`、`strongest_alternative` | 暂定首选及最强竞争解释；不是已知事实 |
| `comparison` | 首选摘要：`against`列所有其余候选；`discriminator_ids`、`why_distinguishes`、`counterevidence`及`required_unknowns`分别列区分、反向与未满足前提。仅列ID不算实际逐项比较 |
| `candidate_reviews` | 每个候选一条同标准审查，字段见下表；包含保留的基线首选和弱备选 |
| `decision_mode` | `conditional`有条件判断；用户要求唯一选项而无法区分时为`forced_choice` |
| `temporal_branches` | 实际分析过的分支`id`及其`primary`，可选`note`记录日期/时辰说明 |
| `expected_temporal_branch_ids` | 计算层发现会影响本题的完整分支清单；用于检查有没有漏掉某段 |
| `fusion` | 两系统各自的`primary`和`record_ref`，另列`override_reason`与`discriminator_ids`；有冲突时无论改票或保留基线都要说明区别，不能只要求挑战者举证 |

这里的`known`只表示用户提供了该事实，不表示我们做过外部核验；`supported`不表示事件已经发生。不要用计算的命盘字段给疾病、财产数量或法律状态盖“已知”标签。依据的引用应指向实际文件与字段，或者明确的传统取法，不写“综合分析”作为来源。

每个候选的子句按完整叙述审查。例：“创业、拥有数套房、净资产达某金额”有三个不同主张，不能只给经营主题就全标支持；未知金额也不能反向证明较小金额选项成立。

### 每候选同样审查，不能只给首选写理由

`candidate_reviews`每条使用以下字段，`id`对应一个候选。数组为空表示明确审过但暂无，不要求弱备选编造证据或证明自己胜出。

| 字段 | 填什么 |
|---|---|
| `support_ids`、`counterevidence_ids` | 分开列支持与反证ID；各自覆盖该候选`known/supported`、`contradicted`子事实所引依据。支持须连接本候选，反证也可列独立的反向条件 |
| `required_unknowns` | 按原`claims[].text`列全该候选的`unknown`子事实，可补其他必要未知；不能漏掉、改成反证或从另一系统借答案 |
| `strongest_alternative` | 对这个候选最强的另一个解释；首选条目须与顶层同名字段一致 |
| `discriminator_ids` | 本次比较声明的区分依据，须连接本候选或所比较备选的支持/反证。无法区分可为空，不要求每个候选都胜出 |
| `comparison` | 简短写该候选与其最强备选各能解释什么、区别及局限；可明确较弱或无法区分，不能只写已比较的ID |

例如“是否入学未知”属于未知；“未找到毕业支持”属于缺正证，都不是“没有毕业”的反证。若将这种缺口列成依据，必须用`status`如实标记；脚本会阻止其进入支持、反证和区分清单，也会阻止同一候选把未知子事实的引用同时当反证。不同子事实的相反作用须分开写依据。不写这些状态而把未知藏在自然语言中，程序无法可靠识别，仍须人工核对。首选必要条件未知时，即使其他候选更弱，也保持未决。

## 检查并回到实际判断

```bash
python scripts/decision_record.py --input /absolute/path/judgment.json --output /absolute/path/judgment-check.json
```

格式错误先修正。结果为未决时，回到原始计算与真实前提，查看缺的是哪条区别；有资料可补则补，没有则保留未决。用户要求全答时仍给出一个字母，并保留强制排序状态，不能删掉困难选项或把备用项算作答对。

v2漏全部或部分候选审查会降为未决；v1不带`candidate_reviews`仍按旧规则读取，结果标`review_standard=legacy_v1`，不表示完成对称审查。格式损坏或ID无效先修正，不由检查器补选候选。

程序只验证声明的字段、引用关系、候选和分支覆盖，不核实古籍、外部文件内容、自然语言真实性或现实预测效度。把“财动”错误地写成`discriminator`仍可能通过；必须人工再问：它是否也支持另一候选？若是，改为共有背景。`relative_basis_declared`只表示声明的结构检查通过，不是医学诊断、法律事实、事件发生或“高准确率”。

同理，保存两个`record_ref`不证明宿主真正隔离过上下文。独立执行应先形成原记录，后交给合参步骤；同一上下文顺序完成时如实说明。`fusion.agreement_as_confidence`若为真，表示错误地以同票提升确定性，应撤回这项提升。

## 具体推演的三个裁决要点

1. **先比较阶段，再比较强弱。** 关系机会、共同责任、法律登记各需不同前提；财务活动、取得收入、保留净资产也分开。只出现强烈变化时，先保留主题，不直接决定事件。
2. **只保留不会被时间分支推翻的全期表述。** 公历月跨节、年度跨交运时分别判读；分支给出不同首选，结论就带日期条件。计算锚点不作实际事件日期。
3. **复合叙述按最弱的未证实部分控制精度。** 学习倾向与已完成学历、社交能力与社交意愿、职业方式与具体行业分别讲；不能把相容叙述累加成一个已确定的人生故事。

以上提高的是可检查性与解释的一致性，是否提高事件预测命中率仍未验证。日常输出仍先回答用户问题，再用少量关键依据说明，不把完整JSON或维护评测流程塞给普通用户。
