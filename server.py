import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import json as json_mod
import re
import threading
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import uvicorn

from website_manager import WebsiteManager
from extractor import ContentExtractor
from openblox_client import OpenBloxClient
from chat_store import ChatStore, ChatSession, ChatMessage
from processor import DevProcessor
from tools_manager import ToolsManager


app = FastAPI(title="OpenBlox Roblox Studio Helper")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8520", "http://127.0.0.1:8520"], allow_methods=["*"], allow_headers=["*"])

wm = WebsiteManager()
extractor = ContentExtractor(chunk_size=wm.search_config["chunk_size"])
store = ChatStore()
dev_proc = DevProcessor(wm, extractor)

app_config = wm.openblox_config
user_context = app_config.get("user_context", "")
ai_client = OpenBloxClient(
    api_key=app_config.get("api_key", ""),
    model=app_config.get("model", "nvidia/nemotron-3-super-120b-a12b:free"),
    temperature=app_config.get("temperature", 0.3),
    user_context=user_context,
)

tools_mgr = ToolsManager()


# Permission system: pending requests
_pending_permissions: dict[str, dict] = {}
_permission_cache: dict[str, str] = {}  # tool_name -> "always" or "session"

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    dev_mode: bool = False
    edit_index: Optional[int] = None
    agent_mode: bool = False
    subagent_model: Optional[str] = ""
    max_subagents: Optional[int] = 2
    chain_thought: Optional[bool] = False


class ConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    user_context: Optional[str] = None
    max_chunks: Optional[int] = None
    chunk_size: Optional[int] = None
    subagent_model: Optional[str] = None
    max_subagents: Optional[int] = None
    chain_thought: Optional[bool] = None
    dev_mode: Optional[bool] = None
    permissions_enabled: Optional[bool] = None
    allowed_tools: Optional[list[str]] = None


class PlanUpdate(BaseModel):
    index: int
    done: bool


class RenameRequest(BaseModel):
    title: str


class EditMessageRequest(BaseModel):
    message: str
    edit_index: int


class ToolToggle(BaseModel):
    tool_id: str
    session_id: Optional[str] = None


class CompactRequest(BaseModel):
    session_id: Optional[str] = None


class PermissionRespond(BaseModel):
    request_id: str
    decision: str  # "decline", "allow_once", "allow_command", "allow_always"
    tool_name: Optional[str] = ""
    session_id: Optional[str] = ""


class SessionPermToggle(BaseModel):
    session_id: str
    disabled: bool


def make_client():
    ctx = wm.openblox_config.get("user_context", "")
    return OpenBloxClient(
        api_key=wm.openblox_config.get("api_key", ""),
        model=wm.openblox_config.get("model", "nvidia/nemotron-3-super-120b-a12b:free"),
        temperature=wm.openblox_config.get("temperature", 0.3),
        user_context=ctx,
    )


@app.get("/api/health")
async def health():
    return {"ok": True}


VERSION_FILE = os.path.join(os.path.dirname(__file__), "version")
VERSION = open(VERSION_FILE, "r").read().strip() if os.path.exists(VERSION_FILE) else "0.0.0"


@app.get("/api/version")
async def get_version():
    return {"version": VERSION}


@app.get("/api/status")
async def status():
    try:
        return {
            "configured": make_client().is_configured(),
            "model": make_client().model,
            "sessions": len(store.sessions),
            "websites": len(wm.websites),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/config")
async def get_config():
    try:
        return {
            "api_key": bool(wm.openblox_config.get("api_key", "")),
            "model": wm.openblox_config.get("model", "nvidia/nemotron-3-super-120b-a12b:free"),
            "temperature": wm.openblox_config.get("temperature", 0.3),
            "user_context": wm.openblox_config.get("user_context", ""),
            "max_chunks": wm.search_config.get("max_chunks", 8),
            "chunk_size": wm.search_config.get("chunk_size", 1500),
            "subagent_model": wm.openblox_config.get("subagent_model", ""),
            "max_subagents": wm.openblox_config.get("max_subagents", 2),
            "chain_thought": wm.openblox_config.get("chain_thought", False),
            "dev_mode": wm.openblox_config.get("dev_mode", False),
            "permissions_enabled": wm.openblox_config.get("permissions_enabled", True),
            "allowed_tools": wm.openblox_config.get("allowed_tools", []),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/config")
async def save_config(cfg: ConfigUpdate):
    try:
        if cfg.api_key is not None:
            wm.openblox_config["api_key"] = cfg.api_key
        if cfg.model is not None:
            wm.openblox_config["model"] = cfg.model
        if cfg.temperature is not None:
            wm.openblox_config["temperature"] = cfg.temperature
        if cfg.user_context is not None:
            wm.openblox_config["user_context"] = cfg.user_context
        if cfg.max_chunks is not None:
            wm.search_config["max_chunks"] = cfg.max_chunks
        if cfg.chunk_size is not None:
            wm.search_config["chunk_size"] = cfg.chunk_size
        if cfg.subagent_model is not None:
            wm.openblox_config["subagent_model"] = cfg.subagent_model
        if cfg.max_subagents is not None:
            wm.openblox_config["max_subagents"] = cfg.max_subagents
        if cfg.chain_thought is not None:
            wm.openblox_config["chain_thought"] = cfg.chain_thought
        if cfg.dev_mode is not None:
            wm.openblox_config["dev_mode"] = cfg.dev_mode
        if cfg.permissions_enabled is not None:
            wm.openblox_config["permissions_enabled"] = cfg.permissions_enabled
        if cfg.allowed_tools is not None:
            wm.openblox_config["allowed_tools"] = cfg.allowed_tools
        wm.save()
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/models")
async def list_models():
    try:
        all_m, free_m = make_client().fetch_models()
        return {"models": all_m, "free_models": free_m}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


def _get_session(session_id: str):
    for s in store.sessions:
        if s.id == session_id:
            return s
    return None


@app.get("/api/sessions")
async def list_sessions():
    try:
        return {
            "sessions": [s.to_dict() for s in store.sessions],
            "active_id": store.active_id,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/sessions")
async def create_session():
    try:
        s = store.new_session()
        return s.to_dict()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    try:
        store.delete_session(session_id)
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.patch("/api/sessions/{session_id}/rename")
async def rename_session(session_id: str, req: RenameRequest):
    try:
        store.rename_session(session_id, req.title)
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str):
    try:
        s = _get_session(session_id)
        if not s:
            raise HTTPException(404, "Session not found")
        lines = [f"OpenBlox — {s.title}", "=" * 50, ""]
        for m in s.messages:
            prefix = "You:" if m.role == "user" else "Assistant:"
            lines.append(f"{prefix}\n{m.content}\n")
        safe_title = "".join(c for c in s.title if c.isalnum() or c in ' _-').strip() or "chat"
        return PlainTextResponse("\n".join(lines),
            headers={"Content-Disposition": f"attachment; filename={safe_title}.txt"})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    try:
        s = _get_session(session_id)
        if not s:
            raise HTTPException(404, "Session not found")
        return s.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/chat")
async def chat(req: ChatRequest):
    ai_client = make_client()
    if not ai_client.is_configured():
        return JSONResponse(status_code=400, content={"error": "API key not configured."})

    session = None
    if req.session_id:
        for s in store.sessions:
            if s.id == req.session_id:
                session = s
                break
    if not session:
        session = store.get_active()
    if session.model:
        ai_client.model = session.model

    if req.edit_index is not None and 0 <= req.edit_index < len(session.messages):
        session.messages = session.messages[:req.edit_index]
        if req.message:
            session.add_message("user", req.message)
    elif req.message:
        session.add_message("user", req.message)

    if len(session.messages) == 1:
        store.rename_session(session.id, req.message[:40] if req.message else "Chat")
    store.save_session(session)

    dev_chunks = []
    doc_ctx = ""
    if req.dev_mode:
        dev_chunks = dev_proc.fetch_for_query(req.message or "")
        if dev_chunks:
            doc_ctx = dev_proc.build_context(dev_chunks)

    history = [{"role": m.role, "content": m.content} for m in session.messages]

    st = session.tools
    tool_ctx = tools_mgr.get_enabled_context(st)
    extra = tool_ctx if tool_ctx else ""

    # Auto-compact if context >= 70%
    if st.get("context_compactor", True) and session.context_pct() >= 70:
        compact_note = _compact_session(session, ai_client)
        history = [{"role": m.role, "content": m.content} for m in session.messages]
        if compact_note:
            extra += f"\n\n[Auto: {compact_note}]"

    openai_tools = tools_mgr.get_openai_tools(st)
    def _handler(name, args):
        if name == "compact_context":
            return _compact_session(session, ai_client) or "Context compacted."
        return tools_mgr.handle_tool_call(name, args, st) if openai_tools else None
    tool_handler = _handler if (openai_tools or st.get("context_compactor", True)) else None
    advanced = st.get("advanced_thinking", False)
    agent_context = ""
    if st.get("roblox_studio_mcp", False):
        agent_context = (
            "Roblox Studio integration is ACTIVE and CONNECTED. "
            "You MUST use the MCP tools to make ALL edits to the game. "
            "NEVER output script code in chat — write every script directly to Studio via MCP. "
            "Describe what you did in one plain sentence without showing code."
        )
    combined_extra = _compose_extra_context(extra, doc_ctx, agent_context)

    if req.dev_mode and dev_chunks:
        response = ai_client.chat_with_context(
            history, doc_ctx, extra_context=_compose_extra_context(extra, "", agent_context),
            tools=openai_tools or None, tool_handler=tool_handler,
            advanced_thinking=advanced)
    else:
        response = ai_client.chat(
            history, extra_context=combined_extra,
            tools=openai_tools or None, tool_handler=tool_handler,
            advanced_thinking=advanced)

    if response is None:
        response = "No response from API."

    session.add_message("assistant", response)
    store.save_session(session)

    dev_out = []
    if req.dev_mode:
        dev_out = [
            {"heading": c.heading_path or c.source_url, "text": c.text[:500]}
            for c in dev_chunks[:5]
        ]
    return {
        "response": response,
        "session": session.to_dict(),
        "dev_chunks": dev_out,
    }



def _get_integration_name(st: dict) -> str:
    for tid, cfg in tools_mgr.tool_defs.items():
        if st.get(tid, False) and cfg.get("command"):
            return cfg.get("name", "Tool")
    return ""


def _extract_json_object(text: str) -> dict:
    if not text:
        return {}
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        return json_mod.loads(match.group(0))
    except json_mod.JSONDecodeError:
        return {}







def _compose_extra_context(base: str = "", doc_ctx: str = "", agent_ctx: str = "") -> str:
    parts = [part for part in [base, agent_ctx] if part]
    if doc_ctx:
        parts.append(f"Relevant documentation:\n{doc_ctx}")
    return "\n\n".join(parts)


def _build_agent_plan(ai_client, history: list, extra_context: str, active_tools: list[str], max_subagents: int = 2) -> dict:
    planner_prompt = (
        "You are the OpenBlox planner. Decide whether this request should stay single-agent or use subagents. "
        f"Never use more than {max_subagents} subagents. Prefer 0 when the task is simple.\n\n"
        f"Active tools: {', '.join(active_tools) if active_tools else 'none'}.\n"
        "Return strict JSON with this shape:\n"
        "{\n"
        '  "summary": string,\n'
        '  "use_subagents": boolean,\n'
        '  "main_steps": [string],\n'
        '  "subagents": [{"name": string, "goal": string, "use_tools": boolean}]\n'
        "}\n"
        "Keep main_steps concise (max 6) and actionable."
    )
    planning_history = list(history) + [{"role": "user", "content": planner_prompt}]
    raw = ai_client.chat(planning_history, max_tokens=700, extra_context=extra_context) or ""
    plan = _extract_json_object(raw)
    steps = [step for step in plan.get("main_steps", []) if isinstance(step, str) and step.strip()][:6]
    subagents = []
    for item in plan.get("subagents", [])[:min(max_subagents, 3)]:
        if isinstance(item, dict) and item.get("name") and item.get("goal"):
            subagents.append({
                "name": str(item["name"]).strip(),
                "goal": str(item["goal"]).strip(),
                "use_tools": bool(item.get("use_tools", False)),
            })
    return {
        "summary": plan.get("summary", "Plan the work, gather context, then execute."),
        "use_subagents": bool(plan.get("use_subagents")) and bool(subagents),
        "main_steps": steps or ["Inspect the request", "Execute the change", "Report the result"],
        "subagents": subagents,
    }


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    ai_client = make_client()
    if not ai_client.is_configured():
        return JSONResponse(status_code=400, content={"error": "API key not configured."})

    session = None
    if req.session_id:
        for s in store.sessions:
            if s.id == req.session_id:
                session = s
                break
    if not session:
        session = store.get_active()
    if session.model:
        ai_client.model = session.model

    if req.edit_index is not None and 0 <= req.edit_index < len(session.messages):
        session.messages = session.messages[:req.edit_index]
        if req.message:
            session.add_message("user", req.message)
    elif req.message:
        session.add_message("user", req.message)

    if len(session.messages) == 1:
        store.rename_session(session.id, req.message[:40] if req.message else "Chat")
    store.save_session(session)

    history = [{"role": m.role, "content": m.content} for m in session.messages]
    st = session.tools
    tool_ctx = tools_mgr.get_enabled_context(st)
    extra = tool_ctx if tool_ctx else ""

    if st.get("context_compactor", True) and session.context_pct() >= 70:
        compact_note = _compact_session(session, ai_client)
        history = [{"role": m.role, "content": m.content} for m in session.messages]
        if compact_note:
            extra += f"\n\n[Auto: {compact_note}]"

    openai_tools = tools_mgr.get_openai_tools(st)
    perm_enabled = wm.openblox_config.get("permissions_enabled", True)
    perm_cache = {}

    def is_asset_tool(name):
        asset_keywords = ["create", "import", "insert", "add", "spawn", "place", "marketplace", "asset"]
        nl = name.lower()
        return any(k in nl for k in asset_keywords)

    # Checks permission and BLOCKS until the user responds.
    # Returns: (True, None) if granted, (False, result_json) if declined.
    def _perm_check_and_block(name):
        if name == "compact_context":
            return True, None
        needs_perm = perm_enabled and not session.permissions_disabled
        allowed_list = wm.openblox_config.get("allowed_tools", [])
        if name in allowed_list or "*" in allowed_list:
            needs_perm = False
        if needs_perm:
            cached = perm_cache.get(name)
            if cached != "always":
                cached = _permission_cache.get(name)
            if cached != "always":
                cached = _permission_cache.get("*")
            if cached == "always":
                needs_perm = False
        if not needs_perm:
            return True, None
        req_id = f"perm-{name}-{len(_pending_permissions)}"
        evt = threading.Event()
        _pending_permissions[req_id] = {"event": evt, "decision": None, "tool_name": name, "is_asset": is_asset_tool(name)}
        evt.wait(timeout=120)
        entry = _pending_permissions.get(req_id, {})
        decision = entry.get("decision")
        if decision is None:
            decision = "decline"
        _pending_permissions.pop(req_id, None)
        if decision == "decline":
            return False, json.dumps([{"type": "text", "text": "User declined this action."}])
        if decision == "allow_command":
            perm_cache[name] = "always"
        elif decision == "allow_always":
            _permission_cache["*"] = "always"
        return True, None

    # Wrap the tool handler to check permissions before executing
    def _wrapped_tool_handler(name, args):
        if not openai_tools:
            return None
        allowed, override_result = _perm_check_and_block(name)
        if not allowed:
            return override_result
        return tools_mgr.handle_tool_call(name, args, st)

    tool_handler = _wrapped_tool_handler if (openai_tools or st.get("context_compactor", True)) else None
    advanced = st.get("advanced_thinking", False)
    integration_name = _get_integration_name(st)

    dev_chunks = []
    doc_ctx = ""
    if req.dev_mode:
        dev_chunks = dev_proc.fetch_for_query(req.message or "")
        if dev_chunks:
            doc_ctx = dev_proc.build_context(dev_chunks)

    def event_stream():
        nonlocal tool_handler
        final_content = "(no response)"
        planner_plan = None
        if req.dev_mode and dev_chunks:
            dev_event = {
                "type": "dev",
                "chunks": [
                    {"heading": c.heading_path or c.source_url, "text": c.text[:500]}
                    for c in dev_chunks[:5]
                ],
            }
            yield f"data: {json_mod.dumps(dev_event)}\n\n"
        if not ai_client.is_configured():
            err_event = {"type": "error", "content": "API key not configured."}
            yield f"data: {json_mod.dumps(err_event)}\n\n"
            return

        agent_context = ""
        if st.get("roblox_studio_mcp", False):
            agent_context = (
                "Roblox Studio integration is ACTIVE and CONNECTED. "
                "You MUST use the MCP tools to make ALL edits to the game. "
                "NEVER output script code in chat — write every script directly to Studio via MCP. "
                "Describe what you did in one plain sentence without showing code. "
                "BEFORE creating a new map/place, FIRST use MCP to list existing instances and check if one already exists. "
                "If a map already exists, do NOT create another. If no map exists, import from the Roblox Marketplace. "
                "When importing third-party assets or marketplace items, the user will be asked for permission — flag it with a warning."
            )

        combined_extra = _compose_extra_context(extra, doc_ctx, agent_context)
        chain_thought = req.chain_thought or advanced

        # Create subagent client if a different model is specified
        subagent_client = None
        if req.subagent_model and req.subagent_model != ai_client.model:
            subagent_client = make_client()
            subagent_client.model = req.subagent_model
        else:
            subagent_client = ai_client

        if req.agent_mode:
            active_tool_names = [cfg["name"] for tid, cfg in tools_mgr.tool_defs.items() if st.get(tid, False)]
            planner_plan = _build_agent_plan(ai_client, history, combined_extra, active_tool_names, req.max_subagents)
            session.agent_plan = [{"text": step, "done": False} for step in planner_plan["main_steps"]]
            store.save_session(session)
            plan_event = {
                "type": "agent_plan",
                "plan": planner_plan,
                "session_plan": session.agent_plan,
            }
            yield f"data: {json_mod.dumps(plan_event)}\n\n"

            subagent_notes = []
            if planner_plan["use_subagents"]:
                sub_list = planner_plan["subagents"][:min(req.max_subagents, 3)]
                for index, subagent in enumerate(sub_list, start=1):
                    status_event = {
                        "type": "agent_status",
                        "stage": "subagent_start",
                        "agent": subagent["name"],
                        "message": subagent["goal"],
                    }
                    yield f"data: {json_mod.dumps(status_event)}\n\n"
                    sub_prompt = (
                        f"You are subagent {index} in OpenBlox agent mode.\n"
                        f"Focus only on this goal: {subagent['goal']}\n"
                        "Return concise findings for the main agent. Do not address the user directly."
                    )
                    sub_history = list(history) + [{"role": "user", "content": sub_prompt}]
                    note = subagent_client.chat(
                        sub_history,
                        max_tokens=1200,
                        extra_context=combined_extra,
                        tools=openai_tools or None if subagent.get("use_tools") else None,
                        tool_handler=tool_handler if subagent.get("use_tools") else None,
                        advanced_thinking=chain_thought,
                    ) or ""
                    subagent_notes.append(f"{subagent['name']}:\n{note}")
                    session.agent_logs.append({
                        "agent": subagent["name"],
                        "stage": "subagent_done",
                        "message": note[:400],
                    })
                    done_event = {
                        "type": "agent_status",
                        "stage": "subagent_done",
                        "agent": subagent["name"],
                        "message": note[:400],
                    }
                    yield f"data: {json_mod.dumps(done_event)}\n\n"

            if planner_plan["use_subagents"] and subagent_notes:
                combined_extra = _compose_extra_context(
                    extra,
                    doc_ctx,
                    agent_context + "\n\nPlanner summary:\n"
                    + planner_plan["summary"]
                    + "\n\nSubagent notes:\n"
                    + "\n\n".join(subagent_notes),
                )
            else:
                combined_extra = _compose_extra_context(
                    extra,
                    doc_ctx,
                    agent_context + "\n\nPlanner summary:\n" + planner_plan["summary"],
                )

            main_event = {
                "type": "agent_status",
                "stage": "main_agent",
                "agent": "Main Agent",
                "message": "Executing the final plan.",
            }
            yield f"data: {json_mod.dumps(main_event)}\n\n"
            # Persist agent plan to logs
            session.agent_logs = [{"agent": "Planner", "stage": "plan", "message": planner_plan.get("summary", "")}]

        # Chain-of-thought reasoning enhancement
        if chain_thought and req.agent_mode:
            reasoning_prompt = (
                "Before responding, work through your reasoning step by step:\n"
                "1. What does the user want?\n"
                "2. What information do I have?\n"
                "3. What approach should I use?\n"
                "4. Execute the approach.\n"
                "5. Verify the result.\n\n"
                "Output your step-by-step reasoning, then provide the final answer."
            )
            # Use a local copy to avoid shadowing the closure variable
            ctx_history = [dict(m) for m in history]
            if ctx_history and ctx_history[-1]["role"] == "user":
                ctx_history[-1]["content"] += f"\n\n{reasoning_prompt}"
        else:
            ctx_history = history

        for event in ai_client.chat_stream(
            ctx_history, extra_context=combined_extra,
            tools=openai_tools or None, tool_handler=tool_handler,
            advanced_thinking=chain_thought, integration_name=integration_name,
        ):
            if event["type"] == "done":
                final_content = event["content"]
            yield f"data: {json_mod.dumps(event)}\n\n"

        session.add_message("assistant", final_content)
        # Auto-tick the first undone step after initial response
        if req.agent_mode and session.agent_plan:
            for step in session.agent_plan:
                if not step.get("done"):
                    step["done"] = True
                    session.agent_logs.append({"agent": "System", "stage": "step_done", "message": step["text"]})
                    break
            plan_update = {"type": "agent_plan_update", "session_plan": session.agent_plan}
            yield f"data: {json_mod.dumps(plan_update)}\n\n"
        store.save_session(session)

        # Multi-execution: keep executing until all steps done or max follow-ups reached
        if req.agent_mode and session.agent_plan:
            max_follow_ups = 1
            follow_count = 0
            while follow_count < max_follow_ups:
                undone = [s for s in session.agent_plan if not s.get("done")]
                if not undone:
                    break
                follow_count += 1
                # Emit working indicator
                work_event = {"type": "agent_working", "message": "Working..."}
                yield f"data: {json_mod.dumps(work_event)}\n\n"
                follow_prompt = "Continue with the next step. Keep it brief."
                # Auto-tick the next undone step before asking AI to continue
                for step in session.agent_plan:
                    if not step.get("done"):
                        step["done"] = True
                        session.agent_logs.append({"agent": "System", "stage": "step_done", "message": step["text"]})
                        break
                plan_update = {"type": "agent_plan_update", "session_plan": session.agent_plan}
                yield f"data: {json_mod.dumps(plan_update)}\n\n"
                session.add_message("user", follow_prompt)
                exec_history = [{"role": m.role, "content": m.content} for m in session.messages]
                for event in ai_client.chat_stream(
                    exec_history, extra_context=combined_extra,
                    tools=openai_tools or None, tool_handler=tool_handler,
                    advanced_thinking=chain_thought, integration_name=integration_name,
                ):
                    if event["type"] == "done":
                        final_content = event["content"]
                    yield f"data: {json_mod.dumps(event)}\n\n"
                session.add_message("assistant", final_content)
                store.save_session(session)

        sess_event = {
            "type": "session",
            "session": session.to_dict(),
        }
        yield f"data: {json_mod.dumps(sess_event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/compact")
async def compact_chat(req: CompactRequest):
    try:
        ai_client = make_client()
        session = None
        if req.session_id:
            session = _get_session(req.session_id)
        if not session:
            session = store.get_active()
        if session.model:
            ai_client.model = session.model

        note = _compact_session(session, ai_client)
        if note:
            # Add system message about compaction
            session.add_message("assistant", f"_Context compacted._")
            store.save_session(session)
            return {
                "ok": True,
                "note": note,
                "session": session.to_dict(),
                "context_pct": session.context_pct(),
            }
        return {"ok": False, "note": "Not enough messages to compact."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/websites")
async def list_websites():
    try:
        return {"websites": [{"name": w.name, "url": w.url, "enabled": w.enabled,
                              "extractor_type": w.extractor_type} for w in wm.websites]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.patch("/api/sessions/{session_id}/model")
async def set_session_model(session_id: str, req: RenameRequest):
    try:
        s = _get_session(session_id)
        if not s:
            raise HTTPException(404, "Session not found")
        s.model = req.title
        store.save_session(s)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/permission/pending")
async def permission_pending(session_id: str = ""):
    """Returns the current pending permission request, if any."""
    for req_id, info in list(_pending_permissions.items()):
        if info.get("decision") is None:
            return {
                "pending": True,
                "request_id": req_id,
                "tool_name": info.get("tool_name", ""),
                "is_asset": info.get("is_asset", False),
            }
    return {"pending": False}


@app.post("/api/permission/respond")
async def permission_respond(req: PermissionRespond):
    try:
        if req.request_id in _pending_permissions:
            _pending_permissions[req.request_id]["decision"] = req.decision
            evt = _pending_permissions[req.request_id].get("event")
            if evt:
                evt.set()
            if req.decision == "allow_command" and req.tool_name:
                _permission_cache[req.tool_name] = "always"
            elif req.decision == "allow_always":
                _permission_cache["*"] = "always"
            return {"ok": True}
        return JSONResponse(status_code=404, content={"error": "Request not found or expired."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/permission/clear")
async def permission_clear():
    _permission_cache.clear()
    return {"ok": True}


@app.patch("/api/sessions/{session_id}/perm")
async def toggle_session_perm(req: SessionPermToggle):
    try:
        s = _get_session(req.session_id)
        if not s:
            raise HTTPException(404, "Session not found")
        s.permissions_disabled = req.disabled
        store.save_session(s)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.patch("/api/sessions/{session_id}/plan")
async def update_session_plan(session_id: str, req: PlanUpdate):
    try:
        s = _get_session(session_id)
        if not s:
            raise HTTPException(404, "Session not found")
        if 0 <= req.index < len(s.agent_plan):
            s.agent_plan[req.index]["done"] = req.done
            store.save_session(s)
        return {"ok": True, "agent_plan": s.agent_plan}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


def _compact_session(session, ai_client) -> str:
    """Summarize old messages to free context space. Returns a note about what happened."""
    if len(session.messages) < 3:
        return ""
    # Keep the last user message + assistant response, summarize everything before
    summary_targets = session.messages[:-2]
    keep = session.messages[-2:]
    if not summary_targets:
        return ""

    text_to_summarize = "\n".join(f"{m.role}: {m.content[:500]}" for m in summary_targets)
    prompt = [
        {"role": "user", "content": f"Summarize this Roblox Studio development conversation concisely. Preserve all decisions, code patterns discussed, and the current state. Keep it under 400 tokens.\n\nConversation:\n{text_to_summarize}"}
    ]
    summary = ai_client.chat(prompt, max_tokens=500)
    if not summary or summary == "(no response)":
        return ""

    session.messages = [
        ChatMessage("assistant", f"[Context compacted — previous conversation summarized]\n{summary}")
    ] + keep
    store.save_session(session)
    return f"Context compacted. Previous conversation summarized. Current message count: {len(session.messages)}."


def _get_session_tools(req_session_id: str = None) -> dict:
    s = None
    if req_session_id:
        s = _get_session(req_session_id)
    if not s:
        s = store.get_active()
    return s.tools if s else {}


@app.get("/api/tools")
async def list_tools(session_id: str = None):
    try:
        st = _get_session_tools(session_id)
        return {"tools": tools_mgr.get_tools(st)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/tools/mcp-names")
async def list_mcp_tool_names():
    """Returns all MCP tool names across all integrations (for allowed commands dropdown)."""
    try:
        all_names = tools_mgr.get_all_mcp_tool_names()
        return {"tools": sorted(set(all_names))}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/tools/toggle")
async def toggle_tool(req: ToolToggle):
    try:
        result, new_tools = tools_mgr.toggle_tool(req.tool_id, _get_session_tools(req.session_id))
        s = None
        if req.session_id:
            s = _get_session(req.session_id)
        if not s:
            s = store.get_active()
        if s:
            s.tools = new_tools
            store.save_session(s)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

# Suppress noisy Windows proactor connection reset errors
import logging
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8520))
    print(f"Server running at http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
