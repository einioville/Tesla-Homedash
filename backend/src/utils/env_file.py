'''
Finds and loads the backend's .env. An installed release keeps it in the app's config folder,
beside config.json — install.sh moves it there (#56); a development checkout keeps it in the repo
root, the nearest .env above this file. frontend_v2/core/dotenv.cpp looks in the same order.
load_dotenv never overrides a variable that is already set, so systemd's Environment= still wins.
'''

import os

from dotenv import find_dotenv, load_dotenv


def app_config_dir() -> str:
    '''
    $XDG_CONFIG_HOME (or ~/.config) / Tesla-Homedash — the folder both halves
    keep their configuration in, and the screensaver its photos.
    '''
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "Tesla-Homedash")


def env_file() -> str:
    '''The .env this backend reads, or "" when there is none.'''
    beside = os.path.join(app_config_dir(), ".env")
    if os.path.isfile(beside):
        return beside
    # Walks up from this file: in a checkout, to the repo root.
    return find_dotenv()


def load_env_file() -> None:
    '''Loads env_file() into the environment; idempotent.'''
    path = env_file()
    if path:
        load_dotenv(path)
