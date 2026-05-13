import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import uvicorn

from website_manager import WebsiteManager
from extractor import ContentExtractor
from kilo_client import KiloClient
from chat_store import ChatStore, ChatSession
from processor import DevProcessor
from tools_manager import ToolsManager


app = FastAPI(title="Kilo Roblox Studio Helper")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8520", "http://127.0.0.1:8520"], allow_methods=["*"], allow_headers=["*"])

wm = WebsiteManager()
extractor = ContentExtractor(chunk_size=wm.search_config["chunk_size"])
store = ChatStore()
dev_proc = DevProcessor(wm, extractor)

kilo_config = wm.kilo_config
user_context = kilo_config.get("user_context", "")
kilo = KiloClient(
    api_key=kilo_config.get("api_key", ""),
    model=kilo_config.get("model", "nvidia/nemotron-3-super-120b-a12b:free"),
    temperature=kilo_config.get("temperature", 0.3),
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


def make_kilo():
    ctx = wm.kilo_config.get("user_context", "")
    return KiloClient(
        api_key=wm.kilo_config.get("api_key", ""),
        model=wm.kilo_config.get("model", "nvidia/nemotron-3-super-120b-a12b:free"),
        temperature=wm.kilo_config.get("temperature", 0.3),
        user_context=ctx,
    )


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/status")
async def status():
    try:
        return {
            "configured": make_kilo().is_configured(),
            "model": make_kilo().model,
            "sessions": len(store.sessions),
            "websites": len(wm.websites),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/config")
async def get_config():
    try:
        return {
            "api_key": bool(wm.kilo_config.get("api_key", "")),
            "model": wm.kilo_config.get("model", "nvidia/nemotron-3-super-120b-a12b:free"),
            "temperature": wm.kilo_config.get("temperature", 0.3),
            "user_context": wm.kilo_config.get("user_context", ""),
            "max_chunks": wm.search_config.get("max_chunks", 8),
            "chunk_size": wm.search_config.get("chunk_size", 1500),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/config")
async def save_config(cfg: ConfigUpdate):
    try:
        if cfg.api_key is not None:
            wm.kilo_config["api_key"] = cfg.api_key
        if cfg.model is not None:
            wm.kilo_config["model"] = cfg.model
        if cfg.temperature is not None:
            wm.kilo_config["temperature"] = cfg.temperature
        if cfg.user_context is not None:
            wm.kilo_config["user_context"] = cfg.user_context
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
        all_m, free_m = make_kilo().fetch_models()
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
        lines = [f"Kilo Roblox Studio Helper — {s.title}", "=" * 50, ""]
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
    kilo_instance = make_kilo()
    if not kilo_instance.is_configured():
        return JSONResponse(status_code=400, content={"error": "API key not configured."})

    session = None
    if req.session_id:
        for s in store.sessions:
            if s.id == req.session_id:
                session = s
                break
    if not session:
        session = store.get_active()

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
    openai_tools = tools_mgr.get_openai_tools(st)
    tool_handler = (lambda n, a: tools_mgr.handle_tool_call(n, a, st)) if openai_tools else None

    if req.dev_mode and dev_chunks:
        doc_ctx = dev_proc.build_context(dev_chunks)
        response = kilo_instance.chat_with_context(
            history, doc_ctx, extra_context=extra,
            tools=openai_tools or None, tool_handler=tool_handler)
    else:
        response = kilo_instance.chat(
            history, extra_context=extra,
            tools=openai_tools or None, tool_handler=tool_handler)

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


@app.get("/api/websites")
async def list_websites():
    try:
        return {"websites": [{"name": w.name, "url": w.url, "enabled": w.enabled,
                              "extractor_type": w.extractor_type} for w in wm.websites]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8520))
    print(f"Server running at http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
