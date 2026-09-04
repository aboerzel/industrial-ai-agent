from pathlib import Path

from dotenv import load_dotenv


def load_local_environment(dotenv_path: Path) -> None:
    load_dotenv(dotenv_path=dotenv_path, override=False)
