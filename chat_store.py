import json
import os
import time
import uuid
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "chats")


class ChatMessage:
    def __init__(self, role: str, content: str, timestamp: float = 0):
        self.role = role
        self.content = content
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, d: dict) -> "ChatMessage":
        return cls(d["role"], d["content"], d.get("timestamp", 0))


MODEL_CONTEXTS = {
    "nvidia/nemotron-3-super-120b-a12b:free": 262144,
}
DEFAULT_CONTEXT = 128000

def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


class ChatSession:
    def __init__(self, title: str = "New Chat"):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.created = time.time()
        self.updated = time.time()
        self.messages: list[ChatMessage] = []
        self.tools: dict[str, bool] = {}
        self.model: str = ""

    def add_message(self, role: str, content: str):
        self.messages.append(ChatMessage(role, content))
        self.updated = time.time()

    def context_tokens(self) -> int:
        total = 0
        for m in self.messages:
            total += estimate_tokens(m.content)
        # Add ~100 tokens per message for role/format overhead
        total += len(self.messages) * 100
        return total

    def context_limit(self) -> int:
        return MODEL_CONTEXTS.get(self.model, DEFAULT_CONTEXT)

    def context_pct(self) -> float:
        limit = self.context_limit()
        if limit <= 0:
            return 0
        return min(100.0, round((self.context_tokens() / limit) * 100, 1))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created": self.created,
            "updated": self.updated,
            "messages": [m.to_dict() for m in self.messages],
            "tools": self.tools,
            "model": self.model,
            "context_pct": self.context_pct(),
            "context_tokens": self.context_tokens(),
            "context_limit": self.context_limit(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChatSession":
        s = cls(d.get("title", "Chat"))
        s.id = d.get("id", uuid.uuid4().hex[:12])
        s.created = d.get("created", time.time())
        s.updated = d.get("updated", s.created)
        s.messages = [ChatMessage.from_dict(m) for m in d.get("messages", [])]
        s.tools = d.get("tools", {})
        s.model = d.get("model", "")
        return s


class ChatStore:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.sessions: list[ChatSession] = []
        self.active_id: Optional[str] = None
        self._load_all()

    def _path(self, sid: str) -> str:
        return os.path.join(DATA_DIR, f"{sid}.json")

    def _load_all(self):
        self.sessions = []
        if not os.path.isdir(DATA_DIR):
            return
        for fname in os.listdir(DATA_DIR):
            if fname.endswith(".json"):
                path = os.path.join(DATA_DIR, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self.sessions.append(ChatSession.from_dict(json.load(f)))
                except (json.JSONDecodeError, KeyError):
                    pass
        self.sessions.sort(key=lambda s: s.updated, reverse=True)
        if not self.sessions:
            self.new_session()

    def new_session(self) -> ChatSession:
        session = ChatSession()
        self.sessions.insert(0, session)
        self.active_id = session.id
        self._save(session)
        self.sessions.sort(key=lambda s: s.updated, reverse=True)
        return session

    def get_active(self) -> Optional[ChatSession]:
        for s in self.sessions:
            if s.id == self.active_id:
                return s
        if self.sessions:
            self.active_id = self.sessions[0].id
            return self.sessions[0]
        return self.new_session()

    def switch_to(self, session_id: str):
        self.active_id = session_id
        for s in self.sessions:
            if s.id == session_id:
                s.updated = time.time()
                self._save(s)
                self.sessions.sort(key=lambda s: s.updated, reverse=True)
                break

    def delete_session(self, session_id: str):
        self.sessions = [s for s in self.sessions if s.id != session_id]
        path = self._path(session_id)
        if os.path.exists(path):
            os.remove(path)
        if not self.sessions:
            self.new_session()
        elif self.active_id == session_id:
            self.active_id = self.sessions[0].id

    def rename_session(self, session_id: str, title: str):
        for s in self.sessions:
            if s.id == session_id:
                s.title = title
                self._save(s)
                break

    def save_session(self, session: ChatSession):
        self._save(session)
        self.sessions.sort(key=lambda s: s.updated, reverse=True)

    def _save(self, session: ChatSession):
        path = self._path(session.id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2)
