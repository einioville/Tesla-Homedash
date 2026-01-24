import json
import os
from dotenv import load_dotenv


class ConfigUtils:
    @staticmethod
    def get_config() -> dict:
        load_dotenv()
        config_path = os.getenv("CONFIG_PATH")
        with open(config_path, 'r') as file:
            return json.load(file)

    @staticmethod
    def get_env(key: str):
        load_dotenv()
        return os.getenv(key)
