import json
import os
import subprocess
import threading
from typing import Optional


class MCPClient:
    def __init__(self, command: str, args: list[str] = None):
        self.command = command
        self.args = args or []
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._initialized = False
        self._req_id = 0

    def start(self) -> tuple[bool, str]:
        try:
            expanded = [os.path.expandvars(self.command)]
            for a in self.args:
                expanded.append(os.path.expandvars(a))
            # Validate the bat file exists
            if len(expanded) >= 3 and expanded[0] == "cmd.exe":
                bat_path = os.path.expandvars(expanded[2])
                if not os.path.isfile(bat_path):
                    return False, f"MCP file not found: {bat_path}"
            self.process = subprocess.Popen(
                expanded,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            ok, msg = self._initialize()
            self._initialized = ok
            return ok, msg
        except FileNotFoundError:
            return False, "Command not found"
        except Exception as e:
            return False, str(e)

    def stop(self):
        self._initialized = False
        if self.process:
            try:
                self.process.terminate()
            except:
                pass
            self.process = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None and self._initialized

    def _send(self, method: str, params: dict = None) -> Optional[dict]:
        if not self.process or not self.process.stdin:
            return None
        self._req_id += 1
        req = {"jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params or {}}
        try:
            payload = json.dumps(req)
            result = []
            def reader():
                try:
                    self.process.stdin.write(payload + "\n")
                    self.process.stdin.flush()
                    buf = ""
                    while True:
                        buf += self.process.stdout.readline()
                        if not buf.strip():
                            break
                        try:
                            result.append(json.loads(buf.strip()))
                            break
                        except json.JSONDecodeError:
                            continue
                except Exception:
                    pass
            t = threading.Thread(target=reader, daemon=True)
            t.start()
            t.join(timeout=8)
            return result[0] if result else None
        except Exception:
            return None

    def _initialize(self) -> tuple[bool, str]:
        resp = self._send("initialize", {
            "protocolVersion": "0.1.0",
            "capabilities": {},
            "clientInfo": {"name": "roblox-helper", "version": "1.0"},
        })
        if resp and "result" in resp:
            return True, "Connected"
        err = resp.get("error", {}).get("message", "No response") if resp else "No response"
        return False, err

    def list_tools(self) -> list[dict]:
        if not self.is_running():
            return []
        resp = self._send("tools/list")
        if resp and "result" in resp:
            return resp["result"].get("tools", [])
        return []

    def call_tool(self, name: str, arguments: dict) -> Optional[dict]:
        if not self.is_running():
            return None
        return self._send("tools/call", {"name": name, "arguments": arguments})

    def tools_to_openai(self) -> list[dict]:
        mcp_tools = self.list_tools()
        result = []
        for t in mcp_tools:
            schema = t.get("inputSchema", {})
            result.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": schema,
                },
            })
        return result


BUILTIN_TOOLS = {
    "roblox_studio_mcp": {
        "name": "Roblox Integration",
        "description": "Lets the AI read the full game hierarchy, list objects, get properties, create and edit scripts and instances in your Roblox Studio game.",
        "command": "cmd.exe",
        "args": ["/c", "%LOCALAPPDATA%\\Roblox\\mcp.bat"],
        "enabled": False,
    },
    "advanced_thinking": {
        "name": "Advanced Thinking",
        "description": "After each response, the AI reviews its own work and improves it before continuing.",
        "command": None,
        "args": None,
        "enabled": False,
    },
    "context_compactor": {
        "name": "Context Compactor",
        "description": "Automatically summarizes old messages when context gets full, preventing the AI from forgetting earlier parts of the conversation.",
        "command": None,
        "args": None,
        "enabled": True,
    },
    "script_placer": {
        "name": "Script Placer",
        "description": "Tells you exactly where to put every script (ServerScriptService, StarterPlayer, etc.).",
        "command": None,
        "args": None,
        "enabled": False,
    },
}


class ToolsManager:
    def __init__(self):
        self.tool_defs = {}
        self.mcp_clients = {}
        self._mcp_tools_cache = {}
        for tid, cfg in BUILTIN_TOOLS.items():
            self.tool_defs[tid] = dict(cfg)
            if cfg.get("command"):
                self.mcp_clients[tid] = MCPClient(cfg["command"], cfg.get("args"))

    def is_enabled(self, tool_id: str, session_tools: dict) -> bool:
        return session_tools.get(tool_id, False)

    def _ensure_running(self, tid: str) -> bool:
        if tid not in self.mcp_clients:
            return False
        client = self.mcp_clients[tid]
        if client.is_running():
            return True
        ok, _ = client.start()
        if ok:
            tools = client.list_tools()
            self._mcp_tools_cache[tid] = tools
            return True
        return False

    def get_tools(self, session_tools: dict = None) -> list[dict]:
        if session_tools is None:
            session_tools = {}
        result = []
        for tid, t in self.tool_defs.items():
            enabled = self.is_enabled(tid, session_tools)
            entry = {
                "id": tid,
                "name": t["name"],
                "description": t["description"],
                "enabled": enabled,
                "has_mcp": t.get("command") is not None,
            }
            if enabled and tid in self.mcp_clients:
                if self._ensure_running(tid):
                    mcp_tools = self._mcp_tools_cache.get(tid, [])
                    entry["mcp_count"] = len(mcp_tools)
            result.append(entry)
        return result

    def toggle_tool(self, tool_id: str, session_tools: dict) -> tuple[dict, dict]:
        if tool_id not in self.tool_defs:
            return {"ok": False, "error": "Tool not found"}, session_tools
        new_enabled = not session_tools.get(tool_id, False)
        session_tools = dict(session_tools)
        session_tools[tool_id] = new_enabled
        if new_enabled and tool_id in self.mcp_clients:
            client = self.mcp_clients[tool_id]
            if not client.is_running():
                ok, msg = client.start()
                if ok:
                    mcp_tools = client.list_tools()
                    self._mcp_tools_cache[tool_id] = mcp_tools
                return {"ok": ok, "enabled": True, "message": msg}, session_tools
        elif not new_enabled and tool_id in self.mcp_clients:
            self.mcp_clients[tool_id].stop()
            self._mcp_tools_cache.pop(tool_id, None)
        return {"ok": True, "enabled": new_enabled}, session_tools

    def get_enabled_context(self, session_tools: dict) -> str:
        lines = []
        for tid, t in self.tool_defs.items():
            if self.is_enabled(tid, session_tools):
                lines.append(f"- {t['name']}: {t['description']}")
                if tid in self.mcp_clients and self.mcp_clients[tid].is_running():
                    count = len(self._mcp_tools_cache.get(tid, []))
                    if count > 0:
                        lines.append(f"  ({count} tools available)")
        if lines:
            return "Active tools:\n" + "\n".join(lines)
        return ""

    def get_openai_tools(self, session_tools: dict) -> list[dict]:
        all_tools = []
        for tid, t in self.tool_defs.items():
            if self.is_enabled(tid, session_tools) and tid in self.mcp_clients:
                if not self._ensure_running(tid):
                    continue
                cached = self._mcp_tools_cache.get(tid)
                if cached:
                    for mt in cached:
                        schema = mt.get("inputSchema", {})
                        all_tools.append({
                            "type": "function",
                            "function": {
                                "name": mt["name"],
                                "description": mt.get("description", ""),
                                "parameters": schema,
                            },
                        })
        # Add context compactor as a virtual tool if enabled
        if self.is_enabled("context_compactor", session_tools):
            all_tools.append({
                "type": "function",
                "function": {
                    "name": "compact_context",
                    "description": "Summarize the conversation to free up context space. Call this when the conversation is getting very long or when you need to remember earlier details.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            })
        return all_tools
    
    def _filter_search_results(self, tool_name: str, raw_text: str) -> str:
        """Sort search results by likes + recency, return top 3."""
        is_search = any(x in tool_name.lower() for x in ['search', 'find', 'query', 'lookup', 'browse'])
        if not is_search:
            return raw_text
        try:
            items = json.loads(raw_text)
            if not isinstance(items, list):
                return raw_text
            scored = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                likes = abs(item.get('likeCount') or item.get('likes') or item.get('rating') or item.get('favorites') or 0)
                updated = item.get('updated') or item.get('lastUpdated') or item.get('date') or ''
                scored.append((likes, updated, item))
            scored.sort(key=lambda x: (-x[0], x[1] or ''))
            top = [s[2] for s in scored[:3]]
            return json.dumps(top) if top else raw_text
        except (json.JSONDecodeError, TypeError):
            # Try line-by-line: look for "Likes: N" patterns
            lines = raw_text.split('\n')
            groups = []
            current = []
            for line in lines:
                if line.strip() and not line.startswith(' '):
                    if current:
                        groups.append('\n'.join(current))
                    current = [line]
                else:
                    current.append(line)
            if current:
                groups.append('\n'.join(current))
            def extract_likes(g):
                import re
                m = re.search(r'(?:Likes|Rating|Favorites):\s*(\d+)', g, re.IGNORECASE)
                return int(m.group(1)) if m else 0
            groups.sort(key=extract_likes, reverse=True)
            return '\n\n'.join(groups[:3])
        return raw_text

    def _clean_tool_output(self, text: str) -> str:
        """Fix common MCP formatting issues: → to newlines, digits→ to line numbers."""
        import re
        # Replace → with newline
        text = text.replace('→', '\n')
        # Fix patterns like "1\ncontent1\n2\ncontent2" → "1. content1\n2. content2"
        text = re.sub(r'(\d+)\n(?=\S)', r'\1. ', text)
        # Remove leading line numbers on each line like "1→" or "1. "
        text = re.sub(r'^\d+[.→]\s*', '', text, flags=re.MULTILINE)
        # Collapse multiple blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def handle_tool_call(self, tool_name: str, arguments: dict, session_tools: dict) -> Optional[str]:
        for tid in self.tool_defs:
            if self.is_enabled(tid, session_tools) and tid in self.mcp_clients and self.mcp_clients[tid].is_running():
                result = self.mcp_clients[tid].call_tool(tool_name, arguments)
                if result:
                    if "result" in result:
                        r = result["result"]
                        if isinstance(r, dict):
                            content = r.get("content", [])
                            if isinstance(content, list):
                                texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                                combined = "\n".join(texts)
                                combined = self._clean_tool_output(combined)
                                filtered = self._filter_search_results(tool_name, combined)
                                return json.dumps([{"type": "text", "text": filtered}]) if texts else json.dumps(content)
                            return json.dumps(content)
                        return json.dumps(r)
                    return json.dumps(result.get("error", "Tool call failed"))
        return None
