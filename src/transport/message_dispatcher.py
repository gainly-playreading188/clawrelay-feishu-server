"""
飞书消息分发器

接收飞书事件回调，路由到对应 handler 处理，
通过飞书 HTTP API 推送流式回复（500ms 节流编辑消息）。
"""

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from typing import Optional

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from config.bot_config import BotConfig
from src.adapters.feishu_api import FeishuAPI
from src.core.claude_relay_orchestrator import ClaudeRelayOrchestrator
from src.core.session_manager import SessionManager
from src.handlers.command_handlers import CommandRouter

logger = logging.getLogger(__name__)

_RELAY_CONNECTION_HINT = (
    "AI 服务暂时无法连接，请联系管理员检查：\n"
    "1. ClawRelay 服务是否正常运行\n"
    "2. bots.yaml 中的 relay_url 配置是否正确"
)
_RELAY_HTTP_ERROR_HINT = "AI 服务返回异常，请联系管理员检查 ClawRelay 服务状态。"

# 节流间隔(秒) - 飞书编辑消息 API 频率限制约 5次/秒
STREAM_THROTTLE_INTERVAL = 0.5


def _friendly_error(e: Exception) -> str:
    msg = str(e)
    if "[ClaudeRelay] Connection error" in msg:
        return _RELAY_CONNECTION_HINT
    if "[ClaudeRelay] HTTP" in msg:
        return _RELAY_HTTP_ERROR_HINT
    return "抱歉，处理出错，请稍后重试。"


class MessageDispatcher:
    """飞书消息分发与回复"""

    def __init__(self, bot_config: BotConfig, loop: asyncio.AbstractEventLoop):
        self.config = bot_config
        self.bot_key = bot_config.bot_key
        self._loop = loop

        # 飞书 HTTP API 客户端
        self.feishu_api = FeishuAPI(bot_config.app_id, bot_config.app_secret)

        # 命令路由器
        self.command_router = CommandRouter()

        # Claude Relay 编排器
        self.orchestrator = ClaudeRelayOrchestrator(
            bot_key=bot_config.bot_key,
            relay_url=bot_config.relay_url or "http://localhost:50009",
            working_dir=bot_config.working_dir or "",
            model=bot_config.model or "",
            system_prompt=bot_config.system_prompt or "",
            env_vars=bot_config.env_vars or None,
        )

        # 会话管理
        self.session_manager = SessionManager()

        # 机器人名称（用于过滤@提及）
        self.bot_name = bot_config.name or ""

        # 消息去重
        self._processed_msgids: dict[str, float] = {}

        # 加载自定义命令
        self._load_custom_commands()

        logger.info("[Dispatcher:%s] 初始化完成", self.bot_key)

    def _load_custom_commands(self):
        if not self.config.custom_commands:
            return
        for module_path in self.config.custom_commands:
            try:
                import importlib
                module = importlib.import_module(module_path)
                if hasattr(module, 'register_commands'):
                    module.register_commands(self.command_router)
                    logger.info("[Dispatcher:%s] 加载自定义命令: %s", self.bot_key, module_path)
            except Exception as e:
                logger.error("[Dispatcher:%s] 加载自定义命令失败: %s (%s)", self.bot_key, module_path, e)

    # ---- 事件入口（同步，由 SDK 线程调用） ----

    def on_message_event(self, data: P2ImMessageReceiveV1):
        """处理接收消息事件（同步入口，由飞书 SDK 回调线程调用）

        将异步处理任务调度到主事件循环。
        """
        logger.info("[Dispatcher:%s] on_message_event 被调用，准备调度异步任务", self.bot_key)
        future = asyncio.run_coroutine_threadsafe(
            self._handle_message_event(data),
            self._loop,
        )

        def _on_done(f):
            exc = f.exception()
            if exc:
                logger.error("[Dispatcher:%s] 异步任务异常: %s", self.bot_key, exc, exc_info=exc)

        future.add_done_callback(_on_done)

    # ---- 异步消息处理 ----

    async def _handle_message_event(self, data: P2ImMessageReceiveV1):
        """异步处理消息事件"""
        event = data.event
        message = event.message
        sender = event.sender

        message_id = message.message_id
        msg_type = message.message_type
        chat_id = message.chat_id
        chat_type = message.chat_type  # "p2p" | "group"
        open_id = sender.sender_id.open_id

        # 消息去重
        if message_id in self._processed_msgids:
            return
        self._processed_msgids[message_id] = time.time()
        self._cleanup_processed_msgids()

        session_key = chat_id if chat_type == "group" else open_id

        logger.info(
            "[Dispatcher:%s] 收到消息: msg_type=%s, user=%s, chat_type=%s, session_key=%s",
            self.bot_key, msg_type, open_id, chat_type, session_key
        )

        # 用户白名单检查
        if self.config.allowed_users and open_id not in self.config.allowed_users:
            logger.warning("[Dispatcher:%s] 用户 %s 不在白名单中", self.bot_key, open_id)
            await self.feishu_api.reply_text(message_id, "抱歉，您没有使用此机器人的权限。")
            return

        # 按消息类型路由
        if msg_type == "text":
            await self._handle_text(message_id, message, open_id, session_key, chat_type)
        elif msg_type == "post":
            await self._handle_post(message_id, message, open_id, session_key, chat_type)
        elif msg_type == "image":
            await self._handle_image(message_id, message, open_id, session_key, chat_type)
        elif msg_type == "file":
            await self._handle_file(message_id, message, open_id, session_key, chat_type)
        else:
            logger.warning("[Dispatcher:%s] 暂不支持的消息类型: %s", self.bot_key, msg_type)
            await self.feishu_api.reply_text(message_id, f"暂不支持处理 {msg_type} 类型的消息。")

    async def _handle_text(self, message_id: str, message, user_id: str, session_key: str, chat_type: str):
        """处理文本消息"""
        try:
            content_json = json.loads(message.content)
            content = content_json.get("text", "").strip()
        except (json.JSONDecodeError, AttributeError):
            content = ""

        if not content:
            return

        # 过滤 @机器人 前缀
        content = re.sub(r'@_user_\d+\s*', '', content).strip()
        if self.bot_name and content.startswith(f"@{self.bot_name}"):
            content = content[len(f"@{self.bot_name}"):].strip()

        if not content:
            return

        await self._handle_text_content(message_id, message, content, user_id, session_key, chat_type)

    async def _handle_post(self, message_id: str, message, user_id: str, session_key: str, chat_type: str):
        """处理富文本(post)消息，提取文本和图片"""
        try:
            content_json = json.loads(message.content)
        except (json.JSONDecodeError, AttributeError):
            await self.feishu_api.reply_text(message_id, "富文本消息解析失败，请重试。")
            return

        # 飞书 post content 结构: {"title": "...", "content": [[{tag, ...}, ...], ...]}
        # content 可能在 zh_cn / en_us / ja_jp 等语言 key 下
        post_body = content_json
        for lang_key in ("zh_cn", "en_us", "ja_jp"):
            if lang_key in content_json:
                post_body = content_json[lang_key]
                break

        title = post_body.get("title", "")
        paragraphs = post_body.get("content", [])

        text_parts = []
        image_keys = []

        if title:
            text_parts.append(title)

        for paragraph in paragraphs:
            for element in paragraph:
                tag = element.get("tag", "")
                if tag == "text":
                    text_parts.append(element.get("text", ""))
                elif tag == "a":
                    link_text = element.get("text", "")
                    href = element.get("href", "")
                    text_parts.append(f"{link_text}({href})" if href else link_text)
                elif tag == "img":
                    img_key = element.get("image_key", "")
                    if img_key:
                        image_keys.append(img_key)
                elif tag == "at":
                    # 跳过 @机器人 自身
                    pass

        text_content = "\n".join(text_parts).strip()
        # 过滤 @机器人 前缀
        text_content = re.sub(r'@_user_\d+\s*', '', text_content).strip()
        if self.bot_name and text_content.startswith(f"@{self.bot_name}"):
            text_content = text_content[len(f"@{self.bot_name}"):].strip()

        if not text_content and not image_keys:
            return

        # 如果有图片，走多模态处理
        if image_keys:
            content_blocks = []
            if text_content:
                content_blocks.append({"type": "text", "text": text_content})
            else:
                content_blocks.append({"type": "text", "text": "[用户发送了富文本消息，包含图片] 请描述或分析图片内容"})

            for img_key in image_keys:
                image_bytes = await self.feishu_api.download_resource(message_id, img_key, "image")
                if image_bytes:
                    b64 = base64.b64encode(image_bytes).decode("utf-8")
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    })

            stream_id = uuid.uuid4().hex[:12]
            log_context = {'chat_type': chat_type, 'message_type': 'post'}

            reply_msg_id = await self.feishu_api.reply_text(message_id, "正在分析消息...")
            if not reply_msg_id:
                return

            on_stream_delta = self._make_stream_delta_callback(reply_msg_id)

            try:
                await self.orchestrator.handle_multimodal_message(
                    user_id=user_id,
                    content_blocks=content_blocks,
                    stream_id=stream_id,
                    session_key=session_key,
                    log_context=log_context,
                    on_stream_delta=on_stream_delta,
                )
            except Exception as e:
                logger.error("[Dispatcher:%s] 处理富文本消息失败: %s", self.bot_key, e, exc_info=True)
                await self.feishu_api.edit_text(reply_msg_id, _friendly_error(e))
        else:
            # 纯文本富文本，当作普通文本处理
            await self._handle_text_content(message_id, message, text_content, user_id, session_key, chat_type)

    async def _handle_text_content(self, message_id: str, message, content: str, user_id: str, session_key: str, chat_type: str):
        """处理已提取的纯文本内容（供 _handle_text 和 _handle_post 复用）"""
        # 检查命令
        normalized = content.strip().lower()

        # 重置会话
        if normalized in ("reset", "new", "clear", "重置", "清空"):
            await self.session_manager.clear_session(self.bot_key, session_key)
            await self.feishu_api.reply_text(message_id, "会话已重置，可以开始新的对话。")
            return

        # 停止任务
        stop_msg = re.sub(r'[^\w\u4e00-\u9fff]', '', normalized)
        if stop_msg in ("stop", "停止", "暂停", "停"):
            from src.core.task_registry import get_task_registry
            cancelled, _ = get_task_registry().cancel(f"{self.bot_key}:{session_key}")
            if cancelled:
                await self.feishu_api.reply_text(message_id, "已停止当前任务。")
            else:
                await self.feishu_api.reply_text(message_id, "当前没有正在运行的任务。")
            return

        # 检查内置命令
        handler = self.command_router.handlers.get(content) or self.command_router.handlers.get(normalized)
        if handler:
            stream_id = uuid.uuid4().hex[:12]
            try:
                msg_json, _ = handler.handle(content, stream_id, user_id)
                msg_data = json.loads(msg_json)
                if msg_data.get("msgtype") == "stream":
                    text_content = msg_data.get("stream", {}).get("content", "")
                else:
                    text_content = str(msg_data)
                await self.feishu_api.reply_text(message_id, text_content)
            except Exception as e:
                logger.error("[Dispatcher:%s] 命令处理失败: %s", self.bot_key, e, exc_info=True)
                await self.feishu_api.reply_text(message_id, f"命令处理出错：{e}")
            return

        # 调用 AI 处理
        stream_id = uuid.uuid4().hex[:12]
        log_context = {
            'chat_type': chat_type,
            'chat_id': message.chat_id,
            'message_type': 'text',
        }

        reply_msg_id = await self.feishu_api.reply_text(message_id, "正在思考中...")
        if not reply_msg_id:
            logger.error("[Dispatcher:%s] 回复占位消息失败", self.bot_key)
            return

        on_stream_delta = self._make_stream_delta_callback(reply_msg_id)

        try:
            await self.orchestrator.handle_text_message(
                user_id=user_id,
                message=content,
                stream_id=stream_id,
                session_key=session_key,
                log_context=log_context,
                on_stream_delta=on_stream_delta,
            )
        except Exception as e:
            logger.error("[Dispatcher:%s] 处理文本消息失败: %s", self.bot_key, e, exc_info=True)
            await self.feishu_api.edit_text(reply_msg_id, _friendly_error(e))

    async def _handle_image(self, message_id: str, message, user_id: str, session_key: str, chat_type: str):
        """处理图片消息"""
        try:
            content_json = json.loads(message.content)
            image_key = content_json.get("image_key", "")
        except (json.JSONDecodeError, AttributeError):
            image_key = ""

        if not image_key:
            await self.feishu_api.reply_text(message_id, "图片获取失败，请重试。")
            return

        # 下载图片
        image_bytes = await self.feishu_api.download_resource(message_id, image_key, "image")
        if not image_bytes:
            await self.feishu_api.reply_text(message_id, "图片下载失败，请重试。")
            return

        # 编码为 data URI
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:image/png;base64,{b64}"

        content_blocks = [
            {"type": "text", "text": "[用户发送了一张图片] 请描述或分析这张图片"},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]

        stream_id = uuid.uuid4().hex[:12]
        log_context = {'chat_type': chat_type, 'message_type': 'image'}

        reply_msg_id = await self.feishu_api.reply_text(message_id, "正在分析图片...")
        if not reply_msg_id:
            return

        on_stream_delta = self._make_stream_delta_callback(reply_msg_id)

        try:
            await self.orchestrator.handle_multimodal_message(
                user_id=user_id,
                content_blocks=content_blocks,
                stream_id=stream_id,
                session_key=session_key,
                log_context=log_context,
                on_stream_delta=on_stream_delta,
            )
        except Exception as e:
            logger.error("[Dispatcher:%s] 处理图片消息失败: %s", self.bot_key, e, exc_info=True)
            await self.feishu_api.edit_text(reply_msg_id, _friendly_error(e))

    async def _handle_file(self, message_id: str, message, user_id: str, session_key: str, chat_type: str):
        """处理文件消息"""
        try:
            content_json = json.loads(message.content)
            file_key = content_json.get("file_key", "")
            file_name = content_json.get("file_name", "unknown")
        except (json.JSONDecodeError, AttributeError):
            file_key = ""
            file_name = "unknown"

        if not file_key:
            await self.feishu_api.reply_text(message_id, "文件获取失败，请重试。")
            return

        file_bytes = await self.feishu_api.download_resource(message_id, file_key, "file")
        if not file_bytes:
            await self.feishu_api.reply_text(message_id, "文件下载失败，请重试。")
            return

        # 编码为 data URI
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        import mimetypes
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        file_data = {
            "type": "file_url",
            "file_url": {
                "url": f"data:{mime_type};base64,{b64}",
                "filename": file_name,
            },
        }

        stream_id = uuid.uuid4().hex[:12]
        log_context = {
            'chat_type': chat_type,
            'message_type': 'file',
            'file_info': [{'filename': file_name}],
        }

        reply_msg_id = await self.feishu_api.reply_text(message_id, f"正在分析文件: {file_name}...")
        if not reply_msg_id:
            return

        on_stream_delta = self._make_stream_delta_callback(reply_msg_id)

        try:
            await self.orchestrator.handle_file_message(
                user_id=user_id,
                message=f"[用户发送了文件: {file_name}] 请分析这个文件的内容。",
                files=[file_data],
                stream_id=stream_id,
                session_key=session_key,
                log_context=log_context,
                on_stream_delta=on_stream_delta,
            )
        except Exception as e:
            logger.error("[Dispatcher:%s] 处理文件消息失败: %s", self.bot_key, e, exc_info=True)
            await self.feishu_api.edit_text(reply_msg_id, _friendly_error(e))

    # ---- 流式推送（通过编辑消息实现） ----

    def _make_stream_delta_callback(self, reply_msg_id: str):
        """创建带节流的 on_stream_delta 回调

        通过反复编辑已发送的消息来模拟流式效果。
        """
        state = {
            'last_pushed_text': "",
            'last_push_time': 0.0,
            'throttle_task': None,
        }
        push_lock = asyncio.Lock()

        async def on_stream_delta(accumulated_text: str, finish: bool):
            if finish:
                if state['throttle_task'] and not state['throttle_task'].done():
                    state['throttle_task'].cancel()
                await self.feishu_api.edit_text(reply_msg_id, accumulated_text)
                state['last_pushed_text'] = accumulated_text
                return

            now = time.monotonic()
            elapsed = now - state['last_push_time']

            if elapsed >= STREAM_THROTTLE_INTERVAL and accumulated_text != state['last_pushed_text']:
                async with push_lock:
                    await self.feishu_api.edit_text(reply_msg_id, accumulated_text)
                    state['last_pushed_text'] = accumulated_text
                    state['last_push_time'] = time.monotonic()
            elif state['throttle_task'] is None or state['throttle_task'].done():
                captured_text = accumulated_text

                async def delayed_push():
                    await asyncio.sleep(STREAM_THROTTLE_INTERVAL - elapsed)
                    async with push_lock:
                        if captured_text != state['last_pushed_text']:
                            await self.feishu_api.edit_text(reply_msg_id, captured_text)
                            state['last_pushed_text'] = captured_text
                            state['last_push_time'] = time.monotonic()

                state['throttle_task'] = asyncio.create_task(delayed_push())

        return on_stream_delta

    # ---- 工具方法 ----

    def _cleanup_processed_msgids(self):
        now = time.time()
        expired = [k for k, v in self._processed_msgids.items() if now - v > 300]
        for k in expired:
            del self._processed_msgids[k]
