# 计算协议与年度报告运行层

这部分把可重算的历法结果交给宿主 AI，供命局判断、具体问题和岁运解读使用。历法正确并不证明人生事件的预测有效。

## 从用户三项资料启动

用户只需给出生日期时间、性别、出生地城市。宿主 AI 将自然语言解析成 JSON；直接咨询从用户给定日期或当前会话日期传入 `as_of`，历史题只给观察年份则保留 `observation_year`，不补月日。程序不把某一年写死成“现在”，也不默认缺失的出生时刻是午夜。

```json
{
  "synthetic": true,
  "birth_datetime": "2000-01-01T12:30:00",
  "sex": "male",
  "birthplace": "香港"
}
```

以上是合成接口演示，不对应真实命主。默认 `calendar=gregorian`、`input_basis=civil`、`time_basis=standard`、`day_boundary=midnight`、`strict_boundary=true`。默认项是公开的实现约定，不是各流派一致结论。

```bash
python3 scripts/report_engine.py --input assets/birth-input.example.json --as-of 2022-01-01 --year 2016 --output /tmp/bazi-report.json --markdown /tmp/bazi-report.md
```

程序使用 Python 3.10+ 标准库、随包固定的 MIT 授权 Astronomy Engine 源码与可用的 IANA 时区资料，无需在线下载星历后端。若环境没有时区数据，宿主须安装并记录 `tzdata` 版本，不能改用固定 UTC 偏移冒充历史时区。运行期间无网络请求；输入和报告不会自动上传。

`generate_report(request, *, as_of=None, years=None)` 是对应 Python API。精确日期模式仍显式传 `as_of="YYYY-MM-DD"`；若不显式传 `years`，使用请求中的 `years`，再否则使用 `as_of` 所在公历年对应的立春年，与旧接口一致。

仅知观察年份时，传 `request.observation_year`（整数），省略 `as_of`；CLI可用 `--as-of-year YYYY` 写入此字段，也可直接从输入JSON读取。它与 `--as-of` 互斥；API也拒绝同时提供年份和精确日期，避免把锚点升格为真实观察日期。CLI与JSON给了不一致的观察年份时拒绝运行。

```bash
python3 scripts/report_engine.py --input assets/birth-input.example.json --as-of-year 2013 --output /tmp/bazi-year-context.json --markdown /tmp/bazi-year-context.md
```

年份模式输出 `as_of=null`、`observation.precision="year"`、`observation.date=null`；`observation.interval` 为该年元旦至次年元旦的半开区间，列出所用出生地时区与对应UTC端点。`observation.calculation_anchor` 记录7月1日及 `is_observation_date=false`，仅供需要代表值的下游接口使用，主引擎按全年求交，不以锚点代替“目前”。接口支持1901—2100观察年，以确保前一立春年也在年度引擎支持范围。

`annual_reports` 自动并入前一立春年与当年，不因显式 `years` 筛选漏掉元旦至立春；显式年份是追加资料。出生当年标为 `observation.coverage="partial_birth_year"`，纯出生前的立春年列在 `pre_birth_solar_years` 并不自动生成。`nominal_coverage` 与 `nominal_effective_start_utc` 只按名义出生瞬间记录；出生不确定窗口跨观察年元旦时，`coverage="uncertain_birth_year_boundary"`，`coverage_candidates` 保留 `complete_year` / `partial_birth_year` 两种覆盖，不能用代表钟点消除分歧，严格与非严格模式均如此。`coverage_basis` 说明所用窗口依据。`observation.dayun_segments` 另保留公历观察全年实际相交的交运段及操作误差；起运前与九步大运之后的时段另有标志，不能假称已有全寿程大运。严格出生边界未解时仍暂停年度/大运资料并标 `dayun_segments_status="withheld_birth_boundary"`，相关起运前/超出大运范围标志及 `pre_birth_solar_years` 置为null；观察区间完整不等于已经完成分支解释。

### 观察时点完全未知时

`generate_report` 及其CLI需要观察日期或年份，不能为满足接口把系统日期、最大选项年份或任意锚点伪装成题目“目前”。此时可直接调用同包 `calendar_engine.chart` 生成本命，调用 `report_engine.luck_intervals` 与 `annual_facts` 生成题面明确指定年份的计算底稿；观察范围保持未知，由宿主整理短摘要。涉及“目前”的选项给条件性选择或猜测，其他明确年份的分析继续完成。该路径不放宽历法边界，合法时间和地点分支仍需核验。

## 地点解析和时制

内置别名包括香港、台北、上海、北京、广州、深圳、唐山、吉隆坡、槟城乔治市、新山、怡保、古晋、亚庇。香港与台北使用各自 IANA 历史时区；马来西亚半岛与沙巴、砂拉越分别解析，1977 年等历史年份不会统一套用今天的 UTC+8。

城市—时区表来源于 [IANA zone.tab](https://data.iana.org/time-zones/tzdb/zone.tab)，历史规则来自 [IANA asia 源文件](https://data.iana.org/time-zones/tzdb/asia)。这些资料存在历史不完备处；出生记录使用何种钟表口径仍可能需文献核对。北京等非上海大陆城市在 1970 年以前不会直接继承上海早期时区史，而返回 `needs_resolution`。新疆城市不能凭“中国”字样代选北京时间或当地时间。

只写“美国”“中国大陆”“马来西亚”“台湾”或未知城市会返回 `needs_resolution`。宿主先解析明确城市和历史时区；不要替用户填首都。外部解析可传：

```json
{
  "synthetic": true,
  "birth_datetime": "2000-01-01T12:30:00",
  "sex": "female",
  "birthplace": {
    "city": "Paris",
    "timezone": "Europe/Paris",
    "timezone_source": "https://data.iana.org/time-zones/tzdb/europe"
  }
}
```

外部来源字段是调用者的可审计声明，程序并未联网验证该页面包含所填值。输入真太阳时经度时必须同时提供 `longitude_source`；经度东正西负，且需记录城市中心或精确地点的分辨率。只提供时辰范围时不能伪装成精确出生分钟；宿主可保留所有时刻候选，或使用明确标记的中心与 `time_uncertainty_minutes` 做边界检查。单次不确定区间上限为前后 24 小时，跨夏令时切换要拆开解析。

外部 `birthplace` 对象可显式加 `"status":"scenario"`，表示条件性地点。输出 `birthplace_resolution.status` 原样保留 `scenario`，不会因提供了时区来源而升格为 `resolved`；`interpretation_must_be_conditional_on_birthplace=true` 和Markdown也注明非已确认出生城市。省略状态沿用旧接口的调用方 `resolved` 声明，不是引擎查证；情景地点应使用此对象形式。未知状态或必要地点/来源缺失返回 `needs_resolution`，不凭城市名称中的文字猜测状态。

出生仅有时辰而用代表钟点调用时，显式传 `time_precision="shichen"` 及正数 `time_uncertainty_minutes`；例如代表08:00、前后60分钟。未给范围或填0返回 `needs_resolution`，不能把代表值当作精确分钟。`birth_time_precision` 保存代表值标志、输入钟面窗口端点与口径，范围继续传入节气、时辰及起运误差检查。时间精度也接受 `clock`（缺省）、`minute`、`second`；它们表示输入声明，不是独立核验。布尔、非数字、负数、非有限数及超过1440分钟的半径均不可用。

注意：此对称窗口调用现有引擎的**保守端点检查**，不是新的半开时辰解析器。已明确辰时的原始区间仍是 `[07:00,09:00)`，09:00不能改称真实可能出生时刻；程序因窗口端点产生的邻盘仅是保守核验提示，不证明原始时辰跨界。须保留原始范围、其端点含义和已定地支，按这些资料核验或独立建立合法分支；不能伪填59.999分钟来绕过边界。

需要在此保守门槛下继续准备情景底稿时，可显式设置 `strict_boundary=false`，仍保留 `time_precision="shichen"`、代表钟点及真实的 `time_uncertainty_minutes`。例如已明确采用标准时地支的辰时，可用08:00与前后60分钟生成底稿，但原始资料仍是 `[07:00,09:00)`、不是出生于08:00。未解状态仍为 `needs_verification`，四柱标 `nominal_pillars_only=true`；非严格模式只是开放年度和大运计算资料，不表示候选已经核实。

宿主负责按原始范围及钟面口径确认合法分支：上述标准时辰时若区间内没有真实节气、换日或时制变化，只有辰时，保守探针生成的07:00之前或09:00邻盘不列为实际出生候选；若存在真实边界，则按实际相交段独立重算与比较。保存合法分支、排除端点邻盘的理由和原输入，不能只将 `strict_boundary` 关掉就宣称稳定。继续使用 `chart.luck.age_margin_years_operational` 与 `dayun` 的日期误差，跨交运范围保留两段；中心报告不提供精确出生分钟或精确交运日。这一路径让普通已定时辰仍可获得条件性完整底稿，而不需要改写历法核心或伪造分钟。

以真实 UTC 瞬间为基准，`standard` 从原民用钟面扣除当时夏令时，不把出生瞬间整体平移。若原资料已扣过夏令时，用 `input_basis=standard` 防止重复扣减。跳时造成不存在的钟面时间必须补资料；回拨造成的重叠时间必须给出 `fold=0/1`。

报告比较民用时、标准时、真太阳时的四柱差异，并在选用钟面为 23 时比较午夜换日与子初换日。真太阳时按 UTC + 经度×4分钟 + 均时差近似。香港、台北、上海、吉隆坡、古晋的内置经度只是 IANA 主地点参考坐标，不能当作医院坐标；其他城市没有经度就不算该分支。太阳时分支敏感时需用户确认地点精度，不应根据已经知道的人生答案反选时辰。

## 节气：优先权威数据，边界保留候选

实际运行已内置两年共 24 个“节”的权威分钟时刻，而非只把它们写在测试里：

- [香港天文台 2013 年节气表](https://www.hko.gov.hk/sc/gts/astron2013/Solar_Term_2013.htm)
- [香港天文台 2016 年节气表](https://www.hko.gov.hk/sc/gts/astron2016/Solar_Term_2016.htm)

天文台表以香港时间 UTC+8 给出，程序转成 UTC。优先级是：调用者有来源的时刻覆盖 → 内置天文台时刻 → 固定版本 Astronomy Engine 的 `SearchSunLongitude`。原 Meeus/NOAA 风格截断太阳黄经公式保留为 `jie_approx` 用于比较，已不担任默认节气后端，也不在错误时静默回退。均时差函数仍是近似公式，太阳时边界限制仍须保留。

后端时刻前后 30 分钟作为保守工程检查区间；内置天文台分钟值前后 1 分钟作为检查区间。二者都是操作门槛，**不是已经证明的误差上界或置信区间**。绕开内置覆盖、直接核验新后端的 24 个权威校验点后，最大绝对时差由旧模型 766.60 秒降至 48.54 秒，平均绝对时差由 305.54 秒降至 20.36 秒。天文台原值按分钟给出，时差含来源舍入影响；该结果只覆盖 2013/2016 的 24 个节，不能外推成全时期分钟精度。上游一般角精度目标约 ±1 角分，也不能直接当作通用节气时刻误差保证。

固定源码来源：[Astronomy Engine commit 826e26f](https://github.com/cosinekitty/astronomy/tree/826e26ff3a6dc03ee46658b1138fef582d96c5d9)。随包 `scripts/vendor/astronomy.py` 保留 Don Cross 的版权与 MIT 许可原文，没有修改；SHA-256 为 `41248c7b1edbf9d11119528eef7455a6dc55abde9f1aab40d363015e956c1729`。版本、逐点验证与限制见 `references/ephemeris-provenance.json`。数值求根容差不代表物理精度。

覆盖输入示例：

```json
{
  "2016-立春": {
    "utc": "2016-02-04T09:46:00+00:00",
    "source": "https://www.hko.gov.hk/sc/gts/astron2016/Solar_Term_2016.htm",
    "margin_minutes": 1
  }
}
```

此对象放在 `verified_terms` 中。只接受带时区和来源的覆盖值；与后端时刻相差超过一天或误差字段为负值、无穷等会拒绝。名称和来源仍须由宿主核验，不能让“verified”字段充当证据本身。

出生靠近节气或输入时刻区间跨过时辰/换日时，`chart.year_month_candidates` / `chart.day_hour_candidates` 保存两侧情况。报告默认严格模式返回 `needs_verification`，保留带 `nominal_pillars_only` 的名义计算供核查，同时暂停唯一盘的 `annual_reports` 与 `dayun`。不能把名义候选偷当成确定命盘。改善输入或加入权威时刻后再计算。

### 宿主必须完成的区间与旁盘步骤

1. 先辨别用户给的是“已确定的地支时辰”还是“原始钟表范围”。地支时辰不伪装成整点分钟；原始范围按约定半开区间保留，端点是否包含不明且会改盘时注明。
2. 需要中心值计算时，显式标为代表值并给不确定范围。例如辰时的中心08:00只能是07:00—09:00范围的代表，不是新的出生事实。不要另添范围以外的16:59等时刻冒充候选。
3. 国家级地点允许条件性场景比较，但输入及最终报告均标记“情景地点、非已确认城市”。先完成不随场景变化的判断，变化的部分保留。
4. 保存原输入。对实际会改年/月/日/时柱或起运的分支，分别运行完整报告、重建十神与岁运，不手改主盘一个字后沿用原来的格局。
5. 对本题首选和最强备选逐分支比对；只有本题的支持条件和排序均未变，才称该结论对这些分支稳定。未比较的分支只能写“尚未分析”。

旁盘比较是对未知出生资料的敏感性检查，不以选中已揭晓答案为校时标准；人工记录了旁盘四柱，不等于已经完成旁盘推断。

边界计算状态限制“唯一命盘及全期稳定结论”的声明。完成合法分支比较后，按用户给定口径或明确情景给出主要判断，说明哪些方向稳定、哪些依赖边界；不伪造精确出生时间，不把程序状态直接抄成整份解读。选择题交付另见 `exercise-mode.md`。

### 将时间精度保留到结论

出生时间的不确定性和事件时间的不确定性分开处理。问“公历某月”时，以该地月初至下月初为区间，与节月和大运段求交；不能把公历五月直接当巳月。保存每个相交段的首选及依据；排序改变则报告时段依赖，事件具体日期未知时不挑有利的一段概括整月。

题目将“目前”限定到某年但没有月日时，按上面的年份接口保存 `observation_year` 和未知的月日，计算覆盖全年相关段。下游接口若必须传单日，可用明确标记的计算锚点生成资料；锚点不是观察日期，不得用其年龄、当前大运或状态代替全年比较。出生城市只用于共用时区解析时仍保留真实城市名称，不把共用时区的首府写成出生地。

普通咨询在简短底稿中记下实际分析过的边界、相关条件改变及结论。明确启用结构化评测时，`decision-record.md` 的分支字段记录实际分析过的各段，期望分支清单来自本层计算；v3每段记录排序或并列及理由，不能只保存边界说明；缺清单的旧记录不能宣称完整覆盖。候选事件年互斥时，每个共同时间口径情景仍比较全部年份，具体年内段作为依据，不把不同候选年的任意片段伪装成同一个观察时刻。

## 四柱、十神、大运

年柱以立春分界，月柱以十二“节”分界，不以农历初一或全部二十四节气混排。日柱使用公历 JDN 和甲子循环。时柱按已选择的换日规约与五鼠遁同步计算；年干配月干按五虎遁。

五行相生顺序为木→火→土→金→水→木；相克为木→土→水→火→金→木。十神按日干、五行关系与阴阳逐一计算。藏干顺序是固定传统表；计数、合冲关系都不自动换算成旺衰权重或吉凶概率。

起运采用年干阴阳和性别决定顺逆：阳男阴女顺，阴男阳女逆；以出生到下一“节”或上一“节”的真实时间差按三天折一年。将起运年龄换成公历日期时，本版明确采用一周年=365.2425个经过日；这不是不同流派公认的唯一换算法。报告列九步大运，每步十年，给出起止周岁约数、UTC约日期与操作误差。若刚好在立春等边界，年干方向和月柱本身也可能改变，必须分支重算，不能仅给起运年龄加减几天。

## 年度输出可直接用于报告工作流

`annual_reports` 包含：

| 字段 | 内容与使用边界 |
|---|---|
| `solar_year` / `pillar` | 指定立春年的干支，不把公历元旦当换年 |
| `interval` | 该年立春到下一立春、各端点来源及精度门槛 |
| `stem_ten_god` | 流年天干相对命主日干的十神 |
| `dayun_segments` | 年内所有重叠大运段；交运年不强行压成一种大运 |
| `annual_natal_relations` | 干支生克、五合配对、冲合刑害破等计算关系 |
| `months` | 十二节月的月柱、十神、起止节与原局关系；每月 `dayun_segments` 保留实际相交的大运段及“原局＋大运＋流年＋流月”联合关系，交运月不压成一个大运 |
| `traditional_observation` | 明确标记为传统假说的观察主题，无具体事件断言 |
| `interpretation_tasks` | 宿主 AI 接着完成格局、扶抑、调候、反证和生活背景分析 |

`report_markdown` 给出可读四柱、大运表和流年月表。它是宿主的分析底稿；宿主还须依解释规程给出连贯的年度报告，不能把空泛主题换成诊断、官司、死亡或财富金额。格局用神与相神沿用用户定义，扶抑与调候喜忌须分别写明。

完整 JSON 包括每个节月的联合关系，可能很长。先用 `--markdown` 输出短底稿，再用标准库 `json` 提取当前需要的字段；年度总览无需一次读入十二个月的全部关系。计算时刻以带偏移的 ISO 字符串保存，UTC 日期可能与当地日期相差一天。用户报告采用的时区应明确；可用 `datetime.fromisoformat(value).astimezone(ZoneInfo(timezone_name))` 换算，而不是直接截取 UTC 字符串日期。交运约值即使带秒，也不代表精确到秒的事件触发时刻。

## 可选紫微计算：规范钟面后再安星

需要 Node.js 20+。在技能安装目录执行 `npm ci --ignore-scripts` 安装锁文件指定的 `iztro@2.6.1` 及依赖。依赖安装访问软件仓库，排盘本身在本地计算，不发送出生资料。没有 Node 环境时，八字计算仍可单独使用；紫微可改用用户提供的已核验命盘，不能声称已运行本适配器。

```bash
node scripts/ziwei_chart.mjs --input /absolute/path/ziwei-input.json --output /absolute/path/ziwei-context.json --markdown /absolute/path/ziwei-context.md --palaces 命宫,官禄,财帛
```

下面是**上游公开计算样例的格式示范**，不是用户生平：

```json
{
  "schema_version": "ziwei-normalized-input/v1",
  "solar_date": "2000-08-16", "hour_index": 2, "sex": "female",
  "normalization": {
    "status": "scenario", "clock_basis": "civil",
    "note": "公开安星样例，寅时为已提供时辰，不代表已核实个人出生钟表。"
  },
  "targets": [{"solar_date": "2023-10-26", "hour_index": 0}],
  "years": [2023, 2024]
}
```

普通用户不填写这些字段；由宿主先解析原始时间及其口径，再建立输入。`confirmed` 只表达调用方已处理该输入口径，不是引擎独立查证；未知城市或时段分支用 `scenario`，每个实际可能分支独立计算。`hour_index`：0为00:00—00:59，1为丑，依次11为亥，12为23:00—23:59；不要把晚子再次手工加一天后又选 `forward`。

默认年界、运限界与年龄界采用 `normal`，晚子采用 `current`，安星为 `default`，`fixLeap=true`；完整四化、亮度表与许可证见 `assets/ziwei-profile.json`。通过 `--day-divide forward` 另算晚子次日分支；每次CLI启动独立进程，避免全局配置串盘。其他流派本接口尚未开放，不声称已经计算中州派或自定义宫干飞化。

`targets` 是明确日期与时辰的**岁限快照**；`years` 是需要覆盖的公历年（最多50个不重复的1901—2099年）。两者均未提供时只返回本命，不借用机器日期。`years` 在当前固定的 `normal` 年界／年龄界配置下扫描民用日期，按大限、流年、虚岁变化生成连续区间；出生年从出生时刻或已知时辰起算，标为部分年度。不是用一个年中快照代表全年，紫微岁限也不采用八字交运日。

| 输出 | 使用方式 |
|---|---|
| `annual_periods[].coverage` | 检查 `complete_year` 或 `partial_birth_year`、实际覆盖范围与配置；仅覆盖大限、流年、虚岁，明确排除流月、流日和流时 |
| `annual_periods[].segments[]` | 读取 `interval.start_inclusive` 至 `end_exclusive`、`starts_because` 和各段 `layers`；报告按不同段分别判断 |
| `evidence_context.palace_catalog` | 完整十二宫、物理星曜位置和亮度；不是只保留目标宫 |
| `evidence_context.natal_layer` | 本命宫位映射、三方四正、本命四化及落宫 |
| `evidence_context.frames[].layers` | 快照或年度分段的独立大限／流年宫位、四化、流曜与叠宫映射 |
| `source_ref`、`stem_source_ref`、稳定 `id` | JSON Pointer 可回溯计算原字段；相同星曜／四化跨视图重复出现按稳定ID去重，不重复加权 |

`--markdown` 输出便于宿主阅读的底稿；`--palaces` 只筛选底稿目标宫（逗号分隔），不会裁掉JSON的十二宫。先读底稿，再按来源指针提取竞争解释需要的旁盘，四化必须保留 `source_scope`，不可把本命忌与流年忌混为同一层。以2024为例，本配置公历全年分为1月1日至2月10日、2月10日至2025年1月1日两段；这只是年界计算示范，不是事件应验日。若问题需要流月／流日，须另建明确日期快照并核验相应边界，不把当前年度分段冒称完整月日覆盖。

输出保存版本、配置、文件哈希、规范化声明、本命和指定岁限。它们保证计算口径可追溯，不是医学诊断或具体事件预测。继续依 `ziwei-inference.md` 解读，结合八字时先各自形成判断，再比较同一主体、同一事件阶段与时间范围。

可选模块的软件检查：`npm run test:ziwei`。它核验公开安星例、输入、晚子和快照等程序行为，不检验命理预测效度。

## 验证与仍存在的边界

```bash
python3 -m unittest discover -s scripts -p 'test_calendar.py' -v
python3 -m unittest discover -s scripts -p 'test_report_engine.py' -v
python3 -m unittest discover -s scripts -p 'test_ephemeris.py' -v
```

历法测试使用公开天文表、IANA 历史时制与明确的合成例，不发布命例当事人的完整出生资料。运行层验证缺城市、缺时刻、阴历转换、夏令时冲突、节气敏感、换运年分段、十二节月连续性、输入不变性与实际报告输出。

尚未消失的限制：节气全支持时期的独立精度验证；部分地区历史钟表实践；太阳时经度与均时差精度；不同起运/换日学派约定；具体人生事件预测的外部效度。以上限制均有状态或说明，不能写成“所有遗留问题已解决”。
