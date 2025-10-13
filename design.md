# Future V0.1 交易系统 —— 设计文档（目录结构 + 接口合同）

> 目标：让团队与 Cursor 基于**清晰的目录与接口合同**快速产出代码。本文不包含实现，仅定义**目录结构、文件职责、数据契约、接口方法、并发/幂等语义**与**运行模式**。
> 目录的**一级分层**固定为：`tradingsystem / optionscreen / strategy / db / marketsource / utils / config`。

---

## 0. 总览与运行模式

* **运行模式**：`backtest`（回测一致性）、`paper`（实盘模拟）、`live`（实盘真实）。
* **跨模块通信**：**唯一 Buffer**（队列/流），`optionscreen → Buffer → strategy`；`tradingsystem`负责装配、调度、故障恢复与下单。
* **幂等键**：

  * 事件：`event_id = hash(symbol, event_time_et, premium, ask, chain_id)`
  * 订单：`client_id = hash(event_id, action, t_exec_et)`
* **日志等级**：`INFO / WARNING / ERROR`，并配套审计（append-only）。
* **V6 规则**：15:30(ET)后事件；**+2分钟**bar收盘买入；每日≤5笔、当日总仓位≤99%；单笔≤30%；premium≥$100k；杠杆≤1.45×，现金≥-50%；止损-5%、止盈+15%、第6天15:00(ET)定时平仓；黑名单15天。

---

## 1. 顶层目录与文件职责

```
future_v0.1/
├─ tradingsystem/                 # 主控：装配、线程、缓冲、守护、指标、调度
│  ├─ app.py                      # 程序入口（读取 config，构建系统，注入策略并启动）
│  ├─ system.py                   # TradingSystem 主类（start/stop/inject_strategy/health）
│  ├─ buffer.py                   # 统一 Buffer 接口与实现（queue 或 redis 可替换）
│  ├─ scheduler.py                # 轻量任务调度与心跳监控
│  ├─ guard.py                    # Kill-Switch 交易保护（pause/resume）
│  ├─ metrics.py                  # 指标/告警接口
│  └─ loops.py                    # 信号线程/持仓线程/订单回报监听线程（调用策略接口）
│
├─ optionscreen/                  # 期权TXT监控与解析（生产 SignalEvent）
│  ├─ watcher.py                  # 目录监控（增量扫描/事件）
│  ├─ parser.py                   # 行解析与字段校验，CN→ET 转换，生成 event_id
│  └─ replayer.py                 # 回测/重放器（按时间升序推送到 Buffer）
│
├─ strategy/                      # 策略抽象与实现（V6 等）
│  ├─ base.py                     # StrategyBase 抽象类（on_signal/on_position_check 等）
│  ├─ models.py                   # 数据契约（SignalEvent/EntryDecision/ExitDecision/PositionView）
│  ├─ context.py                  # StrategyContext（cfg/repo/market/logger 门面）
│  ├─ v6.py                       # V6Strategy（继承 StrategyBase，落地 V6 规则）
│  ├─ rules.py                    # 公共规则片段（止盈止损/定时/黑名单/时间窗等）
│  └─ position.py                 # 风险模拟 & 缩减（99%/1.45×/-50%）
│
├─ db/                            # 持久化与对账（ORM/Repo/审计）
│  ├─ models.py                   # ORM 模型（raw_option_events/trades_open/positions/...）
│  ├─ repo.py                     # Repository 接口：幂等写入、日内容量预定/提交、黑名单等
│  ├─ reconcile.py                # 券商对账（拉取成交、差异报告）
│  ├─ audit.py                    # 审计日志（append-only）
│  └─ migrate.py                  # 建表/迁移辅助
│
├─ marketsource/                  # 行情/交易门面（多模式实现）
│  ├─ gateway.py                  # MarketGateway 抽象（账户/行情/下单 API）
│  ├─ order_oms.py                # OrderOMS（place/amend/cancel/status）
│  ├─ router.py                   # AccountRouter（多账户/多市场）
│  ├─ exec_clock.py               # ExecPriceService（分钟收盘价、回退策略）
│  ├─ feed_backtest.py            # 回测数据源（CSV分钟线）
│  ├─ feed_realtime.py            # 实时行情（订阅聚合到 1m）
│  └─ clock.py                    # TradeCalendar（交易日/开闭市/半日市）
│
├─ utils/                         # 通用工具
│  ├─ tz.py                       # 时区 CN↔ET/DST 安全
│  ├─ business_day.py             # 交易日加减、定时平仓时间求解
│  ├─ validation.py               # 输入校验/DQ
│  ├─ dedup.py                    # 幂等键生成
│  ├─ exec_policy.py              # 执行回退解析（价格缺口策略）
│  └─ fallbacks.py                # 异常场景统一回退策略
│
├─ config/
│  ├─ loader.py                   # load/validate/hot-reload（ConfigWatch）
│  └─ config.yaml                 # 全局配置（模式、阈值、路径、风控等）
│
└─ README.md
```

---

## 2. 数据契约（Data Contracts）

**（所有模块共享，方言由 `strategy/models.py` 定义）**

```text
SignalEvent
  - event_id: str
  - symbol: str
  - premium_usd: float
  - ask: float?                  # 可空
  - chain_id: str?               # 期权合约（用于 DTE）
  - event_time_cn: datetime      # Asia/Shanghai
  - event_time_et: datetime      # America/New_York（已转）

EntryDecision
  - symbol: str
  - shares: int
  - price_limit: float
  - t_exec_et: datetime
  - pos_ratio: float
  - client_id: str               # 幂等下单ID
  - meta: dict

ExitDecision
  - symbol: str
  - shares: int
  - price_limit: float
  - reason: enum{"SL","TP","Timed","Manual"}
  - client_id: str
  - meta: dict

PositionView
  - position_id: str
  - open_id: str
  - symbol: str
  - shares: int
  - price_in: float              # 含买入滑点
  - fee_in: float
  - open_time_et: datetime
  - exit_due_et: datetime
  - meta: dict

OrderResult
  - client_id: str
  - status: enum{"FILLED","PARTIAL","REJECTED","CANCELLED","PENDING"}
  - filled_shares: int
  - avg_price: float?
  - ts_et: datetime
  - broker_order_id: str?
  - raw: dict
```

---

## 3. `tradingsystem` 接口

### 3.1 TradingSystem（主控）

```text
TradingSystem
  + start(): None
  + stop(): None
  + inject_strategy(strategy: StrategyBase): None
  + health() -> dict                         # 线程心跳、队列水位、最近错误
```

### 3.2 Buffer（唯一交换通道）

```text
Buffer
  + publish(ev: SignalEvent): None
  + consume(timeout_s: float) -> SignalEvent|None
  + size() -> int
```

### 3.3 Scheduler（任务/心跳）

```text
Scheduler
  + add_task(name: str, fn: Callable, interval_s: float): None
  + start(): None
  + stop(): None
```

### 3.4 TradingGuard（交易保护）

```text
TradingGuard
  + is_paused() -> bool
  + pause(reason: str) -> None
  + resume() -> None
  + reason() -> str|None
```

### 3.5 Metrics / Alerts（可观测性）

```text
Metrics
  + inc_counter(name: str, labels: dict|None=None): None
  + observe_hist(name: str, value: float, labels: dict|None=None): None
  + gauge_set(name: str, value: float, labels: dict|None=None): None
  + snapshot() -> dict

Alerts
  + notify(level: enum{"INFO","WARN","CRIT"}, title: str, body: str, labels: dict|None=None): None
```

---

## 4. `optionscreen` 接口

### 4.1 OptionWatcher（TXT → 事件）

```text
OptionWatcher
  + start(): None
  + stop(): None
  # 由 TradingSystem 注入的回调（默认：入库 + Buffer.publish）
  - on_new_event(ev: SignalEvent) -> None
```

### 4.2 OptionParser（行解析与标准化）

```text
OptionParser
  + parse_line(line: str) -> dict|None              # 抽取原始字段
  + to_event(fields: dict) -> SignalEvent           # CN→ET 转换 & event_id 生成
```

### 4.3 SignalReplayer（回测重放）

```text
SignalReplayer
  + load_from_db_or_file(source: str) -> Iterable[SignalEvent]   # 时间升序
  + play_to_buffer(buffer: Buffer, speed: enum{"realtime","asap"}, throttle_ms: int=0): None
```

---

## 5. `strategy` 接口

### 5.1 StrategyBase（抽象）

```text
StrategyBase
  + on_start(): None
  + on_shutdown(): None
  + on_day_open(trading_date_et: date): None
  + on_day_close(trading_date_et: date): None

  + on_signal(ev: SignalEvent) -> EntryDecision|None
  + on_position_check(pos: PositionView) -> ExitDecision|None

  + on_order_filled(res: OrderResult): None
  + on_order_rejected(res: OrderResult, reason: str): None
```

### 5.2 StrategyContext（依赖注入）

```text
StrategyContext
  - cfg: dict
  - repo: Repository
  - mkt: MarketGateway
  - logger: Logger
```

### 5.3 风险模拟（建议由 strategy/position.py 提供）

```text
RiskSimulator
  + simulate_after_entry(decision: EntryDecision) -> dict
    # 返回：
    #  equity_after, cash_after, gross_exposure_after, gross_leverage_after
    #  meets: { daily_gross_cap: bool, max_leverage_1p45: bool, min_cash_ratio_neg50: bool }

  + scale_down_to_fit(decision: EntryDecision) -> EntryDecision|None
```

---

## 6. `db` 接口

### 6.1 Repository（核心持久化）

```text
Repository
  # 基础
  + ensure_schema(): None
  + now_et() -> datetime

  # 原始事件
  + insert_raw_event_if_new(ev: SignalEvent) -> bool
  + blacklist_until(symbol: str) -> datetime|None

  # 交易限额（当日，幂等+并发安全）
  + used_today() -> dict                                     # {"trade_count": int, "gross_ratio": float}
  + reserve_daily_capacity(ratio: float) -> str|None         # reservation_id | None
  + commit_daily_capacity(reservation_id: str) -> None
  + rollback_daily_capacity(reservation_id: str) -> None

  # 开仓/持仓/平仓
  + persist_open(ev: SignalEvent, decision: EntryDecision, res: OrderResult) -> str   # returns open_id
  + open_positions() -> list[PositionView]
  + persist_close(pos: PositionView, decision: ExitDecision, res: OrderResult) -> str

  # 黑名单
  + add_blacklist(symbol: str, until: datetime): None

  # 故障恢复
  + load_last_state() -> dict                      # {last_file, last_offset, ...}
  + save_last_state(state: dict): None

  # 审计/订单
  + persist_order_event(order: OrderResult): None
  + last_order_status(client_id: str) -> OrderResult|None

  # 风控审计
  + audit_risk(snapshot: dict): None
```

### 6.2 Reconciler（对账）

```text
Reconciler
  + pull_broker_fills(since_et: datetime) -> list[OrderResult]
  + reconcile_local_vs_broker(window: tuple[datetime, datetime]) -> dict   # 差异报告
  + persist_recon_report(report: dict): None
```

### 6.3 AuditLog（合规日志，追加式）

```text
AuditLog
  + append(event_type: str, payload: dict, ts_et: datetime, actor: str): None
  # event_type 示例：
  # "SIGNAL_RECEIVED" / "FILTER_DROPPED" / "ENTRY_DECIDED" /
  # "RISK_SIM_OK" / "DAILY_CAP_RESERVED" / "ORDER_PLACED" /
  # "ORDER_FILLED" / "EXIT_DECIDED" / "DAILY_CAP_COMMIT"
```

---

## 7. `marketsource` 接口

### 7.1 MarketGateway（行情/交易门面）

```text
MarketGateway
  # 账户/风险
  + get_equity() -> float
  + get_cash() -> float
  + get_gross_exposure() -> float

  # 行情
  + get_minute_close(symbol: str, ts_et: datetime) -> float|None
  + get_realtime_price(symbol: str) -> float|None
  + get_minute_series(symbol: str, start_et: datetime, end_et: datetime) -> "Series|DataFrame"

  # 交易（幂等 client_id）
  + place_buy(symbol: str, shares: int, limit_price: float, client_id: str) -> OrderResult
  + place_sell(symbol: str, shares: int, limit_price: float, client_id: str) -> OrderResult
```

> 建议三个实现：`FutuLiveGateway` / `PaperGateway` / `BacktestGateway`（同签名）。

### 7.2 OrderOMS（订单状态机）

```text
OrderOMS
  + place_buy(symbol: str, shares: int, limit_price: float, client_id: str) -> OrderResult
  + place_sell(symbol: str, shares: int, limit_price: float, client_id: str) -> OrderResult
  + cancel_order(client_id: str) -> bool
  + amend_order(client_id: str, new_limit_price: float, new_shares: int|None=None) -> OrderResult
  + get_order_status(client_id: str) -> OrderResult
```

### 7.3 AccountRouter（多账户/多市场）

```text
AccountRouter
  + register(account_id: str, gateway: MarketGateway): None
  + resolve_account(symbol: str, tags: dict|None=None) -> str
  + gateway(account_id: str) -> MarketGateway
```

### 7.4 ExecPriceService（撮合时序/执行价）

```text
ExecPriceService
  + get_close_at(symbol: str, t_exec_et: datetime) -> float|None
  + fallback_policy() -> enum{"skip","next_bar","use_last","use_rt"}
```

### 7.5 TradeCalendar（交易日/半日市）

```text
TradeCalendar
  + is_trading_day(date_et: date) -> bool
  + next_trading_day(date_et: date) -> date
  + session_open_et(date_et: date) -> datetime
  + session_close_et(date_et: date) -> datetime
  + half_day_close_et(date_et: date) -> datetime|None
```

---

## 8. `utils` 接口

```text
TimeZone
  + cn_to_et(dt_cn: datetime) -> datetime
  + to_time_et(day_et: date, time_str: "HH:MM:SS") -> datetime
  + now_et() -> datetime
```

```text
BusinessDay
  + add_business_days(day_et: date, n: int) -> date
```

```text
Validation
  + validate_signal(ev: SignalEvent) -> tuple[bool, str|None]
  + check_monotonic_time(events: list[SignalEvent]) -> tuple[bool, str|None]
  + ensure_bar_continuity(symbol: str, day: date) -> tuple[bool, dict]
```

```text
Idempotency
  + make_event_id(symbol, event_time_et, premium, ask, chain_id) -> str
  + make_client_id(key: str, action: str, t_exec_et: datetime) -> str
```

```text
ExecPolicy
  + resolve(symbol: str, t_exec_et: datetime, svc: ExecPriceService) -> tuple[float|None, datetime|None]
```

```text
Fallbacks
  + for_quote_gap() -> enum{"skip","next_bar","use_last","use_rt"}
  + for_exec_timeout() -> enum{"cancel","wait","amend_price","marketable_limit"}
  + for_gateway_error() -> enum{"retry_linear","retry_exp","fail_fast"}
```

---

## 9. `config` 接口

```text
Config
  + load(path: str) -> dict
  + validate(cfg: dict) -> None
  + get_mode(cfg: dict) -> enum{"backtest","paper","live"}

ConfigWatch
  + start(path: str, interval_s: int=3): None
  + stop(): None
  + on_change(callback: Callable[[dict], None]): None
  + current() -> dict
```

**建议 `config.yaml` 关键段**（用于 Cursor 生成样板）：

```yaml
mode: "live"  # backtest | paper | live
paths:
  option_txt_dir: "/data/uw_signals/"
  stock_min_csv_dir: "/data/stock_data_csv_min/"
  log_file: "logs/system.log"
db:
  url: "sqlite:///trade.db"
logging:
  level: "INFO"
buffer:
  impl: "queue"       # queue | redis
  maxsize: 10000
strategy:
  entry_after_et: "15:30:00"
  buy_delay_minutes: 2
  exit_time_et: "15:00:00"
  holding_days: 6
  min_premium_usd: 100000
  per_trade_cap: 0.30
  daily_gross_cap: 0.99
  max_trades_per_day: 5
  max_gross_leverage: 1.45
  min_cash_ratio: -0.50
  slippage: 0.001
  fee_per_share: 0.005
  fee_min: 1.0
  blacklist_days: 15
  allow_partial_scale_in: true
timezone:
  source: "Asia/Shanghai"
  trading: "America/New_York"
exec_fallbacks:
  quote_gap: "next_bar"
  exec_timeout: "amend_price"
  gateway_error: "retry_exp"
```

---

## 10. 关键时序（文字版）

**新信号 → 下单：**

1. `OptionWatcher` 解析 TXT → `SignalEvent`
2. `Repository.insert_raw_event_if_new()` → **入库幂等**
3. `Buffer.publish(ev)`
4. `TradingGuard.is_paused()?` → 若暂停跳过
5. `Strategy.on_signal(ev)` → 产出 `EntryDecision`
6. `Repository.reserve_daily_capacity(ratio)` → 成功才继续
7. `RiskSimulator.simulate_after_entry()` → 若不满足 → `scale_down_to_fit()`
8. `ExecPriceService.get_close_at()` → 按策略取价（含回退策略）
9. `OrderOMS.place_buy()` → `Repository.persist_order_event()`
10. 成交 `OrderResult` → `Repository.persist_open()` & `commit_daily_capacity()`
11. `AuditLog.append("ORDER_PLACED"/"ORDER_FILLED")`

**持仓巡检 → 平仓：**

1. `Repository.open_positions()`
2. `Strategy.on_position_check(pos)` → 命中 SL/TP/Timed 产出 `ExitDecision`
3. `OrderOMS.place_sell()` → `Repository.persist_order_event()`
4. 成交 → `Repository.persist_close()` → `Repository.add_blacklist(symbol, +15d)`
5. `AuditLog.append("EXIT_DECIDED"/"ORDER_FILLED")`

---

## 11. 对 Cursor 的落地建议

* 为每个接口文件生成**类/Protocol/抽象方法**的**空实现**（`pass`），并在 `README.md` 标出“先从 paper 模式打通”。
* 先实现：`tradingsystem.app → system → loops`（两个线程 + Buffer）与 `optionscreen.watcher → parser`（最小可用），`strategy.base/v6`（只返回决策，不下单）、`marketsource.exec_clock/feed_backtest`（回测取价），`db.repo`（SQLite 原型）。
* 逐步补：`RiskSimulator`、`reserve/commit capacity`、`AuditLog`、`Reconciler`、`Metrics/Alerts`、`TradingGuard`、`ConfigWatch`。
* 保持**接口不变**，实现可以演进替换（如 Buffer 从 queue 换成 Redis）。

---

如果你把这份文档放入仓库根目录的 `DESIGN.md`，并将每个接口文件建立**空类/抽象类**，Cursor 就能据此自动补全实现骨架。需要我把**空类模板**也列出文件与类签名清单的话，我可以再补一页“Cursor 生成提示卡”。
