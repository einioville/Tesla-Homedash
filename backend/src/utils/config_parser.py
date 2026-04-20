import json
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger("utils.config_parser")


class ConfigUtils:
    @staticmethod
    def get_config() -> dict:
        load_dotenv()
        config_path = os.getenv("CONFIG_PATH")
        if config_path is None:
            logger.warning("CONFIG_PATH environment variable not set")
        try:
            with open(config_path, 'r') as file:
                config = json.load(file)
            logger.info("Configuration loaded from %s", config_path)
            return config
        except Exception as e:
            logger.error("Failed to load configuration from %s: %s", config_path, e)
            raise

    @staticmethod
    def get_env(key: str):
        load_dotenv()
        value = os.getenv(key)
        if value is None:
            logger.warning("Environment variable not set: %s", key)
        return value
