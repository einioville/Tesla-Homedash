import json
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger("utils.config_parser")

_config_cache: dict | None = None
_env_loaded: bool = False


def _ensure_env() -> None:
    global _env_loaded
    if not _env_loaded:
        load_dotenv()
        _env_loaded = True


class ConfigUtils:
    @staticmethod
    def get_config() -> dict:
        global _config_cache
        if _config_cache is not None:
            return _config_cache

        _ensure_env()
        config_path = os.getenv("CONFIG_PATH")
        if not config_path:
            raise RuntimeError("CONFIG_PATH environment variable is not set")
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
        try:
            with open(config_path, 'r') as file:
                _config_cache = json.load(file)
            logger.info("Configuration loaded from %s", config_path)
            return _config_cache
        except json.JSONDecodeError as e:
            raise ValueError(f"Config file contains invalid JSON: {e}") from e
        except OSError as e:
            logger.error("Failed to load configuration from %s: %s", config_path, e)
            raise

    @staticmethod
    def get_env(key: str):
        _ensure_env()
        value = os.getenv(key)
        if value is None:
            logger.warning("Environment variable not set: %s", key)
        return value
