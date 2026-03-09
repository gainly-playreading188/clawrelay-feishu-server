"""
ClaudeRelay适配器模块

封装clawrelay-api的HTTP/SSE接口，将Claude Code CLI的流式输出
解析为结构化事件（TextDelta、ThinkingDelta、ToolUseStart）。

clawrelay-api是一个Go服务（默认端口50009），为每个请求fork一个
claude CLI子进程，并以OpenAI兼容的SSE格式流式输出结果。
"""

import json
import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Dict, Optional, Union

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ToolUseStart:
    name: str


@dataclass
class AskUserQuestionEvent:
    tool_call_id: str
    questions: list


StreamEvent = Union[TextDelta, ThinkingDelta, ToolUseStart, AskUserQuestionEvent]


class ClaudeRelayAdapter:
    """ClawRelay API适配器"""

    def __init__(self, relay_url: str, model: str, working_dir: str, env_vars: Optional[Dict[str, str]] = None):
        self.relay_url = relay_url.rstrip("/")
        self.model = model
        self.working_dir = working_dir
        self.env_vars = env_vars or {}
        logger.info(
            f"[ClaudeRelay] 初始化适配器: relay_url={self.relay_url}, "
            f"model={self.model}, working_dir={self.working_dir}, "
            f"env_vars_count={len(self.env_vars)}"
        )

    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        session_id: str = "",
    ) -> AsyncGenerator[StreamEvent, None]:
        """流式聊天请求"""
        request_messages = list(messages)
        if system_prompt:
            request_messages.insert(0, {
                "role": "system",
                "content": system_prompt,
            })

        request_body = {
            "model": self.model,
            "messages": request_messages,
            "stream": True,
            "working_dir": self.working_dir,
        }
        if session_id:
            request_body["session_id"] = session_id
        if self.env_vars:
            request_body["env_vars"] = self.env_vars

        url = f"{self.relay_url}/v1/chat/completions"
        logger.info(
            f"[ClaudeRelay] POST {url}, model={self.model}, "
            f"messages_count={len(request_messages)}, "
            f"session_id={session_id or '(none)'}, stream=True"
        )

        timeout = aiohttp.ClientTimeout(total=3600, sock_read=3600)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        truncated = error_text[:500] if len(error_text) > 500 else error_text
                        raise Exception(
                            f"[ClaudeRelay] HTTP {response.status} error: {truncated}"
                        )

                    _ask_tool_call_id: str = ""
                    _ask_args_buffer: str = ""

                    async for raw_line in response.content:
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")

                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data: "):
                            continue

                        data = line[6:]

                        if data == "[DONE]":
                            if _ask_args_buffer:
                                yield self._flush_ask_event(_ask_tool_call_id, _ask_args_buffer)
                            logger.info("[ClaudeRelay] SSE stream ended: [DONE]")
                            return

                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError as e:
                            logger.warning(f"[ClaudeRelay] JSON parse error: {e}")
                            continue

                        choices = chunk.get("choices")
                        if not choices:
                            continue
                        delta = choices[0].get("delta")
                        if not delta:
                            continue

                        content = delta.get("content")
                        if content:
                            yield TextDelta(text=content)

                        thinking = delta.get("thinking")
                        if thinking:
                            yield ThinkingDelta(text=thinking)

                        tool_calls = delta.get("tool_calls")
                        if tool_calls:
                            for tool_call in tool_calls:
                                func = tool_call.get("function", {})
                                name = func.get("name")

                                if name == "AskUserQuestion":
                                    _ask_tool_call_id = tool_call.get("id", "")
                                    _ask_args_buffer = func.get("arguments", "")
                                elif name:
                                    yield ToolUseStart(name=name)
                                elif _ask_args_buffer is not None and not name:
                                    args_fragment = func.get("arguments", "")
                                    if args_fragment:
                                        _ask_args_buffer += args_fragment

                    if _ask_args_buffer:
                        yield self._flush_ask_event(_ask_tool_call_id, _ask_args_buffer)

        except aiohttp.ClientError as e:
            raise Exception(
                f"[ClaudeRelay] Connection error to {self.relay_url}: {e}"
            ) from e

    @staticmethod
    def _flush_ask_event(tool_call_id: str, args_buffer: str) -> AskUserQuestionEvent:
        try:
            args = json.loads(args_buffer) if args_buffer else {}
        except json.JSONDecodeError:
            args = {}
        questions = args.get("questions", [])
        return AskUserQuestionEvent(tool_call_id=tool_call_id, questions=questions)

    async def check_health(self) -> bool:
        url = f"{self.relay_url}/health"
        timeout = aiohttp.ClientTimeout(total=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return False
                    data = await response.json()
                    return data.get("status") == "healthy"
        except Exception:
            return False
