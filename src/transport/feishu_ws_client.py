"""
飞书 WebSocket 长连接客户端

封装 lark_oapi.ws.Client，接收飞书事件回调。
通过 EventDispatcherHandler 注册消息事件处理器。
"""

import logging
import threading
from typing import Callable, Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

logger = logging.getLogger(__name__)


class FeishuWsClient:
    """飞书 WebSocket 长连接客户端

    使用 lark_oapi.ws.Client 建立长连接，接收消息事件。
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        bot_key: str,
        on_message: Optional[Callable] = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bot_key = bot_key
        self._on_message = on_message
        self._ws_client = None

    def _build_event_handler(self) -> lark.EventDispatcherHandler:
        """构建事件分发处理器"""
        handler = lark.EventDispatcherHandler.builder("", "", lark.LogLevel.INFO) \
            .register_p2_im_message_receive_v1(self._handle_message_event) \
            .build()
        return handler

    def _handle_message_event(self, data: P2ImMessageReceiveV1) -> None:
        """处理接收消息事件（同步回调，由 SDK 内部调用）"""
        if self._on_message:
            try:
                self._on_message(data)
            except Exception as e:
                logger.error("[FeishuWs:%s] 消息处理异常: %s", self.bot_key, e, exc_info=True)

    def start(self):
        """启动 WebSocket 长连接（阻塞）"""
        event_handler = self._build_event_handler()

        from lark_oapi.ws import Client as WsClient

        self._ws_client = WsClient(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
            auto_reconnect=True,
        )

        logger.info("[FeishuWs:%s] 启动 WebSocket 长连接...", self.bot_key)
        self._ws_client.start()  # 阻塞调用

    def start_in_thread(self) -> threading.Thread:
        """在独立线程中启动 WebSocket 长连接"""
        thread = threading.Thread(
            target=self.start,
            name=f"feishu-ws-{self.bot_key}",
            daemon=True,
        )
        thread.start()
        logger.info("[FeishuWs:%s] WebSocket 线程已启动", self.bot_key)
        return thread
