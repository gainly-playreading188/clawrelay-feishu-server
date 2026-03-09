"""
命令处理器模块

处理文本命令并返回消息内容。
飞书版简化了命令集，移除企业微信特有的模板卡片命令。
"""

import json
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class CommandHandler:
    def handle(self, cmd: str, stream_id: str, user_id: str) -> tuple[str, None]:
        raise NotImplementedError


class HelpCommandHandler(CommandHandler):
    def handle(self, cmd: str, stream_id: str, user_id: str) -> tuple[str, None]:
        help_text = """ClawRelay Bot - 可用命令

基本命令:
  hello - 问候
  help / 帮助 / ? - 显示帮助

会话管理:
  reset / 重置 / 清空 - 重置当前会话
  stop / 停止 - 停止当前任务

直接发送文本即可与 AI 对话。"""
        return _make_stream_msg(stream_id, help_text), None


class HelloCommandHandler(CommandHandler):
    def handle(self, cmd: str, stream_id: str, user_id: str) -> tuple[str, None]:
        reply_content = f"你好 {user_id}！很高兴为你服务。"
        return _make_stream_msg(stream_id, reply_content), None


class CommandRouter:
    def __init__(self):
        self.handlers: Dict[str, CommandHandler] = {
            "help": HelpCommandHandler(),
            "帮助": HelpCommandHandler(),
            "?": HelpCommandHandler(),
            "？": HelpCommandHandler(),
            "hello": HelloCommandHandler(),
        }

    def register(self, handler: CommandHandler):
        cmd_name = getattr(handler, 'command', None)
        if cmd_name:
            self.handlers[cmd_name] = handler


def _make_stream_msg(stream_id: str, content: str) -> str:
    """构造与企业微信版兼容的消息格式"""
    return json.dumps({
        "msgtype": "stream",
        "stream": {
            "id": stream_id,
            "finish": True,
            "content": content,
        },
    }, ensure_ascii=False)
