import json
from pathlib import Path
from typing import Dict

CONFIG_PATH = Path.home() / ".ironcore" / "config.json"

def save_config(cfg: Dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def load_config() -> Dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}
