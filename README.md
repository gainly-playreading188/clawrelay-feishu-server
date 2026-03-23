# ClawRelay Feishu Server

让飞书机器人接入 AI —— 三步启动，开箱即用。

![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)
![License MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

```
飞书用户发消息 → 本服务 WebSocket 接收 → clawrelay-api → Claude Code 处理 → 流式回复推送
```

**无需公网 IP**，无需回调 URL，无需数据库。通过飞书官方 SDK WebSocket 长连接接收消息，YAML 配置即用。

---

## 30 秒了解

你需要准备：

1. **飞书自建应用**的 `App ID` 和 `App Secret`（从[飞书开放平台](https://open.feishu.cn/) → 开发者后台 → 创建应用 获取）
2. **[clawrelay-api](https://github.com/roodkcab/clawrelay-api)** 运行在本机（默认端口 50009）

然后：

```bash
git clone https://github.com/wxkingstar/clawrelay-feishu-server.git
cd clawrelay-feishu-server
pip install -r requirements.txt
python main.py
```

首次启动会自动进入**配置向导**，按提示填入 `App ID` 和 `App Secret` 即可：

```
==================================================
飞书机器人配置向导
==================================================

请输入飞书应用 App ID: __________
请输入飞书应用 App Secret: __________
请输入 ClawRelay API 地址 [http://localhost:50009]: __________
请输入 Claude 工作目录 [留空使用默认]: __________

配置已保存到 config/bots.yaml
```

配置完成，服务自动启动 WebSocket 连接。去飞书给机器人发条消息试试吧。

---

## Docker 部署

```bash
git clone https://github.com/wxkingstar/clawrelay-feishu-server.git
cd clawrelay-feishu-server

# 编辑配置（Docker 中不支持交互式向导，需提前填写）
cp config/bots.yaml.example config/bots.yaml
vim config/bots.yaml

docker compose up -d
```

> Docker 模式下 `relay_url` 需使用 `http://host.docker.internal:50009`（而非 `localhost`）连接宿主机的 clawrelay-api。

```bash
docker compose logs -f app   # 查看日志
docker compose down           # 停止
```

---

## 功能一览

| 特性 | 说明 |
|------|------|
| **WebSocket 长连接** | 基于飞书官方 SDK，无需公网 IP、回调 URL |
| **零外部依赖** | 无数据库，YAML 配置 + 内存会话 + JSONL 日志 |
| **首次配置向导** | 启动即引导，无需手动编辑配置文件 |
| **多机器人** | 一个服务托管多个机器人，YAML 中加一段配置即可 |
| **流式回复** | 500ms 节流编辑消息，实时展示 AI 回复 |
| **多模态** | 文本 / 富文本(post) / 图片 / 文件 |
| **会话管理** | 自动过期，发送 `reset` 或 `清空` 手动重置 |
| **自定义命令** | 模块化扩展，动态加载 |
| **用户白名单** | 按机器人维度的访问控制 |

---

## 配置说明

配置文件：`config/bots.yaml`

```yaml
bots:
  my_bot:
    # === 必填 ===
    app_id: "YOUR_APP_ID"
    app_secret: "YOUR_APP_SECRET"
    relay_url: "http://localhost:50009"    # Docker 中改为 http://host.docker.internal:50009

    # === 可选 ===
    name: "My Bot"                         # 机器人名称（群聊中过滤 @提及）
    description: "My AI assistant"
    working_dir: "/path/to/project"        # Claude 工作目录
    model: "claude-sonnet-4-6"             # 模型名称
    system_prompt: "You are a helpful assistant."

    allowed_users:                          # 用户白名单（不设 = 不限制）
      - "ou_xxxxxxxxxxxx"

    env_vars:                               # 注入 Claude 子进程的环境变量
      MY_API_KEY: "xxx"

    custom_commands:                        # 自定义命令模块
      - "src.handlers.custom.demo_commands"
```

添加多个机器人只需在 `bots:` 下增加新的配置块，重启生效。

---

## 飞书应用配置

1. 登录[飞书开放平台](https://open.feishu.cn/)，创建企业自建应用
2. 在「凭证与基础信息」中获取 `App ID` 和 `App Secret`
3. 在「权限管理」中开通以下权限：
   - `im:message` — 获取与发送单聊、群组消息
   - `im:message.group_at_msg` — 接收群聊中 @ 机器人消息
   - `im:resource` — 获取消息中的资源文件（图片、文件）
4. 在「事件与回调」中添加事件：
   - `im.message.receive_v1` — 接收消息
5. 启用「长连接」模式（无需配置回调 URL）
6. 发布应用版本

---

## 自定义命令

在 `src/handlers/custom/` 下创建 Python 文件：

```python
from src.handlers.command_handlers import CommandHandler

class PingCommandHandler(CommandHandler):
    command = "ping"
    description = "Check if the bot is alive"

    def handle(self, cmd, stream_id, user_id):
        return "Pong!", None

def register_commands(command_router):
    command_router.register(PingCommandHandler())
```

在 `config/bots.yaml` 中添加模块路径后重启即可。

---

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `BOT_CONFIG_PATH` | 配置文件路径 | `config/bots.yaml` |
| `CHAT_LOG_DIR` | 聊天日志目录 | `logs` |

---

## 架构

```
┌──────────┐  WebSocket  ┌─────────────────────────┐   SSE    ┌───────────────┐
│   飞书    │ <────────> │  ClawRelay Feishu Server │ ──────> │ clawrelay-api │
│          │  长连接      │  (Python asyncio)        │ <────── │ (Go :50009)   │
└──────────┘  (lark SDK) └─────────────────────────┘  流式响应 └───────┬───────┘
                                                                       │
                                                                       v
                                                              ┌───────────────┐
                                                              │  Claude Code  │
                                                              └───────────────┘
```

- **WebSocket 长连接**：通过飞书官方 `lark-oapi` SDK 建立长连接，自动心跳保活与断线重连
- **流式回复**：先回复占位消息，再通过编辑消息 API 实现 500ms 节流的流式更新
- **会话管理**：每个用户/群聊独立会话，内存存储，自动过期

<details>
<summary>项目结构</summary>

```
clawrelay-feishu-server/
├── main.py                              # 入口（asyncio，per-bot WebSocket）
├── config/
│   ├── bots.yaml.example               # 机器人配置模板（复制为 bots.yaml 使用）
│   └── bot_config.py                   # 配置加载 & 首次向导
├── src/
│   ├── adapters/
│   │   ├── feishu_api.py               # 飞书 HTTP API 客户端（回复/编辑/下载）
│   │   └── claude_relay_adapter.py     # clawrelay-api SSE 客户端
│   ├── transport/
│   │   ├── feishu_ws_client.py         # 飞书 WebSocket 长连接（lark SDK 封装）
│   │   └── message_dispatcher.py       # 消息路由、节流推送
│   ├── core/
│   │   ├── claude_relay_orchestrator.py # AI 调用编排
│   │   ├── session_manager.py          # 会话管理（内存，自动过期）
│   │   ├── chat_logger.py             # 聊天日志（JSONL）
│   │   └── task_registry.py           # 异步任务注册表
│   ├── handlers/
│   │   └── command_handlers.py         # 内置命令（help, reset 等）
│   └── utils/
│       ├── text_utils.py               # 文本处理
│       └── logging_config.py           # 日志配置
├── logs/                                # 聊天日志（chat.jsonl）
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

</details>

<details>
<summary>消息处理流程</summary>

```
用户发送消息
    │
    v
飞书 WebSocket 推送
    │
    v
消息路由 ─── text ────> 命令检查 ─── 匹配 ──> 执行命令（reset, help, 自定义...）
    │                        │
    │                     不匹配
    │                        v
    │              ClaudeRelayOrchestrator
    │                        │
    │                        ├── 获取/创建会话
    │                        ├── SSE 流式调用 clawrelay-api
    │                        ├── 500ms 节流编辑消息推送
    │                        └── 记录聊天日志
    │
    ├── post  ──> 提取文本+图片 → 纯文本走 text / 含图走多模态
    ├── image ──> 下载图片 → 多模态分析
    └── file  ──> 下载文件 → 内容分析
```

</details>

---

## License

[MIT](LICENSE)
