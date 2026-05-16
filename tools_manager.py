import json
import os
import re
import subprocess
import threading
from typing import Optional


class MCPClient:
    def __init__(self, command: str, args: list[str] = None):
        self.command = command
        self.args = args or []
        self.process: Optional[subprocess.Popen] = None
        self._initialized = False
        self._req_id = 0
        self._write_lock = threading.Lock()
        self._pending: dict[int, tuple[threading.Event, dict]] = {}
        self._pending_lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_tail: list[str] = []

    def start(self) -> tuple[bool, str]:
        self.stop()
        try:
            expanded = [os.path.expandvars(self.command)]
            expanded.extend(os.path.expandvars(a) for a in self.args)
            if len(expanded) >= 3 and expanded[0].lower() == "cmd.exe":
                bat_path = os.path.expandvars(expanded[2])
                if not os.path.isfile(bat_path):
                    return False, f"MCP file not found: {bat_path}"

            self.process = subprocess.Popen(
                expanded,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._start_background_threads()
            ok, msg = self._initialize()
            self._initialized = ok
            if not ok:
                self.stop()
            return ok, msg
        except FileNotFoundError:
            return False, "Command not found"
        except Exception as e:
            self.stop()
            return False, str(e)

    def stop(self):
        self._initialized = False
        proc = self.process
        self.process = None
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._flush_pending("MCP process stopped")

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None and self._initialized

    def _start_background_threads(self):
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_thread.start()

    def _stderr_loop(self):
        proc = self.process
        if not proc or not proc.stderr:
            return
        try:
            for line in iter(proc.stderr.readline, ""):
                line = line.strip()
                if not line:
                    continue
                self._stderr_tail.append(line)
                if len(self._stderr_tail) > 20:
                    self._stderr_tail.pop(0)
        except Exception:
            pass

    def _reader_loop(self):
        proc = self.process
        if not proc or not proc.stdout:
            return
        try:
            while self.process is proc and proc.poll() is None:
                msg = self._read_message(proc.stdout)
                if msg is None:
                    break
                if "id" in msg:
                    try:
                        req_id = int(msg["id"])
                    except Exception:
                        continue
                    with self._pending_lock:
                        pending = self._pending.get(req_id)
                    if pending:
                        event, box = pending
                        box["message"] = msg
                        event.set()
        finally:
            self._initialized = False
            self._flush_pending("MCP connection closed")

    def _read_message(self, stream) -> Optional[dict]:
        headers = {}
        first_line = stream.readline()
        if not first_line:
            return None
        line = first_line.rstrip("\r\n")

        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                payload_lines = [line]
                while True:
                    next_line = stream.readline()
                    if not next_line:
                        break
                    payload_lines.append(next_line.rstrip("\r\n"))
                    try:
                        return json.loads("\n".join(payload_lines))
                    except json.JSONDecodeError:
                        continue
                return None

        while line:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
            next_line = stream.readline()
            if not next_line:
                return None
            line = next_line.rstrip("\r\n")

        content_length = headers.get("content-length")
        if not content_length:
            return None
        try:
            raw = stream.read(int(content_length))
            if not raw:
                return None
            return json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return None

    def _flush_pending(self, error_message: str):
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for event, box in pending:
            box["message"] = {"error": {"message": error_message}}
            event.set()

    def _send(self, method: str, params: dict = None, timeout: float = 10.0) -> Optional[dict]:
        if not self.process or not self.process.stdin or self.process.poll() is not None:
            return None

        with self._write_lock:
            self._req_id += 1
            req_id = self._req_id
            req = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
            event = threading.Event()
            box: dict = {}
            with self._pending_lock:
                self._pending[req_id] = (event, box)
            try:
                payload = json.dumps(req)
                self.process.stdin.write(payload + "\n")
                self.process.stdin.flush()
            except Exception:
                with self._pending_lock:
                    self._pending.pop(req_id, None)
                return None

        if not event.wait(timeout):
            with self._pending_lock:
                self._pending.pop(req_id, None)
            return {
                "error": {
                    "message": f"Timed out waiting for MCP response to {method}",
                    "details": self._stderr_tail[-5:],
                }
            }

        with self._pending_lock:
            self._pending.pop(req_id, None)
        return box.get("message")

    def _notify(self, method: str, params: dict = None):
        if not self.process or not self.process.stdin or self.process.poll() is not None:
            return
        with self._write_lock:
            try:
                payload = json.dumps({
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params or {},
                })
                self.process.stdin.write(payload + "\n")
                self.process.stdin.flush()
            except Exception:
                pass

    def _initialize(self) -> tuple[bool, str]:
        resp = self._send("initialize", {
            "protocolVersion": "0.1.0",
            "capabilities": {},
            "clientInfo": {"name": "openblox", "version": "1.0"},
        }, timeout=12.0)
        if resp and "result" in resp:
            self._notify("notifications/initialized", {})
            return True, "Connected"
        err = self._extract_error_message(resp) or "No response"
        return False, err

    def _extract_error_message(self, resp: Optional[dict]) -> str:
        if not resp:
            return ""
        error = resp.get("error")
        if isinstance(error, dict):
            message = error.get("message", "")
            details = error.get("details")
            if isinstance(details, list) and details:
                return f"{message} | {' | '.join(str(x) for x in details)}"
            return message
        if isinstance(error, str):
            return error
        return ""

    def list_tools(self) -> list[dict]:
        if not self.is_running():
            return []
        resp = self._send("tools/list", timeout=10.0)
        if resp and "result" in resp:
            return resp["result"].get("tools", [])
        return []

    def call_tool(self, name: str, arguments: dict) -> Optional[dict]:
        if not self.is_running():
            return None
        return self._send("tools/call", {"name": name, "arguments": arguments}, timeout=20.0)


BUILTIN_TOOLS = {
    "roblox_studio_mcp": {
        "name": "Roblox Integration",
        "description": "Lets the AI read the full game hierarchy, list objects, get properties, create and edit scripts and instances in your Roblox Studio game.",
        "command": "cmd.exe",
        "args": ["/c", "%LOCALAPPDATA%\\Roblox\\mcp.bat"],
        "enabled": False,
    },
    "advanced_thinking": {
        "name": "Advanced Reasoning",
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
        client = self.mcp_clients.get(tid)
        if not client:
            return False
        if client.is_running():
            return True
        ok, _ = client.start()
        if ok:
            self._mcp_tools_cache[tid] = client.list_tools()
        return ok

    def _normalize_schema(self, schema: dict) -> dict:
        if not isinstance(schema, dict) or not schema:
            return {"type": "object", "properties": {}, "required": []}
        normalized = dict(schema)
        normalized.setdefault("type", "object")
        normalized.setdefault("properties", {})
        if "required" not in normalized or not isinstance(normalized["required"], list):
            normalized["required"] = []
        return normalized

    def _get_running_mcp_client(self, session_tools: dict) -> tuple[Optional[str], Optional[MCPClient]]:
        for tid in self.tool_defs:
            if self.is_enabled(tid, session_tools) and tid in self.mcp_clients:
                if self._ensure_running(tid):
                    return tid, self.mcp_clients[tid]
        return None, None

    def _get_cached_mcp_tools(self, session_tools: dict) -> list[dict]:
        tools = []
        for tid in self.tool_defs:
            if self.is_enabled(tid, session_tools) and tid in self.mcp_clients:
                if self._ensure_running(tid):
                    tools.extend(self._mcp_tools_cache.get(tid, []))
        return tools

    def _find_tool_by_name_patterns(self, session_tools: dict, patterns: list[str]) -> list[dict]:
        matches = []
        for tool in self._get_cached_mcp_tools(session_tools):
            name = (tool.get("name") or "").lower()
            if all(pattern in name for pattern in patterns):
                matches.append(tool)
        return matches

    def _build_call_args(self, schema: dict, seed: dict) -> dict:
        props = (schema or {}).get("properties", {})
        if not isinstance(props, dict):
            return dict(seed)
        args = {}
        alias_map = {
            "query": ["query", "search", "pattern", "text", "needle", "term", "name"],
            "max_results": ["limit", "max", "count", "maxResults", "numResults"],
            "context_chars": ["context", "contextChars", "radius", "around"],
            "script_name": ["script", "scriptName", "name", "path", "instancePath", "fullName"],
            "source": ["source", "content", "text", "scriptSource"],
        }
        for key, value in seed.items():
            aliases = alias_map.get(key, [key])
            for alias in aliases:
                if alias in props:
                    args[alias] = value
        return args or dict(seed)

    def _call_named_tool(self, session_tools: dict, tool_name: str, seed: dict) -> Optional[dict]:
        _, client = self._get_running_mcp_client(session_tools)
        if not client:
            return None
        tool_meta = next((t for t in self._get_cached_mcp_tools(session_tools) if t.get("name") == tool_name), None)
        call_args = self._build_call_args(tool_meta.get("inputSchema", {}) if tool_meta else {}, seed)
        return client.call_tool(tool_name, call_args)

    def _extract_text_payload(self, result: Optional[dict]) -> str:
        if not result or "result" not in result:
            return ""
        payload = result["result"]
        if isinstance(payload, dict):
            content = payload.get("content", [])
            if isinstance(content, list):
                parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                return "\n".join(part for part in parts if part).strip()
        if isinstance(payload, str):
            return payload.strip()
        return ""

    def _extract_json_payload(self, result: Optional[dict]):
        text = self._extract_text_payload(result)
        if not text:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    def _codebase_grep_tool_def(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "codebase_grep",
                "description": (
                    "Search through many Roblox scripts at once. Use this when you need to find code patterns, "
                    "APIs, variable names, or behavior across the whole game."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The text or pattern to search for."},
                        "max_results": {"type": "integer", "description": "Maximum matches to return.", "default": 25},
                        "context_chars": {"type": "integer", "description": "Snippet size around each match.", "default": 120},
                    },
                    "required": ["query"],
                },
            },
        }

    def _fallback_codebase_grep(self, session_tools: dict, query: str, max_results: int, context_chars: int) -> str:
        list_candidates = [
            ["list", "script"],
            ["get", "scripts"],
            ["find", "script"],
        ]
        read_candidates = [
            ["get", "source"],
            ["script", "source"],
            ["read", "script"],
            ["get", "script"],
        ]
        list_tools = []
        for patterns in list_candidates:
            list_tools.extend(self._find_tool_by_name_patterns(session_tools, patterns))
        read_tools = []
        for patterns in read_candidates:
            read_tools.extend(self._find_tool_by_name_patterns(session_tools, patterns))
        if not list_tools or not read_tools:
            return json.dumps([{
                "type": "text",
                "text": "codebase_grep could not find compatible Roblox MCP script listing/reading tools."
            }])

        listed = self._call_named_tool(session_tools, list_tools[0]["name"], {"limit": max(100, max_results * 4)})
        scripts = self._extract_json_payload(listed)
        if not isinstance(scripts, list):
            raw = self._extract_text_payload(listed)
            scripts = []
            for line in raw.splitlines():
                line = line.strip()
                if line:
                    scripts.append({"name": line})

        matches = []
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        for script in scripts[:200]:
            if len(matches) >= max_results:
                break
            if not isinstance(script, dict):
                continue
            identifier = (
                script.get("path")
                or script.get("fullName")
                or script.get("name")
                or script.get("script")
                or script.get("instancePath")
            )
            if not identifier:
                continue
            source_result = self._call_named_tool(session_tools, read_tools[0]["name"], {"script_name": identifier})
            source_text = self._extract_text_payload(source_result)
            if not source_text:
                parsed = self._extract_json_payload(source_result)
                if isinstance(parsed, dict):
                    source_text = (
                        parsed.get("source")
                        or parsed.get("content")
                        or parsed.get("text")
                        or parsed.get("scriptSource")
                        or ""
                    )
            if not source_text:
                continue
            for found in pattern.finditer(source_text):
                start = max(0, found.start() - context_chars)
                end = min(len(source_text), found.end() + context_chars)
                matches.append({
                    "script": identifier,
                    "match": found.group(0),
                    "snippet": source_text[start:end].replace("\r", ""),
                })
                if len(matches) >= max_results:
                    break

        if not matches:
            return json.dumps([{"type": "text", "text": f"No codebase matches found for '{query}'."}])
        return json.dumps([{"type": "text", "text": json.dumps(matches, ensure_ascii=False)}])

    def _handle_codebase_grep(self, arguments: dict, session_tools: dict) -> str:
        query = (arguments or {}).get("query", "").strip()
        if not query:
            return json.dumps([{"type": "text", "text": "codebase_grep requires a query."}])
        max_results = max(1, min(int((arguments or {}).get("max_results", 25) or 25), 100))
        context_chars = max(20, min(int((arguments or {}).get("context_chars", 120) or 120), 400))

        direct = self._find_tool_by_name_patterns(session_tools, ["grep"])
        if direct:
            result = self._call_named_tool(
                session_tools,
                direct[0]["name"],
                {"query": query, "max_results": max_results, "context_chars": context_chars},
            )
            if result and "result" in result:
                payload = result["result"]
                if isinstance(payload, dict):
                    return json.dumps(payload.get("content", payload))
                return json.dumps([{"type": "text", "text": str(payload)}])

        return self._fallback_codebase_grep(session_tools, query, max_results, context_chars)

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
            if enabled and tid in self.mcp_clients and self._ensure_running(tid):
                entry["mcp_count"] = len(self._mcp_tools_cache.get(tid, []))
            result.append(entry)
        return result

    def toggle_tool(self, tool_id: str, session_tools: dict) -> tuple[dict, dict]:
        if tool_id not in self.tool_defs:
            return {"ok": False, "error": "Tool not found"}, session_tools
        new_enabled = not session_tools.get(tool_id, False)
        session_tools = dict(session_tools)
        session_tools[tool_id] = new_enabled
        if new_enabled and tool_id in self.mcp_clients:
            ok = self._ensure_running(tool_id)
            if ok:
                return {"ok": True, "enabled": True, "message": "Connected"}, session_tools
            session_tools[tool_id] = False
            return {"ok": False, "enabled": False, "message": "Failed to start MCP"}, session_tools
        if not new_enabled and tool_id in self.mcp_clients:
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
        return "Active tools:\n" + "\n".join(lines) if lines else ""

    def get_all_mcp_tool_names(self) -> list[str]:
        """Returns all MCP tool names from ALL integrations (even disabled ones)."""
        names = []
        for tid, client in self.mcp_clients.items():
            if client.is_running() or client.start()[0]:
                if tid not in self._mcp_tools_cache or not self._mcp_tools_cache[tid]:
                    self._mcp_tools_cache[tid] = client.list_tools()
                for tool in self._mcp_tools_cache.get(tid, []):
                    names.append(tool.get("name", ""))
        return [n for n in names if n]

    def get_openai_tools(self, session_tools: dict) -> list[dict]:
        all_tools = []
        for tid in self.tool_defs:
            if self.is_enabled(tid, session_tools) and tid in self.mcp_clients:
                if not self._ensure_running(tid):
                    continue
                for mt in self._mcp_tools_cache.get(tid, []):
                    all_tools.append({
                        "type": "function",
                        "function": {
                            "name": mt["name"],
                            "description": mt.get("description", ""),
                            "parameters": self._normalize_schema(mt.get("inputSchema", {})),
                        },
                    })
        if self.is_enabled("roblox_studio_mcp", session_tools):
            all_tools.append(self._codebase_grep_tool_def())
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
        is_search = any(x in tool_name.lower() for x in ["search", "find", "query", "lookup", "browse"])
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
                likes = abs(item.get("likeCount") or item.get("likes") or item.get("rating") or item.get("favorites") or 0)
                updated = item.get("updated") or item.get("lastUpdated") or item.get("date") or ""
                scored.append((likes, updated, item))
            scored.sort(key=lambda x: (-x[0], x[1] or ""))
            top = [s[2] for s in scored[:3]]
            return json.dumps(top) if top else raw_text
        except (json.JSONDecodeError, TypeError):
            lines = raw_text.split("\n")
            groups = []
            current = []
            for line in lines:
                if line.strip() and not line.startswith(" "):
                    if current:
                        groups.append("\n".join(current))
                    current = [line]
                else:
                    current.append(line)
            if current:
                groups.append("\n".join(current))

            def extract_likes(group: str) -> int:
                import re
                match = re.search(r"(?:Likes|Rating|Favorites):\s*(\d+)", group, re.IGNORECASE)
                return int(match.group(1)) if match else 0

            groups.sort(key=extract_likes, reverse=True)
            return "\n\n".join(groups[:3])

    def _clean_tool_output(self, text: str) -> str:
        import re
        text = text.replace("â†’", "\n")
        text = re.sub(r"(\d+)\n(?=\S)", r"\1. ", text)
        text = re.sub(r"^\d+[.â†’]\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def handle_tool_call(self, tool_name: str, arguments: dict, session_tools: dict) -> Optional[str]:
        if tool_name == "codebase_grep":
            return self._handle_codebase_grep(arguments, session_tools)
        for tid in self.tool_defs:
            if not self.is_enabled(tid, session_tools) or tid not in self.mcp_clients:
                continue
            if not self._ensure_running(tid):
                continue
            client = self.mcp_clients[tid]
            result = client.call_tool(tool_name, arguments)
            if result is None:
                client.stop()
                if self._ensure_running(tid):
                    result = self.mcp_clients[tid].call_tool(tool_name, arguments)
            if not result:
                continue
            if "result" in result:
                payload = result["result"]
                if isinstance(payload, dict):
                    content = payload.get("content", [])
                    if isinstance(content, list):
                        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                        if texts:
                            combined = self._clean_tool_output("\n".join(texts))
                            filtered = self._filter_search_results(tool_name, combined)
                            return json.dumps([{"type": "text", "text": filtered}])
                        return json.dumps(content)
                    return json.dumps(payload)
                return json.dumps(payload)
            error_message = client._extract_error_message(result) or "Tool call failed"
            return json.dumps([{"type": "text", "text": f"MCP error from {tool_name}: {error_message}"}])
        return json.dumps([{"type": "text", "text": f"MCP tool unavailable: {tool_name}"}])
