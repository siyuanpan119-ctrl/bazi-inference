# 八字命理推演 · bazi-inference

**教 AI Agent 根据出生时间、性别和出生地算命。** 本技能提供从排盘到判断的完整传统方法：看月令和根气、辨旺衰、取格局用神与相神、分析成败救应，再推进到大运、流年、流月，回答用户实际关心的问题。

当前版本 **0.5.5**。普通咨询默认先给明确主判断和行动建议，再简述关键命局与岁运依据；数量、时间、渠道和选择问题都应直接作答，把握有限的部分集中简短说明。同步统一八字、事件判断、年度报告和紫微的交付规则，不编造概率或用命理符号计数现实事件。

## 普通用户怎样用

安装后直接说：

> 使用 bazi-inference。我是公历2000年7月15日14:20出生，男，香港。请分析我的命局、事业财运，以及2027年运势。

这只是合成格式示例，使用时换成自己的资料。AI负责整理输入、核验历史时间、计算命盘和完成解释；不要求用户参加测验、提供标准答案或填写审计表。

也可以只问一个具体问题：

- 这个命局更偏向怎样的工作方式？
- 未来几年，哪一阶段更适合发展事业？
- 请分析婚恋倾向，以及2027和2028的差别。
- 请给出年度报告、当前大运及重要流月。
- 根据这份出生资料，判断给定的命例选项并说明理由。
- 分别用八字和紫微分析，并说明两套判断是否一致、有什么区别。

## 技能具体教什么

| 层次 | AI要学会的判断 |
|---|---|
| 排盘 | 公农历、出生城市、历史时区、夏令时、节气、日界和起运；缺资料时保留必要分支 |
| 原局 | 月令、透藏、根气与实际生克链；不按五行数量机械判断旺衰 |
| 格局 | 用神、相神、成格条件、破坏与救应；扶抑和调候另列；合化、从格按条件审查 |
| 岁运 | 同一命局中，大运、流年和流月补足或破坏了哪条作用链；多个年份按相同标准比较 |
| 问题判断 | 区分职责与升职、营收与净资产、恋爱与登记等，比较竞争解释并给主要倾向 |
| 紫微合参 | 独立计算命身、十二宫、星曜、四化和岁限；明确新增区分依据，冲突不靠任意加权解决 |
| 表达 | 结论→关键依据→建议→必要的一句说明；低把握也给首选，不反复撤回或用宽泛主题替代所问结果 |

技能主入口：[SKILL.md](skills/bazi-inference/SKILL.md)。核心教学：[推演主流程](skills/bazi-inference/references/inference.md)、[格局条件树](skills/bazi-inference/references/patterns.md)、[具体问题判断](skills/bazi-inference/references/question-analysis.md)、[年度和大运报告](skills/bazi-inference/references/annual-report.md)。

具体事件使用[条件与竞争解释比较](skills/bazi-inference/references/event-discrimination.md)：已给事件只比较尚未知的时间；区分能力、现实活动与完成结果；在同一领域继续比较最接近的表现。普通咨询和[批量答卷](skills/bazi-inference/references/exercise-mode.md)默认简短原始底稿，按要求完整回答。只有明确要求结构化审计或机器评测时才启用[v3判断记录](skills/bazi-inference/references/decision-record.md)。原记录检查标准保留，无法区分的结果如实标注，不把可提交记录称为已经验证的判断。

输入只明确观察年份时使用 `--as-of-year YYYY`，不将计算锚点冒充观察日期；假设地点、代表时辰及其不确定范围须保留到解释中。普通精确日期接口保持兼容。

紫微模块：[独立解盘与双系统比较](skills/bazi-inference/references/ziwei-inference.md)。一般咨询的交付仍是连贯的判断和依据，不要求用户参与开发评测。

## 在 ChatGPT 和 Codex 安装 Plugin

本仓库根目录已经封装为 skills-only Plugin，并提供 GitHub marketplace。安装步骤见 [PLUGIN_INSTALL.md](PLUGIN_INSTALL.md)。

安装完成并新建对话后，在 ChatGPT 输入 `@八字`，或在 Codex 输入 `$bazi-inference` 显式调用。系统也可以根据问题与 Skill 描述自动匹配。

## 安装给其他 AI Agent

```bash
git clone https://github.com/siyuanpan119-ctrl/bazi-inference.git bazi-inference-project
```

将 `skills/bazi-inference/` 完整导入支持 Agent Skills 的客户端。支持 `.agents/skills/` 惯例的客户端可放在该目录，具体以客户端说明为准。没有技能加载器的 AI 也可阅读 `SKILL.md` 及其引用，但要复算排盘，需要宿主提供 Python 执行能力。[Agent Skills 规范](https://agentskills.io/specification)

**普通使用只需安装 `skills/bazi-inference/`。** 其他目录用于项目维护，不是解读前置步骤。

## 计算与示例

需要 Python 3.10+ 和 IANA 时区数据。固定版本 MIT Astronomy Engine 已随包提供，无须运行时下载。运行计算底稿：

```bash
python skills/bazi-inference/scripts/report_engine.py \
  --input skills/bazi-inference/assets/birth-input.example.json \
  --as-of 2026-09-06 --year 2027 --output /tmp/bazi-context.json
```

程序负责可复算的数据；AI按技能继续完成命理解释。[合成年度报告](examples/annual-report.zh.md)与[事业年份比较](examples/career-comparison.zh.md)展示实际独立调用的交付形式，不是预测命中证明。

### 可选紫微计算

在技能目录执行 `npm ci --ignore-scripts`，按锁文件安装本地依赖。使用固定 `iztro@2.6.1`，不向在线算命服务上传出生资料。调用 `node scripts/ziwei_chart.mjs --help` 查看接口；时间规范化及参数说明见[计算说明](skills/bazi-inference/references/calculation.md)。引擎不接受出生城市，历史时区和夏令时必须先由宿主按计算层处理。无 Node 环境时仍可使用八字模块或用户提供的已核验紫微盘。

## 维护者怎样改进这套方法

我们使用命例题、答案与反例来发现推理问题，再将能复用的判断方法写回技能。开发者工具位于 [maintainer/](maintainer/README.md)：保留原预测、对答案、记录规则改动、比较旧新版结果。普通使用者无需读取或运行这些工具。

每次发布更新教学方法、版本和验证记录。已知答案只能用于提出和修正规则；命中率是否提高，需要未见答案的新人物和事前固定的比较。新版[复盘与准确率验证流程](skills/bazi-inference/references/review-and-evaluation.md)规定冻结原答卷、定位错误和用新命例比较版本。最近一次0.5.2与0.5.3同题冻结比较中，两版均为16/40（40%），新版改对5题、改错5题，没有净提升。0.5.4依据暴露的通用问题作维护修订，本身尚未获得新的预测成绩。[原0.4.1与0.4.2比较协议](maintainer/references/next-trial.md)仅保留为历史计划。修改技能不会训练底层AI模型权重。

验证范围及未决问题见 [EVALUATION.md](EVALUATION.md)。公开仓库不包含私人原始题库或敏感生平资料；许可证见 [LICENSE](LICENSE)。
