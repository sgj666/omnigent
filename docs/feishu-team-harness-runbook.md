# Feishu Team Harness 本地运行与验收手册

本文是开发/验收环境的操作手册。生产环境请把数据库、密钥和日志交给
平台的 secret manager，不要把下面的示例值提交到 Git。

## 1. 迁移与启动

在仓库根目录执行：

```bash
.venv/bin/python -m alembic -c omnigent/db/alembic.ini upgrade head
.venv/bin/python -m alembic -c omnigent/db/alembic.ini check
omnigent server --background
omnigent server status
```

本地 Web UI 默认地址是 `http://localhost:6767`。如果使用源码启动 Web
开发服务器，另开终端执行 `pnpm --dir web dev`（Node 20 是当前前端工具链的
要求）。后端 Host 必须单独注册；本机 Host 的最小流程是：

```bash
omnigent host                 # 本地 server
# 远程 server 则使用：omnigent host https://your-server.example
```

`omnigent stop` 可停止本地 server/host。迁移失败时先确认数据库 URL 指向
测试库或开发库，再检查 Alembic 当前 revision；不要在未知生产库上执行
`downgrade`。

## 2. 飞书环境与扫码安装

在启动 server 的环境注入（值从 secret manager 或一次性 shell 环境提供）：

```bash
export OMNIGENT_DATABASE_URI='sqlite:///./omnigent-dev.db'
export OMNIGENT_AUTH_PROVIDER='header'
export OMNIGENT_LOCAL_SINGLE_USER='1'
export OMNIGENT_ACCOUNTS_COOKIE_SECRET='change-me-in-a-secret-store'
export OMNIGENT_FEISHU_API_BASE_URL='https://open.feishu.cn'   # 可选，测试可指向 fake
export OMNIGENT_FEISHU_SIGNING_SECRET='provider-verification-secret'  # 可选
```

Device Flow 不要求把 App Secret 写入配置文件：在 Team 页面点击“连接飞书”，
后端调用 PersonalAgent registration API，UI 仅显示一次性的
`verification_uri_complete` 二维码。使用要绑定的飞书账号扫码并批准权限，
随后按服务端返回的 `interval` 轮询状态。成功后会记录安装者 `open_id`、Bot
信息和加密后的凭证，并自动初始化 `omnigent-team` Surface。

Surface 能力探测成功时显示应用级菜单；租户菜单 API 不可用时状态为
`partial`，改用常驻“Omnigent 工作台”交互卡片。重复扫码或点击“重新初始化
工作台”是幂等的，不会创建第二套 Surface。

## 3. 创建 Team、注册工作区与多仓验证

1. 在 Web UI 的 Teams 一级导航创建 Team，指定且仅指定一个 Coordinator。
   添加 Worker Profiles（能力标签、并发上限、失败通知级别），并为 Team 绑定
   Feishu installation。
2. 在 Workspaces 注册需求目录。目录可以不是 Git 仓库；一级子目录中的每个
   独立 Git 仓库作为 `expertProjects`。有清单时提交
   `.workbench-workspace.json`，并确认路径没有 `..`、绝对路径或嵌套仓库。
3. 在 Team 详情选择 Workspace Bundle，执行模式选 `auto`，仓库默认 `all`，
   Host 选 `auto`。
4. 从绑定群聊或话题发送需求文本。Adapter 按 `chat_id/thread_id` 找到 Team，
   将普通文本、`@Worker` 文本和卡片动作全部转换成 Coordinator 请求；Worker
   不会获得绕过 Coordinator 的入站入口。
5. 在 Run Inspector 核对不可变的 `workspace_id`、Task DAG、每个 Attempt 的
   Profile/worktree、stdout/stderr、Parent Inbox 事件、提交和产物。多仓并行
   验收可运行：

```bash
.venv/bin/python -m pytest tests/e2e/test_feishu_team_harness.py -q
```

## 4. 失败码与恢复动作

| failure_code | 含义 | 下一步 |
| --- | --- | --- |
| `DEVICE_FLOW_EXPIRED` | 二维码会话超时 | 重新点击连接并在 `expires_in` 内扫码 |
| `WS_DISCONNECTED` | WebSocket 断线/心跳失败 | 检查网络与签名配置；Adapter 会重连，确认重连计数和事件 |
| `DUPLICATE_CARD` | 相同 `action_id + nonce` 重复投递 | 无需人工重试；检查 Ledger 幂等键，第二次应返回第一次结果 |
| `WORKER_PROCESS_EXIT_1` | Worker 进程以非零码退出 | 打开 Attempt 日志，按建议动作 retry；超过次数则处理 Hard Block |
| `COORDINATOR_RESTART_RECOVERY` | Coordinator 重启后的恢复标记 | 从 Durable Ledger 重放事件，确认未重复创建 Attempt/通知 |
| `LEASE_EXPIRED` | Host 心跳过期 | 先确认 owner，再回收过期 worktree；reconciler 完成后重新调度 |
| `MENU_UNAVAILABLE` | 应用级菜单 API 无权限 | 接受 `partial`，使用常驻工作台卡片；修复权限后可重新初始化 |
| `RUNNING_WORKSPACE_SWITCH_REJECTED` | 运行中切换工作区 | 这是保护行为；切换仅影响该话题后续新 Run |

每种失败都应在 Inspector 和飞书通知中同时出现 failure code、Run/Attempt
上下文和下一步动作。日志只引用 `log_ref`，不要把 Provider 原始 secret 或
请求体直接写入日志。

## 5. 日志、重连与安全边界

- 查看 server/Coordinator 日志：`omnigent server logs`（或部署平台的应用
  日志）；Host 日志在运行 Host 的终端/服务日志中。
- 断线后先确认 WebSocket 心跳恢复，再检查 Adapter 的发送重试；不要通过重复
  点击卡片来“催促”任务。
- Lease recovery 必须校验 owner，回收后确认 sibling repository 的 Git 状态
  未被修改；运行中的 Run 的 `workspace_id` 永远不变。
- App Secret 仅在 Device Flow 成功返回到加密存储的短暂窗口存在。禁止将
  `client_secret`、解密密钥或 token 写入 Agent Profile、Prompt、
  `.workbench-workspace.json`、任何 Git 仓库、提交信息或聊天消息。Profile
  只保存显示身份、能力和通知偏好。

## 6. 验收命令

后端与静态检查：

```bash
.venv/bin/python -m pytest tests -q
git diff --check
.venv/bin/python -m alembic -c omnigent/db/alembic.ini check
```

前端（要求 Node 20）：

```bash
node --version
pnpm --dir web test --run
pnpm --dir web lint
```

如果本机 Node 版本低于 20，记录为环境限制并在 Node 20 CI/开发容器中运行，
不要把“未执行”报告为通过。网络不可用时，使用本仓库的
`tests/fixtures/fake_lark.py` 与 `tests/fixtures/fake_host.py` 运行离线验收。

