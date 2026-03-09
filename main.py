#!/usr/bin/env python
# coding=utf-8
"""
ClawRelay Feishu Server - WebSocket Long Connection Mode

使用飞书官方 SDK 的 WebSocket 长连接接收消息事件，
通过 HTTP API 回复/编辑消息实现流式推送。
"""

import asyncio
import logging
import signal
import threading
from dotenv import load_dotenv

from config.bot_config import BotConfigManager
from src.transport.feishu_ws_client import FeishuWsClient
from src.transport.message_dispatcher import MessageDispatcher

VERSION = "v1.0.0"

load_dotenv(override=False)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from src.utils.logging_config import setup_business_logging
setup_business_logging()


def run_bot(bot_config, loop: asyncio.AbstractEventLoop) -> threading.Thread:
    """为单个 bot 启动 WebSocket 长连接线程"""
    if not bot_config.app_secret:
        logger.error("机器人 %s 未配置 app_secret，跳过", bot_config.bot_key)
        return None

    # 创建消息分发器（需要主事件循环用于调度异步任务）
    dispatcher = MessageDispatcher(bot_config, loop)

    # 创建飞书 WebSocket 客户端
    ws_client = FeishuWsClient(
        app_id=bot_config.app_id,
        app_secret=bot_config.app_secret,
        bot_key=bot_config.bot_key,
        on_message=dispatcher.on_message_event,
    )

    logger.info("启动机器人: %s (%s)", bot_config.bot_key, bot_config.description)

    # 在独立线程中启动 WebSocket（SDK 的 start() 是阻塞的）
    return ws_client.start_in_thread()


async def main():
    logger.info("=" * 60)
    logger.info("ClawRelay Feishu Server %s (WebSocket Long Connection)", VERSION)
    logger.info("=" * 60)

    config_manager = BotConfigManager()

    if config_manager.needs_setup():
        if not config_manager.run_setup_wizard():
            logger.error("配置未完成，退出")
            return
        print()

    all_configs = config_manager.get_all_bots()
    if not all_configs:
        logger.error("没有找到任何有效的机器人配置，退出")
        return

    loop = asyncio.get_running_loop()
    threads = []

    for bot_key, bot_config in all_configs.items():
        logger.info("  - %s: %s", bot_key, bot_config.description)
        thread = run_bot(bot_config, loop)
        if thread:
            threads.append(thread)

    logger.info("=" * 60)
    logger.info("共启动 %d 个机器人", len(threads))
    logger.info("=" * 60)

    # 主事件循环保持运行，处理异步任务
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("收到退出信号，准备关闭...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("收到退出信号，关闭服务")
