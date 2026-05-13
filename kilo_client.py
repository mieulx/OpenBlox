import json
import requests
from typing import Optional


GATEWAY_URL = "https://api.kilo.ai/api/gateway"
ENDPOINT = f"{GATEWAY_URL}/chat/completions"
MODELS_ENDPOINT = f"{GATEWAY_URL}/models"
DEFAULT_MODEL = "kilo-auto/free"

ROBLOX_SYSTEM = (
    "You are a Roblox Studio expert assistant. Help with LuaU scripting, "
    "Roblox API, Studio workflows, and game development.\n"
    "Rules:\n"
    "- Answer ONLY about Roblox Studio. If asked something else, redirect back.\n"
    "- Be concise. Don't pre-emptively dump code examples unless the user asks for code.\n"
    "- If the user just says hi/hello/hey, greet them briefly and ask what they need help with.\n"
    "- Use your training knowledge to answer.\n"
    "\n"
    "ROBLOX SERVICES REFERENCE:\n"
    "  workspace         — Contains all in-game objects (parts, models, etc.)\n"
    "  Players           — Manages player joining/leaving, player objects\n"
    "  Lighting          — Controls environmental lighting, sky, fog\n"
    "  MaterialService   — Manages material definitions and overrides\n"
    "  ReplicatedFirst   — Replicated to clients before anything else. Use for loading screens.\n"
    "  ReplicatedStorage — Replicated to all clients. Store ModuleScripts, assets, remote events/functions.\n"
    "  ServerScriptService — ONLY runs on server. Put server Scripts here.\n"
    "  ServerStorage     — NOT replicated. Store server-only assets and ModuleScripts.\n"
    "  StarterGui        — Templates copied to each player's PlayerGui on join.\n"
    "  StarterPack       — Templates copied to each player's Backpack on join.\n"
    "  StarterPlayer     — Contains StarterPlayerScripts (LocalScripts copied to each player).\n"
    "  Teams            — Manages team definitions and balancing.\n"
    "  SoundService     — Manages sound groups, effects, and audio properties.\n"
    "  TextChatService  — Manages in-game chat system.\n"
    "\n"
    "SCRIPT PLACEMENT RULES — ALWAYS state where each script goes:\n"
    "  Server Script (Script) → ServerScriptService (or workspace if logic is tied to a specific place)\n"
    "  LocalScript → StarterPlayer > StarterPlayerScripts (or StarterGui for GUI-specific logic)\n"
    "  ModuleScript → ReplicatedStorage (shared) or ServerStorage (server-only)\n"
    "  RemoteEvent/RemoteFunction → ReplicatedStorage\n"
    "\n"
    "When you write a script, ALWAYS start it with a comment like:\n"
    "  -- ServerScript → Place in ServerScriptService\n"
    "  -- LocalScript → Place in StarterPlayer > StarterPlayerScripts\n"
    "  -- ModuleScript → Place in ReplicatedStorage\n"
    "\n"
    "Always explain briefly what type of script it is and where the user should put it."
    "\n"
    "PLANNING CHECKLIST:\n"
    "If the user asks for something multi-step (create a game system, multiple scripts, "
    "a full feature), first output a numbered checklist of what you'll do. "
    "Then execute each step. Mark items as [DONE] as you complete them.\n"
    "\n"
    "MCP TOOL USAGE:\n"
    "When Roblox Studio MCP is active, you can create/edit instances and scripts directly "
    "in Studio. If the user asks you to DO something in Studio (create a script, change a "
    "property, insert a part), call the appropriate MCP tool. Only give copy-paste code "
    "if MCP is not available or the user asks for code specifically. You can chain "
    "multiple tool calls if needed — no need to overthink."
)


class KiloClient:
    def __init__(self, api_key: str = "", model: str = DEFAULT_MODEL,
                 temperature: float = 0.3, system_prompt: str = ROBLOX_SYSTEM,
                 user_context: str = ""):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature
        self.user_context = user_context
        self.session = requests.Session()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _build_system(self, extra_context: str = "") -> str:
        sp = ROBLOX_SYSTEM
        if self.user_context:
            sp += f"\n\nUser preferences:\n{self.user_context}"
        if extra_context:
            sp += f"\n\n{extra_context}"
        return sp

    HARDCODED_MODELS = [
        {"id": "kilo-auto/free", "name": "kilo-auto/free", "tier": "Auto"},
        {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "name": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "tier": "Light"},
        {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "nvidia/nemotron-3-super-120b-a12b:free", "tier": "Pro"},
    ]

    def fetch_models(self) -> tuple[list[dict], list[dict]]:
        return self.HARDCODED_MODELS, self.HARDCODED_MODELS

    def fetch_free_models(self) -> list[dict]:
        return self.HARDCODED_MODELS

    def _run_tool_loop(self, full: list, payload: dict,
                       tools: list, tool_handler) -> str:
        max_rounds = 5
        content = ""
        for _ in range(max_rounds):
            resp = self._send_payload(payload)
            if resp is None:
                return content or "(no response)"
            msg = resp.get("message", {})
            content = msg.get("content") or content
            tool_calls = msg.get("tool_calls")
            if not tool_calls or not tool_handler:
                break
            full.append(msg)
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                result = tool_handler(name, args)
                full.append({"role": "tool", "tool_call_id": tc["id"], "content": result or "{}"})
            payload["messages"] = full
            if tools:
                payload["tools"] = tools
        return content.strip() if content else "(no response)"

    def chat(self, messages: list, max_tokens: int = 4096,
             extra_context: str = "", tools: list = None,
             tool_handler=None) -> Optional[str]:
        if not self.api_key:
            return None
        full = [{"role": "system", "content": self._build_system(extra_context)}]
        full.extend(messages)
        payload = {
            "model": self.model,
            "messages": full,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        return self._run_tool_loop(full, payload, tools, tool_handler)

    def chat_with_context(self, messages: list, context: str,
                          max_tokens: int = 4096,
                          extra_context: str = "",
                          tools: list = None,
                          tool_handler=None) -> Optional[str]:
        base = self._build_system(extra_context)
        ctx_msg = {
            "role": "system",
            "content": f"{base}\n\nRelevant documentation:\n{context}"
        }
        full = [ctx_msg]
        full.extend(messages)
        payload = {
            "model": self.model,
            "messages": full,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        return self._run_tool_loop(full, payload, tools, tool_handler)

    def _send_payload(self, payload: dict) -> Optional[dict]:
        try:
            resp = self.session.post(
                ENDPOINT, json=payload,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                timeout=120,
            )
            if resp.status_code == 401:
                return {"message": {"content": "Auth error: Kilo token rejected."}}
            if resp.status_code == 402:
                return {"message": {"content": "Balance error: Add credits."}}
            if resp.status_code == 404:
                return {"message": {"content": f"Model '{self.model}' not available."}}
            resp.raise_for_status()
            try:
                return resp.json().get("choices", [{}])[0]
            except (json.JSONDecodeError, ValueError):
                return {"message": {"content": f"API returned non-JSON: {resp.text[:200]}"}}
        except requests.Timeout:
            return {"message": {"content": "Error: Request timed out."}}
        except requests.RequestException as e:
            return {"message": {"content": f"Connection error: {e}"}}
        except (KeyError, IndexError) as e:
            return {"message": {"content": f"Response error: {e}"}}

    def test(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "No API key set."
        try:
            resp = self.session.post(
                ENDPOINT, json={"model": self.model,
                                "messages": [{"role": "user", "content": "ping"}],
                                "max_tokens": 5},
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                timeout=15,
            )
            if resp.status_code == 200:
                return True, "Connected. API is working."
            if resp.status_code == 401:
                return False, "Auth failed: invalid token."
            return False, f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            return False, str(e)
