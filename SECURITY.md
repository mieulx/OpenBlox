# Security Notes

## Overview

OpenBlox is intended to run locally on a single Windows machine. The backend serves a local web UI, stores configuration and chats on disk, and sends model requests to the configured external AI API.

Current defaults in the codebase:

- Backend bind address: `127.0.0.1`
- Default port: `8520`
- Allowed browser origins:
  - `http://localhost:8520`
  - `http://127.0.0.1:8520`
- User data location:
  - `%APPDATA%\OpenBlox\config.json`
  - `%APPDATA%\OpenBlox\chats\`

## Data handled by the app

OpenBlox may store or transmit:

- API keys
- chat messages
- model selection and temperature
- user context/instructions
- website source configuration
- MCP tool outputs

OpenBlox does not currently include:

- multi-user auth
- role-based permissions
- encryption at rest
- server-side session auth
- database-backed secret management

## Current security posture

### Local-only backend

`server.py` runs Uvicorn on `127.0.0.1`, not `0.0.0.0`. This is a good default for a local desktop tool because it avoids exposing the API to the local network under normal use.

### Restricted CORS

CORS is limited to the two local frontend origins used by the app. This is safer than wildcard CORS for a localhost tool.

### AppData persistence

API keys and chats are stored in AppData instead of the repository folder. This reduces accidental loss during updates and reduces the chance of committing sensitive files from the working tree. It does not encrypt the data.

### MCP process hardening

The MCP client in `tools_manager.py` now includes:

- explicit process start/stop handling
- path existence checks for the Roblox MCP batch file
- request/response tracking by id
- background stdout and stderr readers
- timeout-based waiting for MCP responses
- restart/reconnect behavior when a tool call fails due to a dead client

This is materially safer and more reliable than a blocking single-read approach.

## Remaining risks

### Plaintext API key storage

The API key is still stored in plaintext JSON in `%APPDATA%\OpenBlox\config.json`.

Risk:
- anyone with access to the user profile can read it

Mitigations you may want later:

- Windows Credential Manager storage
- DPAPI encryption
- environment variable or token-provider support

### No backend authentication

Any local process able to reach `127.0.0.1:8520` can call the API routes while the app is running.

Risk:
- local malware or another local process could read or modify local app state

This is acceptable for many local tools, but it is not a hardened trust boundary.

### MCP trust boundary

OpenBlox can launch a local MCP batch file from:

`%LOCALAPPDATA%\Roblox\mcp.bat`

Risk:
- if that batch file or its downstream binaries are replaced, OpenBlox will execute the replaced code

Current mitigation:
- the path is expanded and checked for existence before launch

Good future hardening:

- validate the resolved path is inside the expected Roblox directory
- verify file ownership or signature if practical

### Prompt injection through tool or site content

OpenBlox can ingest external web content and MCP tool output, then pass it to the model.

Risk:
- malicious or noisy content may influence model behavior

The app does not currently implement a strong trust separation between user prompts, fetched content, and tool text beyond prompt wording and tool-loop control.

### File-based persistence

Chats are saved as individual JSON files in AppData.

Risk:
- local tampering is possible
- there is no integrity checking

### No explicit input size enforcement

The app relies mostly on model/API limits and internal context handling rather than hard request-size validation on all user inputs.

Risk:
- oversized local requests may still create memory or UX issues

## Security recommendations

High value next steps:

- move API key storage to Windows Credential Manager or DPAPI
- add optional backend auth token for localhost API calls
- add explicit maximum lengths for chat/config inputs
- validate the resolved MCP batch path is inside the expected Roblox directory
- add structured logging for updater and MCP failures
- consider marking sensitive config fields more carefully in exported/debug contexts

## Dependency and update posture

The project currently uses standard Python packages such as:

- `fastapi`
- `uvicorn`
- `pydantic`
- `requests`
- `beautifulsoup4`
- `lxml`

Security still depends on keeping these dependencies updated on the local machine. The provided Windows batch helper upgrades `pip` and reinstalls requirements, but it is not a vulnerability scanner.

## Reporting

If you discover a security issue, avoid posting secrets or exploit details publicly in issue threads. Share a minimal reproduction and affected files/flows privately with the maintainer first if possible.
