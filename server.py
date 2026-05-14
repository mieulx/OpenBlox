import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
import json as json_mod
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


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    dev_mode: bool = False
    edit_index: Optional[int] = None


class ConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    user_context: Optional[str] = None
    max_chunks: Optional[int] = None
    chunk_size: Optional[int] = None


class RenameRequest(BaseModel):
    title: str


class EditMessageRequest(BaseModel):
    message: str
    edit_index: int


class ToolToggle(BaseModel):
    tool_id: str
    session_id: Optional[str] = None


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
    if req.dev_mode:
        dev_chunks = dev_proc.fetch_for_query(req.message or "")

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

    if req.dev_mode and dev_chunks:
        doc_ctx = dev_proc.build_context(dev_chunks)
        response = ai_client.chat_with_context(
            history, doc_ctx, extra_context=extra,
            tools=openai_tools or None, tool_handler=tool_handler,
            advanced_thinking=advanced)
    else:
        response = ai_client.chat(
            history, extra_context=extra,
            tools=openai_tools or None, tool_handler=tool_handler,
            advanced_thinking=advanced)

    if response is None:
        response = "No response from API."

    session.add_message("assistant", response)
    store.save_session(session)

    return {
        "response": response,
        "session": session.to_dict(),
        "dev_chunks": [{"heading": c.heading_path or c.source_url, "text": c.text[:500]}
                       for c in dev_chunks[:5]] if req.dev_mode else [],
    }


def _get_integration_name(st: dict) -> str:
    for tid, cfg in tools_mgr.tool_defs.items():
        if st.get(tid, False) and cfg.get("command"):
            return cfg.get("name", "Tool")
    return ""


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
    def _s_handler(name, args):
        if name == "compact_context":
            return _compact_session(session, ai_client) or "Context compacted."
        return tools_mgr.handle_tool_call(name, args, st) if openai_tools else None
    tool_handler = _s_handler if (openai_tools or st.get("context_compactor", True)) else None
    advanced = st.get("advanced_thinking", False)
    integration_name = _get_integration_name(st)

    dev_chunks = []
    if req.dev_mode:
        dev_chunks = dev_proc.fetch_for_query(req.message or "")

    def event_stream():
        final_content = "(no response)"
        if req.dev_mode and dev_chunks:
            yield f"data: {json_mod.dumps({'type': 'dev', 'chunks': [{'heading': c.heading_path or c.source_url, 'text': c.text[:500]} for c in dev_chunks[:5]]})}\n\n"
        if not ai_client.is_configured():
            yield f"data: {json_mod.dumps({'type': 'error', 'content': 'API key not configured.'})}\n\n"
            return
        for event in ai_client.chat_stream(
            history, extra_context=extra,
            tools=openai_tools or None, tool_handler=tool_handler,
            advanced_thinking=advanced, integration_name=integration_name,
        ):
            if event["type"] == "done":
                final_content = event["content"]
            yield f"data: {json_mod.dumps(event)}\n\n"
        
        session.add_message("assistant", final_content)
        store.save_session(session)
        yield f"data: {json_mod.dumps({'type': 'session', 'session': session.to_dict()})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
