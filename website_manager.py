import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


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
        self.kilo_config = {
            "api_key": "",
            "endpoint": "https://api.kilo.ai/api/gateway/chat/completions",
            "model": "nvidia/nemotron-3-super-120b-a12b:free",
            "temperature": 0.3,
            "user_context": "",
        }
        self.search_config = {
            "max_chunks": 8,
            "chunk_size": 1500,
        }
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
            self.kilo_config.update(data.get("kilo", {}))
            self.search_config.update(data.get("search", {}))
        except (json.JSONDecodeError, KeyError):
            self._set_defaults()
            self.save()

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
            "kilo": self.kilo_config,
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

    def update_kilo_config(self, api_key: str = "", endpoint: str = "",
                           model: str = "nvidia/nemotron-3-super-120b-a12b:free",
                           temperature: float = 0.3,
                           user_context: str = ""):
        self.kilo_config["api_key"] = api_key
        self.kilo_config["endpoint"] = endpoint
        self.kilo_config["model"] = model
        self.kilo_config["temperature"] = temperature
        if user_context is not None:
            self.kilo_config["user_context"] = user_context
        self.save()

    def update_search_config(self, max_chunks: int = 8, chunk_size: int = 1500):
        self.search_config["max_chunks"] = max_chunks
        self.search_config["chunk_size"] = chunk_size
        self.save()
