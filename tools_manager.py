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
        req = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params or {},
        }
        try:
            payload = json.dumps(req)
            result = []
            err = []
            def reader():
                try:
                    self.process.stdin.write(payload + "\n")
                    self.process.stdin.flush()
                    line = self.process.stdout.readline()
                    if line and line.strip():
                        result.append(json.loads(line.strip()))
                except Exception as e:
                    err.append(e)
            t = threading.Thread(target=reader, daemon=True)
            t.start()
            t.join(timeout=5)
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
        "name": "Roblox Studio MCP",
        "description": "Create and edit Roblox instances, scripts, and properties directly in Studio.",
        "command": "cmd.exe",
        "args": ["/c", "%LOCALAPPDATA%\\Roblox\\mcp.bat"],
        "enabled": False,
    },
    "script_placer": {
        "name": "Script Placer",
        "description": "Always states script type and correct Roblox service placement for every script.",
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
            if enabled and tid in self.mcp_clients and self.mcp_clients[tid].is_running():
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
            if self.is_enabled(tid, session_tools) and tid in self.mcp_clients and self.mcp_clients[tid].is_running():
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
        return all_tools

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
                                return json.dumps([c for c in content if c.get("type") == "text"])
                            return json.dumps(content)
                        return json.dumps(r)
                    return json.dumps(result.get("error", "Tool call failed"))
        return None
