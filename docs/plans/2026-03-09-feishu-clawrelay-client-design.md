# Feishu Clawrelay Client Design

## Overview

基于企业微信 Clawrelay 客户端 (`clawrelay-wecom-server`)，实现飞书版本的 Clawrelay 客户端。使用飞书官方 Python SDK (`lark_oapi`) 的 WebSocket 长连接模式接收消息，通过 HTTP API 回复/编辑消息，连接 `clawrelay-api` 实现 AI 对话。

## Architecture

```
Feishu WebSocket (lark_oapi.ws.Client, protobuf frames)
    |
EventDispatcher (P2ImMessageReceiveV1)
    |
MessageDispatcher
    |-- Command handlers (help, reset, stop)
    |-- Text -> ClaudeRelayOrchestrator
    |-- Image -> download via API -> ClaudeRelayOrchestrator
    |-- File -> download via API -> ClaudeRelayOrchestrator
            |
    ClaudeRelayAdapter (SSE to clawrelay-api)
            |
    Streaming reply -> edit message API -> Feishu chat
                    (lark_oapi.Client HTTP API)
```

## Key Differences from WeChat Work Version

| Feature | WeChat Work | Feishu |
|---------|-------------|--------|
| Receive | Direct WebSocket (`aibot_msg_callback`) | `lark_oapi.ws.Client` (protobuf) |
| Reply | Same WebSocket (`aibot_respond_msg`) | HTTP API (`/open-apis/im/v1/messages`) |
| Streaming | Native stream message | Edit message repeatedly (500ms throttle) |
| Auth | bot_id + secret in WebSocket | app_id + app_secret (SDK manages token) |
| Media | AES-256-CBC decrypt | API download (image_key / file_key) |

## Project Structure

```
clawrelay-feishu-server/
├── main.py
├── config/
│   ├── bot_config.py
│   └── bots.yaml
├── src/
│   ├── transport/
│   │   ├── feishu_ws_client.py
│   │   └── message_dispatcher.py
│   ├── core/
│   │   ├── claude_relay_orchestrator.py
│   │   ├── session_manager.py
│   │   ├── chat_logger.py
│   │   └── task_registry.py
│   ├── adapters/
│   │   ├── claude_relay_adapter.py
│   │   └── feishu_api.py
│   ├── handlers/
│   │   └── command_handlers.py
│   └── utils/
│       ├── text_utils.py
│       └── logging_config.py
├── logs/
├── requirements.txt
└── docker-compose.yml
```

## Config Format (bots.yaml)

```yaml
bots:
  default:
    app_id: "cli_xxxxx"
    app_secret: "xxxxx"
    relay_url: "http://localhost:50009"
    name: "AI Assistant"
    working_dir: "/path/to/project"
    model: "vllm/claude-sonnet-4-6"
    system_prompt: "You are a helpful assistant."
    allowed_users: []
    env_vars: {}
```

## Streaming Reply Strategy

1. User sends message -> event callback
2. Reply placeholder: "Thinking..." (POST /messages/:msg_id/reply)
3. Get reply_message_id
4. SSE stream from clawrelay-api
5. Every 500ms, edit message (PUT /messages/:reply_message_id)
6. Stream ends -> final edit

## Session Key Rules

- P2P: `{bot_key}_{open_id}`
- Group: `{bot_key}_{chat_id}`

## Reused Modules (from wecom version)

- `claude_relay_adapter.py` - SSE client (direct reuse)
- `claude_relay_orchestrator.py` - AI orchestration (minor adaptation)
- `session_manager.py` - Session management (direct reuse)
- `chat_logger.py` - JSONL logging (direct reuse)
- `task_registry.py` - Async task registry (direct reuse)
- `text_utils.py` - Text processing (direct reuse)
- `command_handlers.py` - Command routing (adapted)

## New Modules

- `feishu_ws_client.py` - Wraps lark_oapi.ws.Client
- `feishu_api.py` - Feishu HTTP API (send/edit/download)
- `message_dispatcher.py` - Rewritten for Feishu event format

## Dependencies

- lark-oapi - Feishu official SDK (WebSocket + HTTP API)
- aiohttp - SSE streaming to clawrelay-api
- pyyaml - Config parsing
- python-dotenv - .env support
