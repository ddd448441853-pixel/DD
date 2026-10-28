# 交易提醒机器人（只盯盘 · 只算信号 · 绝不下单）

> 目标：替我盯盘，发现符合规则的机会就推送，附上进场区、止损、目标和 R 值。
> 机器人只负责「盯」和「算」，**开不开单永远由我决定**，不接任何下单权限。

---

## 一、它是什么 / 不是什么

| ✅ 会做 | ❌ 不做 |
| --- | --- |
| 拉 Binance 公开 K 线（无需 API Key） | 不自动开仓 / 平仓 / 改单 |
| 算 EMA / RSI / ATR / 量能 | 不承诺收益、不说「稳赚」 |
| 判断 4h 方向 + 1h 进场 | 没数据时不硬给信号 |
| 算止损 / 1R·2R·3R / 仓位 / 杠杆 / 强平价 | 不因催促放宽规则 |
| 记录日志、每天 9 点复盘 | 不因单笔亏损自动改参数 |

规则全部来自 `../交易档案.md`，改规则先改那份文件 + `config.py`。

---

## 二、目录结构

```
trading-bot/
├─ config.py        所有可调参数（标的、风险、周期、风控阈值…）
├─ data_fetch.py    第1步 数据获取（Binance 公开K线，多地址自动切换）
├─ indicators.py    第2步 指标计算（EMA/RSI/ATR/量能/摆动点）
├─ signals.py       第3步 信号判断（4h方向 + 1h四条进场规则）
├─ risk_push.py     第4步 风控 + 推送（仓位/杠杆/强平价/风控闸门/文案）
├─ journal.py       第5步 日志 + 复盘（交易日志.md + 每日复盘 + 20信号汇总）
├─ main.py          总开关（check / review / followup）
├─ backtest.py      历史回放验证
├─ tests/           每步的测试（跑法见下）
├─ data/            本地 K 线缓存（回放/回测用）
└─ output/          推送存档、风控状态、结构化交易记录
```

---

## 三、本地怎么跑

需要 Python 3.10+，装依赖：

```bash
pip install -r requirements.txt
```

**1. 跑测试（确认每步都通）：**

```bash
cd trading-bot
python tests/test_data_fetch.py
python tests/test_data_fetch_all.py
python tests/test_indicators.py
python tests/test_signals.py
python tests/test_risk_push.py
python tests/test_journal.py
```

**2. 手动触发一次盯盘：**

```bash
python main.py check
```

**3. 历史回放（检验规则灵不灵）：**

```bash
python backtest.py
```

**4. 其他命令：**

```bash
python main.py review     # 手动发一次每日复盘
python main.py followup   # 跟踪「没开」的信号后来走到几R
```

---

## 四、日常怎么用（我 = 你）

1. 机器人每小时（1h K 线收盘后）自动检查一次，4h 收盘自动更新大方向。
2. 只在「早上 8-12 点、下午 14-18 点」推送信号（其他时间只记不打扰）。
3. 收到推送后，你回一句：
   - **「开了」** → 机器人记你已进场；之后平仓时再告诉它结果（赚/亏几 R），它算连亏、单日亏损。
   - **「没开」** → 机器人记下，并事后跟踪「如果开了会走到几 R」。
4. 每天早上 9 点收到复盘；每满 20 个信号收到一次汇总调参建议（调不调你定）。

---

## 五、部署到云端（电脑关了也照常跑）

> 机器人要在云端 24 小时运行，推荐二选一。以下都给好了现成文件。

### 方案 A：GrokBot 例行任务（你提到的目标）

在 GrokBot 里新建一个「例行任务」，把下面这段当任务说明粘进去，并让它每隔 1 小时执行一次、每天早上 9 点再执行一次复盘命令：

```
你是我的交易提醒机器人。规则文件在 交易档案.md（严格遵守）。
每个小时执行：cd trading-bot && python main.py check
每天早上9点执行：cd trading-bot && python main.py review
只盯盘、只算信号、只推送，绝不下单；没数据不硬给信号。
```

（具体「每隔1小时执行」的触发方式，按 GrokBot 例行任务的设置来配；代码和规则它只需按上面命令调用即可。）

### 方案 B：GitHub Actions 免费云端（最省心，电脑关着也跑）

1. 把 `trading-bot/` 里的**所有内容**上传到一个 GitHub 仓库的**根目录**（`.github/workflows/` 已就位）。
2. 在仓库的 **Settings → Secrets and variables → Actions → New repository secret** 里，新建一个名为 `PUSH_WEBHOOK_URL` 的秘密，值填你的推送地址（见下方「手机推送」）。
3. 完成。两个工作流会按 Cron 自动跑（`check` 每小时、`review` 每天 9 点北京时间），免费、无需服务器、电脑关机也在跑，还会把「记忆」（连亏、当日亏损、日志）自动存回仓库。

**手机推送（Server酱，最省事，微信收）：**
1. 打开 sct.ftqq.com，用你的 GitHub 账号登录；
2. 微信扫码关注后，拿到一串 `SendKey`；
3. 把 `https://sctapi.ftqq.com/<你的SendKey>.send` 填到上面的 `PUSH_WEBHOOK_URL` 秘密里。

> 想用企业微信/钉钉群机器人也行：把 `PUSH_WEBHOOK_URL` 填对应群机器人的 Webhook 地址，并把工作流里 `PUSH_CHANNEL: serverchan` 改成 `wecom` 或 `dingtalk`。

### 方案 C：本机定时任务（电脑必须开着）

用 Windows 任务计划程序，每小时跑一次：
```
python "C:\...\trading-bot\main.py" check
```
（电脑关机就停，所以只作备用。）

---

## 六、以后怎么自己改

- **加标的**：改 `config.py` 的 `SYMBOLS`（如 `["BTCUSDT", "ETHUSDT", "SOLUSDT"]`）。
- **改单笔风险 / 账户金额**：改 `config.py` 的 `TRADER`。
- **改风控阈值**：改 `config.py` 的 `MAX_OPEN_SIGNALS`、`PAUSE_HOURS` 等。
- **重大事件（CPI/议息）**：填进 `config.py` 的 `EVENTS` 列表（时间用北京时间）。
- **改策略规则**：先改 `../交易档案.md`，再对应改 `signals.py` / `config.py`。

> 每条规则都有中文注释，对着改即可。改完记得重跑一遍 `tests/`。
