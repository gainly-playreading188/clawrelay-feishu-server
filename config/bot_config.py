"""
飞书机器人配置管理

从 bots.yaml 加载机器人配置，支持多机器人实例。
"""

import logging
import os
from typing import Dict, Optional

import yaml

logger = logging.getLogger(__name__)


class BotConfig:
    """单个机器人配置"""

    def __init__(
        self,
        bot_key: str = "",
        app_id: str = "",
        app_secret: str = "",
        relay_url: str = "",
        working_dir: str = "",
        model: str = "",
        name: str = "",
        description: str = "",
        system_prompt: str = "",
        allowed_users: list = None,
        env_vars: dict = None,
        custom_commands: list = None,
    ):
        self.bot_key = bot_key
        self.app_id = app_id
        self.app_secret = app_secret
        self.relay_url = relay_url
        self.working_dir = working_dir
        self.model = model
        self.name = name
        self.description = description or name or bot_key
        self.system_prompt = system_prompt
        self.allowed_users = allowed_users or []
        self.env_vars = env_vars or {}
        self.custom_commands = custom_commands or []


class BotConfigManager:
    """机器人配置管理器"""

    def __init__(self, config_path: str = ""):
        self.bots: Dict[str, BotConfig] = {}
        self._config_path = config_path or os.getenv("BOT_CONFIG_PATH") or "config/bots.yaml"
        self._load_from_yaml()

    def _load_from_yaml(self):
        if not os.path.exists(self._config_path):
            logger.warning("配置文件不存在: %s", self._config_path)
            return

        with open(self._config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        bots_data = data.get("bots", {})
        for bot_key, bot_data in bots_data.items():
            if not isinstance(bot_data, dict):
                continue
            app_id = bot_data.get("app_id", "")
            if not app_id or app_id.startswith("YOUR_"):
                logger.warning("跳过未配置的机器人: %s", bot_key)
                continue
            self.bots[bot_key] = BotConfig(
                bot_key=bot_key,
                app_id=app_id,
                app_secret=bot_data.get("app_secret", ""),
                relay_url=bot_data.get("relay_url", "http://localhost:50009"),
                working_dir=bot_data.get("working_dir", ""),
                model=bot_data.get("model", ""),
                name=bot_data.get("name", ""),
                description=bot_data.get("description", ""),
                system_prompt=bot_data.get("system_prompt", ""),
                allowed_users=bot_data.get("allowed_users", []),
                env_vars=bot_data.get("env_vars", {}),
                custom_commands=bot_data.get("custom_commands", []),
            )
            logger.info("加载机器人配置: %s (%s)", bot_key, self.bots[bot_key].description)

    def needs_setup(self) -> bool:
        return len(self.bots) == 0

    def run_setup_wizard(self) -> bool:
        """交互式配置向导"""
        print("\n" + "=" * 50)
        print("飞书机器人配置向导")
        print("=" * 50)

        app_id = input("\n请输入飞书应用 App ID: ").strip()
        if not app_id:
            print("App ID 不能为空")
            return False

        app_secret = input("请输入飞书应用 App Secret: ").strip()
        if not app_secret:
            print("App Secret 不能为空")
            return False

        relay_url = input("请输入 ClawRelay API 地址 [http://localhost:50009]: ").strip()
        if not relay_url:
            relay_url = "http://localhost:50009"

        working_dir = input("请输入 Claude 工作目录 [留空使用默认]: ").strip()

        config_data = {
            "bots": {
                "default": {
                    "app_id": app_id,
                    "app_secret": app_secret,
                    "relay_url": relay_url,
                    "working_dir": working_dir,
                    "model": "vllm/claude-sonnet-4-6",
                    "name": "AI Assistant",
                    "description": "My AI assistant",
                }
            }
        }

        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)

        print(f"\n配置已保存到 {self._config_path}")
        self._load_from_yaml()
        return True

    def get_all_bots(self) -> Dict[str, BotConfig]:
        return self.bots
