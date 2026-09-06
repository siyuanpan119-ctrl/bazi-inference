# 计算协议与年度报告运行层

这部分把可重算的历法结果交给宿主 AI，供命局判断、具体问题和岁运解读使用。历法正确并不证明人生事件的预测有效。

## 从用户三项资料启动

用户只需给出生日期时间、性别、出生地城市。宿主 AI 将自然语言解析成 JSON，并从用户给定的观察日期或当前会话日期传入 `as_of`。程序不把某一年写死成“现在”，也不默认缺失的出生时刻是午夜。

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

`generate_report(request, *, as_of, years=None)` 是对应 Python API。若不显式传 `years`，使用请求中的 `years`，再否则使用 `as_of` 所在公历年对应的立春年。

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

## 验证与仍存在的边界

```bash
python3 -m unittest discover -s scripts -p 'test_calendar.py' -v
python3 -m unittest discover -s scripts -p 'test_report_engine.py' -v
python3 -m unittest discover -s scripts -p 'test_ephemeris.py' -v
```

历法测试使用公开天文表、IANA 历史时制与明确的合成例，不发布命例当事人的完整出生资料。运行层验证缺城市、缺时刻、阴历转换、夏令时冲突、节气敏感、换运年分段、十二节月连续性、输入不变性与实际报告输出。

尚未消失的限制：节气全支持时期的独立精度验证；部分地区历史钟表实践；太阳时经度与均时差精度；不同起运/换日学派约定；具体人生事件预测的外部效度。以上限制均有状态或说明，不能写成“所有遗留问题已解决”。
