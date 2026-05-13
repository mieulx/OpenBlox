import json
import subprocess
import threading
from typing import Optional


class MCPClient:
    def __init__(self, command: str, args: list[str] = None):
        self.command = command
        self.args = args or []
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        try:
            self.process = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def send_request(self, request: dict) -> Optional[dict]:
        if not self.is_running():
            return None
        try:
            payload = json.dumps(request)
            self.process.stdin.write(payload + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            return json.loads(line.strip()) if line.strip() else None
        except Exception:
            return None

    def list_tools(self) -> list[dict]:
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }
        resp = self.send_request(req)
        if resp and "result" in resp:
            return resp["result"].get("tools", [])
        return []

    def call_tool(self, name: str, arguments: dict) -> Optional[dict]:
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        return self.send_request(req)


BUILTIN_TOOLS = {
    "roblox_studio_mcp": {
        "name": "Roblox Studio MCP",
        "description": "Connect to Roblox Studio via MCP to create scripts, manage instances, and edit properties directly.",
        "command": "cmd.exe",
        "args": ["/c", r"%LOCALAPPDATA%\Roblox\mcp.bat"],
        "enabled": False,
    },
    "script_placer": {
        "name": "Script Placer",
        "description": "Automatically places scripts in the correct Roblox service based on script type.",
        "command": None,
        "args": None,
        "enabled": False,
    },
}


class ToolsManager:
    def __init__(self):
        self.tools = {}
        self.mcp_clients = {}
        for tid, cfg in BUILTIN_TOOLS.items():
            self.tools[tid] = dict(cfg)
            if cfg.get("command"):
                self.mcp_clients[tid] = MCPClient(cfg["command"], cfg.get("args"))

    def get_tools(self) -> list[dict]:
        return [
            {
                "id": tid,
                "name": t["name"],
                "description": t["description"],
                "enabled": t["enabled"],
                "has_mcp": t.get("command") is not None,
            }
            for tid, t in self.tools.items()
        ]

    def toggle_tool(self, tool_id: str) -> dict:
        if tool_id not in self.tools:
            return {"ok": False, "error": "Tool not found"}
        t = self.tools[tool_id]
        t["enabled"] = not t["enabled"]
        if t["enabled"] and tool_id in self.mcp_clients:
            client = self.mcp_clients[tool_id]
            if not client.is_running():
                client.start()
        elif not t["enabled"] and tool_id in self.mcp_clients:
            self.mcp_clients[tool_id].stop()
        return {"ok": True, "enabled": t["enabled"]}

    def get_enabled_context(self) -> str:
        lines = []
        for tid, t in self.tools.items():
            if t["enabled"]:
                lines.append(f"- {t['name']}: {t['description']}")
        if lines:
            return "Active tools:\n" + "\n".join(lines)
        return ""

    def get_mcp_tools(self, tool_id: str) -> list[dict]:
        if tool_id in self.mcp_clients and self.mcp_clients[tool_id].is_running():
            return self.mcp_clients[tool_id].list_tools()
        return []

    def call_mcp_tool(self, tool_id: str, name: str, args: dict) -> Optional[dict]:
        if tool_id in self.mcp_clients and self.mcp_clients[tool_id].is_running():
            return self.mcp_clients[tool_id].call_tool(name, args)
        return None
