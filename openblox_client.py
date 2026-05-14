import json
import requests
from typing import Optional


GATEWAY_URL = "https://api.kilo.ai/api/gateway"
ENDPOINT = f"{GATEWAY_URL}/chat/completions"
MODELS_ENDPOINT = f"{GATEWAY_URL}/models"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

ROBLOX_SYSTEM = (
    "You are a Roblox Studio expert assistant. Help with LuaU scripting, "
    "Roblox API, Studio workflows, and game development.\n"
    "Rules:\n"
    "- Answer ONLY about Roblox Studio. If asked something else, redirect back.\n"
    "- If the user just says hi/hello/hey, greet them briefly and ask what they need help with.\n"
    "- Use your training knowledge to answer.\n"
    "\n"
    "FORMATTING — CRITICAL: You MUST use proper formatting ALWAYS.\n"
    "  - Code blocks: ALWAYS wrap ALL scripts and code in ```lua ... ```\n"
    "  - NEVER output code without ``` formatting. Every script must be in a code block.\n"
    "  - Inline code: use `single backticks` for property names, method names, short snippets.\n"
    "  - Bold: use **bold** for emphasis on important concepts.\n"
    "  - Italic: use *italic* for secondary emphasis.\n"
    "  - Bullet lists: use - for lists.\n"
    "  - Numbered lists: use 1. 2. 3. for steps.\n"
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
    "Always explain briefly what type of script it is and where the user should put it.\n"
    "\n"
    "STEP-BY-STEP EXECUTION — CRITICAL:\n"
    "When the user asks to build a system or multiple scripts, you MUST execute step by step:\n"
    "  1. Output the FULL plan as a numbered checklist\n"
    "  2. Execute ONE step at a time via MCP tools\n"
    "  3. Mark each step [DONE] after completion\n"
    "  4. Each intermediate response is visible to the user.\n"
    "\n"
    "MCP TOOL USAGE — CRITICAL HONESTY RULES:\n"
    "  - Only claim you did something if you ACTUALLY called a tool. Never pretend.\n"
    "  - If you output code in a ``` block, you did NOT use MCP — just say you wrote the code.\n"
    "  - When Integration is not active, just write code with ``` formatting — no tool claims.\n"
    "  - Tool call results are automatically logged above. You don't need to repeat them.\n"
    "  - NEVER say \"creating...\" or \"I've created\" unless a tool just returned success.\n"
    "  - After a tool succeeds, just mark the step [DONE] and move on. Don't narrate it again.\n"
    "  - If a tool fails, say it failed. Don't pretend it worked.\n"
    "  - Be honest: if you can't do something, say so directly."
)


class OpenBloxClient:
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
        {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "nvidia/nemotron-3-super-120b-a12b:free", "tier": "Apex"},
        {"id": "arcee-ai/trinity-large-thinking:free", "name": "arcee-ai/trinity-large-thinking:free", "tier": "Rover"},
    ]

    def fetch_models(self) -> tuple[list[dict], list[dict]]:
        return self.HARDCODED_MODELS, self.HARDCODED_MODELS

    def fetch_free_models(self) -> list[dict]:
        return self.HARDCODED_MODELS

    def _run_tool_loop(self, full: list, payload: dict,
                       tools: list, tool_handler,
                       advanced_thinking: bool = False) -> str:
        max_rounds = 15
        content = ""
        reviewed = False
        for _ in range(max_rounds):
            resp = self._send_payload(payload)
            if resp is None:
                if content:
                    return content
                continue
            msg = resp.get("message", {})
            new_content = msg.get("content") or ""
            if new_content:
                if content:
                    content += "\n\n" + new_content
                else:
                    content = new_content
            tool_calls = msg.get("tool_calls")
            if not tool_calls or not tool_handler:
                if content:
                    if advanced_thinking and not reviewed:
                        reviewed = True
                        full.append({"role": "user", "content": "Review what you just did. Check for errors, improvements, or missing details. Then provide a final improved response."})
                        payload["messages"] = full
                        if tools:
                            payload["tools"] = tools
                        continue
                    break
                full.append({"role": "user", "content": "Please provide your response now."})
                payload["messages"] = full
                if tools:
                    payload["tools"] = tools
                continue
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
                if result:
                    try:
                        summary = json.loads(result)
                        texts = [item.get("text", "") for item in summary if isinstance(item, dict) and item.get("type") == "text"]
                        if texts:
                            tool_feedback = f"\n\n> **MCP:** Called `{name}` — {texts[0][:200]}"
                            if content:
                                content += tool_feedback
                            else:
                                content = tool_feedback.strip()
                    except (json.JSONDecodeError, TypeError):
                        pass
            payload["messages"] = full
            if tools:
                payload["tools"] = tools
        return content.strip() if content else "(no response)"

    def chat(self, messages: list, max_tokens: int = 4096,
             extra_context: str = "", tools: list = None,
             tool_handler=None,
             advanced_thinking: bool = False) -> Optional[str]:
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
        return self._run_tool_loop(full, payload, tools, tool_handler, advanced_thinking)

    def chat_with_context(self, messages: list, context: str,
                          max_tokens: int = 4096,
                          extra_context: str = "",
                          tools: list = None,
                          tool_handler=None,
                          advanced_thinking: bool = False) -> Optional[str]:
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
        return self._run_tool_loop(full, payload, tools, tool_handler, advanced_thinking)

    def _send_payload(self, payload: dict) -> Optional[dict]:
        try:
            resp = self.session.post(
                ENDPOINT, json=payload,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                timeout=120,
            )
            if resp.status_code == 401:
                return {"message": {"content": "Auth error: API token rejected."}}
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
