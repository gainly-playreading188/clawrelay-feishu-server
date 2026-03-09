"""
飞书 HTTP API 封装

封装飞书消息相关的 HTTP API，包括：
- 回复消息（reply）
- 编辑消息（update）— 用于流式更新
- 发送消息（create）
- 下载资源（图片/文件）
"""

import json
import logging
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    UpdateMessageRequest,
    UpdateMessageRequestBody,
    GetMessageResourceRequest,
)

logger = logging.getLogger(__name__)


class FeishuAPI:
    """飞书消息 API 封装"""

    def __init__(self, app_id: str, app_secret: str):
        self.client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()
        logger.info("[FeishuAPI] 初始化完成")

    async def reply_text(self, message_id: str, text: str) -> Optional[str]:
        """回复文本消息

        Args:
            message_id: 要回复的消息ID
            text: 回复文本

        Returns:
            回复消息的 message_id，失败返回 None
        """
        content = json.dumps({"text": text})
        request = ReplyMessageRequest.builder() \
            .message_id(message_id) \
            .request_body(ReplyMessageRequestBody.builder()
                          .msg_type("text")
                          .content(content)
                          .build()) \
            .build()

        response = self.client.im.v1.message.reply(request)
        if not response.success():
            logger.error(
                "[FeishuAPI] 回复消息失败: code=%d, msg=%s",
                response.code, response.msg
            )
            return None

        reply_msg_id = response.data.message_id
        logger.info("[FeishuAPI] 回复消息成功: reply_msg_id=%s", reply_msg_id)
        return reply_msg_id

    async def edit_text(self, message_id: str, text: str) -> bool:
        """编辑文本消息（用于流式更新）

        Args:
            message_id: 要编辑的消息ID
            text: 新的文本内容

        Returns:
            是否成功
        """
        content = json.dumps({"text": text})
        request = UpdateMessageRequest.builder() \
            .message_id(message_id) \
            .request_body(UpdateMessageRequestBody.builder()
                          .msg_type("text")
                          .content(content)
                          .build()) \
            .build()

        response = self.client.im.v1.message.update(request)
        if not response.success():
            logger.warning(
                "[FeishuAPI] 编辑消息失败: code=%d, msg=%s, message_id=%s",
                response.code, response.msg, message_id
            )
            return False
        return True

    async def send_text(self, receive_id: str, text: str, receive_id_type: str = "chat_id") -> Optional[str]:
        """主动发送文本消息

        Args:
            receive_id: 接收方ID
            text: 文本内容
            receive_id_type: ID类型（chat_id / open_id / user_id）

        Returns:
            消息ID，失败返回 None
        """
        content = json.dumps({"text": text})
        request = CreateMessageRequest.builder() \
            .receive_id_type(receive_id_type) \
            .request_body(CreateMessageRequestBody.builder()
                          .receive_id(receive_id)
                          .msg_type("text")
                          .content(content)
                          .build()) \
            .build()

        response = self.client.im.v1.message.create(request)
        if not response.success():
            logger.error(
                "[FeishuAPI] 发送消息失败: code=%d, msg=%s",
                response.code, response.msg
            )
            return None

        msg_id = response.data.message_id
        logger.info("[FeishuAPI] 发送消息成功: msg_id=%s", msg_id)
        return msg_id

    async def download_resource(self, message_id: str, file_key: str, resource_type: str = "image") -> Optional[bytes]:
        """下载消息中的资源文件（图片/文件）

        Args:
            message_id: 消息ID
            file_key: 资源文件key
            resource_type: 资源类型（image / file）

        Returns:
            文件字节数据，失败返回 None
        """
        request = GetMessageResourceRequest.builder() \
            .message_id(message_id) \
            .file_key(file_key) \
            .type(resource_type) \
            .build()

        response = self.client.im.v1.message_resource.get(request)
        if not response.success():
            logger.error(
                "[FeishuAPI] 下载资源失败: code=%d, msg=%s, file_key=%s",
                response.code, response.msg, file_key
            )
            return None

        logger.info("[FeishuAPI] 下载资源成功: file_key=%s", file_key)
        return response.file.read()
