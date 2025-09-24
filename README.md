# AnyRouter 自动签到脚本

本项目实现了 `prd.md` 中描述的 AnyRouter 自动签到 MVP：
Playwright 持久化浏览器会话、结构化日志、失败告警邮件、`systemd timer` 调度与 CSV 历史环形缓冲。

## 目录结构

```
config.toml             # 单文件配置（时区/调度/SMTP/选择器）
src/                    # Python 模块（授权、签到、工具函数）
data/userdata/          # Playwright 持久化用户目录
/data/history.csv       # 签到/授权历史，环切保留
/data/logs/             # JSONL 结构化日志（带轮转）
screenshots/            # 失败截图
systemd/anyrouter.*     # systemd service + timer
```

## 环境准备

1. 安装 Python 3.11+ 与 [Playwright for Python](https://playwright.dev/python/)。
2. 运行 `pip install -r requirements.txt`（如使用 Poetry，请相应调整）。
3. 初始化 Playwright 浏览器驱动：
   ```bash
   playwright install chromium
   ```
4. 根据实际账号信息编辑 `config.toml`：
   * 更新 SMTP 主机、账号、收件人；
   * 如果站点文案/选择器有变化，调整 `[selectors]` 中的策略；
   * 根据需求修改重试、超时与调度时间。

## 首次授权（GitHub OAuth）

按照 PRD §3.1，首次需要人工完成 GitHub 授权以写入 `data/userdata/`。

```bash
python -m src.authorize
```

脚本会拉起 Chromium 持久化上下文，请在弹出的浏览器中完成登录，终端按提示回车即可。
成功后：

* `data/userdata/` 和 `data/auth_state.json` 记录会话；
* `data/history.csv` 新增一条 `AUTH_OK` 记录；
* 日志写入 `data/logs/signin.jsonl`。

## 手动执行签到

```bash
python -m src.signin
```

行为与 PRD §3.2–§3.5 对应：

* 复用 `data/userdata/` 自动检测登录态；
* 失败最多重试 3 次，指数退避（1s/4s/9s，可在配置中调整）；
* 失败立即截图保存至 `screenshots/` 并发送邮件；
* 当日首次成功才会发送成功邮件，其余成功只记录日志/历史；
* `data/history.csv` 按 `history_limit` 环形裁剪，默认保留 1000 条。

## 通知策略

`src/notifier_email.py` 聚合逻辑满足 PRD §3.4：

* `[notify.success_email_once_per_day] = true` 时，每日成功邮件仅发送一次（基于 `data/meta/last_success_email.json`）；
* `[notify.email_on_failure_always] = true` 时，任何失败都会即刻发送告警邮件，并附带失败截图。

若不需要邮件，可将 `notify.enable_email` 设为 `false`。

## 调度方式

### systemd timer（推荐，PRD §3.3 / §6）

1. 修改 `systemd/anyrouter.service` 中的安装路径、运行用户；
2. 拷贝到系统目录并启用：
   ```bash
   sudo cp systemd/anyrouter.* /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now anyrouter.timer
   sudo systemctl list-timers | grep anyrouter
   ```

`anyrouter.timer` 默认每天 08:30/12:30/20:30（`Europe/Helsinki`），并且 `Persistent=true` 支持补跑。

### cron（备选）

参考 PRD §8.2：

```bash
30 8,12,20 * * * /usr/bin/python3 /opt/anyrouter-auto/src/signin.py >> /opt/anyrouter-auto/data/logs/cron.out 2>&1
```

请确保系统时区与 `config.toml` 中保持一致，或在环境变量中设置 `TZ`。

## 日志与数据

* **JSONL 日志**：`src/logging_setup.py` 以轮转方式输出结构化日志（字段包含 `ts/run_id/step/error_code/...`）。
* **历史记录**：`src/utils.append_history_entry` 维护环形 `history.csv`，字段为 `ts,run_id,stage,result,error_code,retry_count,duration_ms,notes`。
* **截图**：失败时在 `screenshots/{timestamp}_{run_id}_a{attempt}_{error}.png` 中留存，可随邮件发送。

## 错误码对照

| 错误码 | 说明 | 常见原因 | 建议 |
| ------ | ---- | -------- | ---- |
| `NEED_AUTH` | 会话失效，需重新执行 `python -m src.authorize` | Cookie 过期 / SSO / 风控 | 重新授权 |
| `NAV_TIMEOUT` | 页面加载超时 | 网络慢、站点异常 | 检查网络或调大 `nav_timeout_ms` |
| `SELECTOR_CHANGED` | 无法定位签到控件 | 前端改版 | 更新 `config.toml` 中的选择器 |
| `CAPTCHA` | 如站点加入人机校验，可在此扩展 | 频率过高 | 人工介入 |
| `UNKNOWN` | 未归类的异常 | —— | 查看截图与日志 |

## 故障排查

1. 检查 `data/logs/signin.jsonl` 是否有结构化错误信息；
2. 若失败邮件未收到，请确认 SMTP 配置是否正确；
3. 若 systemd 没有触发，使用 `systemctl status anyrouter.timer` 查看状态，并确认 `TZ` 一致；
4. 当页面元素改动时，更新 `config.toml` 中 `[selectors]`，可使用多策略定位（CSS / text / role）。

## 安全提示

* `config.toml` 中的 SMTP 凭据应限制权限（推荐 600）；
* `data/userdata/` 与日志目录建议仅授权运行用户访问；
* 日志中不记录敏感信息，邮件地址等会在应用中做必要的脱敏或避免输出。

## 开发者笔记

* `src/state_check.py` 负责登录态与签到结果检测，可按需扩展更多错误码；
* `src/utils.py` 的 `SignInError` 支持携带截图路径与 `retryable` 标记，便于统一处理；
* 若需要开启 Playwright trace，可将 `run.trace_on_failure` 设为 `true` 并在 `_attempt_checkin` 中扩展保存逻辑。

