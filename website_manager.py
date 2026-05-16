import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional


def _appdata_root() -> str:
    base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA") or os.path.dirname(__file__)
    path = os.path.join(base, "OpenBlox")
    os.makedirs(path, exist_ok=True)
    return path


CONFIG_PATH = os.path.join(_appdata_root(), "config.json")
LEGACY_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


@dataclass
class WebsiteEntry:
    url: str
    name: str
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    extractor_type: str = "generic_html"


class WebsiteManager:
    def __init__(self, config_path: str = CONFIG_PATH):
        self.config_path = config_path
        self.websites: List[WebsiteEntry] = []
        self.openblox_config = {
            "api_key": "",
            "endpoint": "https://api.kilo.ai/api/gateway/chat/completions",
            "model": "nvidia/nemotron-3-super-120b-a12b:free",
            "temperature": 0.3,
            "user_context": "",
            "dev_mode": False,
            "permissions_enabled": True,
            "allowed_tools": [],
        }
        self.search_config = {
            "max_chunks": 8,
            "chunk_size": 1500,
        }
        self._migrate_legacy_config()
        self.load()

    def load(self):
        if not os.path.exists(self.config_path):
            self._set_defaults()
            self.save()
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.websites = [WebsiteEntry(**w) for w in data.get("websites", [])]
            self.openblox_config.update(data.get("openblox", {}))
            self.search_config.update(data.get("search", {}))
        except (json.JSONDecodeError, KeyError):
            self._set_defaults()
            self.save()

    def _migrate_legacy_config(self):
        if os.path.abspath(self.config_path) == os.path.abspath(LEGACY_CONFIG_PATH):
            return
        if os.path.exists(self.config_path) or not os.path.exists(LEGACY_CONFIG_PATH):
            return
        try:
            with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except (OSError, json.JSONDecodeError):
            pass

    def _set_defaults(self):
        self.websites = [
            WebsiteEntry(
                url="https://create.roblox.com/docs",
                name="Roblox Creator Docs",
                enabled=True,
                tags=["docs", "api", "luau"],
                extractor_type="nextjs",
            ),
            WebsiteEntry(
                url="https://devforum.roblox.com",
                name="Roblox DevForum",
                enabled=True,
                tags=["forum", "community", "scripts"],
                extractor_type="devforum",
            ),
            WebsiteEntry(
                url="https://create.roblox.com/docs/reference/engine",
                name="Roblox Engine API",
                enabled=True,
                tags=["api", "reference", "classes"],
                extractor_type="nextjs",
            ),
        ]

    def save(self):
        data = {
            "websites": [asdict(w) for w in self.websites],
            "openblox": self.openblox_config,
            "search": self.search_config,
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def add_website(self, url: str, name: str, tags: Optional[List[str]] = None,
                    extractor_type: str = "generic_html") -> WebsiteEntry:
        entry = WebsiteEntry(
            url=url,
            name=name or url,
            enabled=True,
            tags=tags or [],
            extractor_type=extractor_type,
        )
        self.websites.append(entry)
        self.save()
        return entry

    def remove_website(self, index: int):
        if 0 <= index < len(self.websites):
            del self.websites[index]
            self.save()

    def toggle_website(self, index: int):
        if 0 <= index < len(self.websites):
            self.websites[index].enabled = not self.websites[index].enabled
            self.save()

    def get_enabled_websites(self) -> List[WebsiteEntry]:
        return [w for w in self.websites if w.enabled]

    def update_openblox_config(self, api_key: str = "", endpoint: str = "",
                           model: str = "nvidia/nemotron-3-super-120b-a12b:free",
                           temperature: float = 0.3,
                           user_context: str = ""):
        self.openblox_config["api_key"] = api_key
        self.openblox_config["endpoint"] = endpoint
        self.openblox_config["model"] = model
        self.openblox_config["temperature"] = temperature
        if user_context is not None:
            self.openblox_config["user_context"] = user_context
        self.save()

    def update_search_config(self, max_chunks: int = 8, chunk_size: int = 1500):
        self.search_config["max_chunks"] = max_chunks
        self.search_config["chunk_size"] = chunk_size
        self.save()
