# OpenBlox

OpenBlox is a local Roblox Studio assistant built around a FastAPI backend and a static web client. It is designed to help with Roblox-focused chat, Luau scripting, documentation lookup, context management, and optional MCP-based Roblox Studio integration.

## What it does

- Runs a local web app at `http://localhost:8520`
- Stores chat sessions per conversation
- Saves API settings, model selection, search settings, and user context
- Supports a Roblox Studio MCP integration for tool calls
- Supports optional advanced self-review and automatic context compaction
- Streams responses to the browser UI

## Architecture

- `server.py`: FastAPI app and API routes
- `frontend/`: static HTML/CSS/JS web client
- `openblox_client.py`: chat completion client and tool/review loop
- `tools_manager.py`: built-in tool state and MCP client lifecycle
- `chat_store.py`: session persistence
- `website_manager.py`: config and website source persistence
- `installer.py`: GUI and terminal installer/updater
- `openblox_update_and_run.bat`: Windows update + install + launch helper

## Requirements

- Windows
- Python 3.12 recommended
- Internet access for the AI API and optional documentation lookups
- Roblox Studio MCP installed locally if you want tool integration

## Install

```bash
git clone https://github.com/Artemcik5/OpenBlox.git
cd OpenBlox
python -m pip install -r requirements.txt
python run.py
```

Then open [http://localhost:8520](http://localhost:8520).

## Windows helper

If you want a one-click update/install flow on Windows, run:

```bat
openblox_update_and_run.bat
```

This batch file:

- upgrades `pip`
- installs `requirements.txt`
- runs `installer.py` in terminal mode
- launches `run.py` in a visible terminal window

## Updating

You can update in two ways:

1. Run `openblox_update_and_run.bat`
2. Run `installer.py` directly

Examples:

```bash
python installer.py
```

```bash
python installer.py --terminal --path "C:\path\to\OpenBlox" --launch
```

The updater now preserves only repo assets that belong in the install folder. User data is stored in AppData, so updating does not depend on keeping local `config.json` or `chats/` inside the repository.

## Data storage

OpenBlox stores user data in AppData:

- Config and API settings: `%APPDATA%\OpenBlox\config.json`
- Chat sessions: `%APPDATA%\OpenBlox\chats\`

On startup, OpenBlox will migrate older repo-local `config.json` and `chats/` data into AppData if present.

## Current behavior

- The backend binds to `127.0.0.1:8520`
- CORS is restricted to `http://localhost:8520` and `http://127.0.0.1:8520`
- The frontend is served directly by FastAPI using `StaticFiles`
- Sessions are saved as JSON files
- Advanced thinking performs at most one internal review pass for substantive answers
- MCP tools are exposed only when enabled in a session

## Development notes

- `run.py` starts the local server
- `requirements.txt` contains the Python dependencies
- The frontend is plain HTML/CSS/JavaScript, not a bundled SPA framework
- The default model is currently `nvidia/nemotron-3-super-120b-a12b:free`

## Known limitations

- This project is Roblox-specific by design and will redirect non-Roblox questions
- There is no login/auth system because the app is intended for local use
- Session storage is file-based rather than database-backed
- MCP availability depends on the local Roblox MCP setup
- There is no packaged executable in the repository yet

## Contributing

Contributions are welcome.

Typical workflow:

1. Fork the repository
2. Create a branch
3. Make your changes
4. Test locally
5. Open a pull request

## License

This project is licensed under the terms of the included [LICENSE](./LICENSE).
