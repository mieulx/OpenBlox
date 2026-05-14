# Security Review — OpenBlox

## Summary
This app runs **locally only** (localhost:8520). It stores an API key locally and communicates with the Kilo AI API. There are no user accounts, no shared databases, and no external network exposure in normal use.

---

## Issues Found

### 1. API key stored in plaintext (config.json)
- **File**: `config.json`
- **Risk**: Low (local-only app)
- **Mitigation**: `config.json` is in `.gitignore` — never pushed to GitHub.
- **Note**: The key is readable by anyone with access to your filesystem.

### 2. CORS allows all origins
- **File**: `server.py:22`
  ```python
  app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
  ```
- **Risk**: Low (local-only). If the port were exposed to a network, any website could call the API.
- **Fix**: Change to `allow_origins=["http://localhost:8520"]` for production.

### 3. No API authentication on the backend
- **File**: `server.py` — all endpoints
- **Risk**: Low. The server listens on `0.0.0.0:8520` which is accessible to anyone on the local network.
- **Fix**: Change `host` to `"127.0.0.1"` in production to bind to localhost only.

### 4. Subprocess runs user-defined MCP command
- **File**: `tools_manager.py:22-29`
  ```python
  self.process = subprocess.Popen(expanded, ...)
  ```
- **Risk**: Low. The command is hardcoded (`cmd.exe /c %LOCALAPPDATA%\Roblox\mcp.bat`). `%LOCALAPPDATA%` is expanded via `os.path.expandvars()`.
- **Note**: If the `.bat` file were replaced by malware, the app would execute it.
- **Fix**: Validate the resolved path exists and is within `%LOCALAPPDATA%\Roblox\` before execution.

### 5. No timeout on MCP subprocess reads
- **File**: `tools_manager.py:65`
  ```python
  line = self.process.stdout.readline()
  ```
- **Risk**: Medium. If the MCP server doesn't respond, `readline()` blocks **forever** — the entire server thread hangs.
- **Fix**: Use `select()` or `threading.Thread` with a timeout wrapper.

### 6. Session IDs exposed in URLs
- **File**: `server.py:141,147,153,166`
- **Risk**: Low (local-only). Session IDs are random 12-char hex strings (`uuid.uuid4().hex[:12]`).
- **Note**: No sensitive data is keyed off sessions alone.

### 7. No input length limits
- **File**: `server.py:41-45` — ChatRequest accepts arbitrary-length messages.
- **Risk**: Low. Messages are sent to the Kilo API which has its own limits.
- **Fix**: Add `max_length` to Pydantic models.

### 8. User context stored in config.json without sanitization
- **File**: `server.py:111` — `cfg.user_context` is stored as-is.
- **Risk**: Low. Content is only sent to the Kilo API, never executed.

### 9. Export header injection possible
- **File**: `server.py:161-162`
  ```python
  headers={"Content-Disposition": f"attachment; filename={s.title}.txt"}
  ```
- **Risk**: Low. The session title is user-controlled but only affects the download filename. No path traversal possible since it's a header value, not a filesystem path.

---

## Recommendations

| Priority | Fix |
|----------|-----|
| **High** | Add timeout to MCP `readline()` — wrap in `select()` or move to a thread with `Thread.join(timeout=5)` |
| **Medium** | Bind server to `127.0.0.1` instead of `0.0.0.0` |
| **Medium** | Restrict CORS to `http://localhost:8520` |
| **Low** | Validate MCP `.bat` path exists before launching |
| **Low** | Add `max_length=10000` to message fields in Pydantic models |

---

## Dependencies with known issues

All packages are standard/popular with no known critical CVEs relevant to this usage:

| Package | Version | Notes |
|---------|---------|-------|
| fastapi | latest | Standard web framework |
| uvicorn | latest | ASGI server, local only |
| requests | latest | HTTPS to Kilo API only |
| beautifulsoup4 | latest | HTML parsing, fetch only |
| lxml | latest | XML parsing |
