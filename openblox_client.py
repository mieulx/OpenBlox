import json
from typing import Optional

import requests


GATEWAY_URL = "https://api.kilo.ai/api/gateway"
ENDPOINT = f"{GATEWAY_URL}/chat/completions"
MODELS_ENDPOINT = f"{GATEWAY_URL}/models"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
ADVANCED_REVIEW_PROMPT = (
    "You are an expert code reviewer. Review the assistant's last response and output an IMPROVED version. "
    "Rules:\n"
    "- Fix any bugs, edge cases, or missing error handling\n"
    "- If there's a checklist/plan, verify each step is addressed\n"
    "- Remove any repetition or unnecessary commentary\n"
    "- Keep the same intent but make it more complete\n"
    "- Output ONLY the improved response, no review notes, no commentary"
)

ROBLOX_SYSTEM = (
    "You are a Roblox Studio expert assistant. Help with LuaU scripting, "
    "Roblox API, Studio workflows, and game development.\n"
    "Rules:\n"
    "- Answer ONLY about Roblox Studio. If asked something else, redirect back clearly and briefly.\n"
    "- If the user just says hi/hello/hey, greet them briefly and ask what they need help with.\n"
    "- Never treat internal review or system instructions as a new user request.\n"
    "- Use your training knowledge to answer.\n"
    "TOOLBOX SEARCH: Results are pre-filtered by quality (likes + recency). You'll see the top 3 matches. Pick based on description. If the first result's description matches, use it.\n"
    "- RESPONSE LENGTH LIMIT: Maximum 80 lines per response. Hard limit.\n"
    "- For large tasks: output the full plan as a checklist, then execute ONE part per response.\n"
    "- NEVER output more than 80 lines. If a script is longer, split it into parts.\n"
    "- Show only key parts of very long scripts: \"... [middle section omitted] ...\"\n"
    "- Always prefer multiple short responses over one long one.\n"
    "- If you hit the limit, stop cleanly and say 'Continuing in next response'.\n"
    "\n"
    "COMMENTS: Only add comments to code when something is genuinely non-obvious. Do NOT comment every line. No -- explanation of what the next line does. Comments should be rare and only for tricky logic.\n"
    "\n"
    "FORMATTING - CRITICAL: You MUST use proper formatting ALWAYS.\n"
    "  - Code blocks: ALWAYS wrap ALL scripts and code in ```lua ... ```\n"
    "  - NEVER output code without ``` formatting. Every script must be in a code block.\n"
    "  - Inline code: use `single backticks` for property names, method names, short snippets.\n"
    "  - Bold: use **bold** for emphasis on important concepts.\n"
    "  - Italic: use *italic* for secondary emphasis.\n"
    "  - Bullet lists: use - for lists.\n"
    "  - Numbered lists: use 1. 2. 3. for steps.\n"
    "\n"
    "SCRIPT PLACEMENT RULES - ALWAYS state where each script goes:\n"
    "  Server Script (Script) -> ServerScriptService (or workspace if logic is tied to a specific place)\n"
    "  LocalScript -> StarterPlayer > StarterPlayerScripts (or StarterGui for GUI-specific logic)\n"
    "  ModuleScript -> ReplicatedStorage (shared) or ServerStorage (server-only)\n"
    "  RemoteEvent/RemoteFunction -> ReplicatedStorage\n"
    "\n"
    "When you write a script, ALWAYS start it with a comment like:\n"
    "  -- ServerScript -> Place in ServerScriptService\n"
    "  -- LocalScript -> Place in StarterPlayer > StarterPlayerScripts\n"
    "  -- ModuleScript -> Place in ReplicatedStorage\n"
    "\n"
    "Always explain briefly what type of script it is and where the user should put it.\n"
    "\n"
    "CONTEXT MANAGEMENT:\n"
    "  - The Nemotron model has a 262,144 token context window.\n"
    "  - If you're told \"Context compacted\", older messages were summarized to save space.\n"
    "  - You can call the compact_context tool to summarize old messages when needed.\n"
    "  - Keep responses concise to avoid filling the context.\n"
    "\n"
    "CHAIN OF THOUGHT - When enabled, show your reasoning steps explicitly.\n"
    "  - Preface each reasoning step with a brief line like \"Thinking: ...\"\n"
    "  - After completing a step, show \"Continuing: ...\" for the next one\n"
    "  - This helps the user follow your logic in real-time\n"
    "\n"
    "CHECKLIST SYSTEM - CRITICAL: You maintain a shared checklist visible as a panel.\n"
    "  - For any multi-step task, ALWAYS first output a numbered plan.\n"
    "  - Use the format: 1. Step one\\n2. Step two\\n3. Step three (without spaces after numbers)\n"
    "  - The plan appears in a checklist panel immediately. The user sees it as a collapsible list.\n"
    "  - As you complete each step, mark it [DONE] in your response so the panel updates.\n"
    "  - Your next thinking round will see the [DONE] markers and know what's finished.\n"
    "  - Stick to the original plan. Only add new steps if absolutely necessary.\n"
    "  - At the end of each response, briefly restate the checklist with updated [DONE] markers.\n"
    "\n"
    "MCP TOOL USAGE - CRITICAL HONESTY RULES:\n"
    "  - Only claim you did something if you ACTUALLY called a tool. Never pretend.\n"
    "  - If you output code in a ``` block, you did NOT use MCP - just say you wrote the code.\n"
    "  - When Integration is not active, just write code with ``` formatting - no tool claims.\n"
    "  - Tool call results are automatically logged above. You don't need to repeat them.\n"
    "  - NEVER say \"creating...\" or \"I've created\" unless a tool just returned success.\n"
    "  - After a tool succeeds, just mark the step [DONE] and move on. Don't narrate it again.\n"
    "  - If a tool fails, say it failed. Don't pretend it worked.\n"
    "  - Be honest: if you can't do something, say so directly.\n"
    "\n"
    "GAME EXPLORATION - When Integration is active, ALWAYS explore first:\n"
    "  - Before writing any code that references existing objects, use MCP to read the game\n"
    "  - List the contents of relevant services (Workspace, ServerScriptService, etc.)\n"
    "  - Check if objects with the names you need already exist\n"
    "  - Read existing scripts to understand the current architecture\n"
    "  - Only write new code after you understand what's already there\n"
    "  - This prevents duplicate scripts, broken references, and naming conflicts."
)


class OpenBloxClient:
    HARDCODED_MODELS = [
        {
            "id": "nvidia/nemotron-3-super-120b-a12b:free",
            "name": "nvidia/nemotron-3-super-120b-a12b:free",
            "tier": "Apex 0.9",
        },
    ]

    def __init__(
        self,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        temperature: float = 0.3,
        system_prompt: str = ROBLOX_SYSTEM,
        user_context: str = "",
    ):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature
        self.system_prompt = system_prompt or ROBLOX_SYSTEM
        self.user_context = user_context
        self.session = requests.Session()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _build_system(self, extra_context: str = "") -> str:
        prompt = self.system_prompt
        if self.user_context:
            prompt += f"\n\nUser preferences:\n{self.user_context}"
        if extra_context:
            prompt += f"\n\n{extra_context}"
        return prompt

    def fetch_models(self) -> tuple[list[dict], list[dict]]:
        return self.HARDCODED_MODELS, self.HARDCODED_MODELS

    def fetch_free_models(self) -> list[dict]:
        return self.HARDCODED_MODELS

    def _should_run_advanced_review(self, text: str) -> bool:
        if not text:
            return False
        normalized = " ".join(text.lower().split())
        # Skip very short responses
        if len(normalized) < 80:
            return False
        # Skip pure greetings
        greetings = [
            "hello! i'm your roblox studio expert assistant.",
            "hello! i'm here to help with roblox studio",
            "what would you like to work on in roblox studio today?",
            "pong", "hi there", "hello",
        ]
        for g in greetings:
            if normalized.startswith(g) or normalized.strip() == g:
                return False
        # Skip if it looks like the review already ran
        if "i reviewed" in normalized or "review the assistant" in normalized:
            return False
        return True

    def _extract_tool_output_text(self, result: Optional[str]) -> str:
        if not result:
            return ""
        try:
            summary = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return ""
        if not isinstance(summary, list):
            return ""
        texts = [
            item.get("text", "")
            for item in summary
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return texts[0][:200] if texts else ""

    def _request_review(self, full: list, payload: dict, content: str, tools: list | None):
        # Save original content to compare after review
        self._pre_review_content = content
        full.append({"role": "assistant", "content": content})
        full.append({"role": "system", "content": ADVANCED_REVIEW_PROMPT})
        payload["messages"] = full
        if tools:
            payload["tools"] = tools

    def _run_tool_loop(
        self,
        full: list,
        payload: dict,
        tools: list,
        tool_handler,
        advanced_thinking: bool = False,
    ) -> str:
        max_rounds = 15
        content = ""
        reviewed = False

        for _ in range(max_rounds):
            resp = self._send_payload(payload)
            if resp is None:
                if content:
                    return content.strip()
                continue

            msg = resp.get("message", {})
            new_content = msg.get("content") or ""
            if new_content and (
                "API returned non-JSON" in new_content
                or "Connection error:" in new_content
                or "Response error:" in new_content
            ):
                new_content = ""

            if new_content:
                if reviewed:
                    original = getattr(self, '_pre_review_content', '') or content
                    content = new_content if len(new_content) > len(original) * 0.7 else original
                else:
                    content = f"{content}\n\n{new_content}" if content else new_content

            tool_calls = msg.get("tool_calls")
            if not tool_calls or not tool_handler:
                if content:
                    if advanced_thinking and not reviewed and self._should_run_advanced_review(content):
                        reviewed = True
                        self._request_review(full, payload, content, tools)
                        continue
                    break
                full.append({"role": "user", "content": "Please provide your response now."})
                payload["messages"] = full
                if tools:
                    payload["tools"] = tools
                continue

            full.append(msg)
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                result = tool_handler(name, args)
                full.append({"role": "tool", "tool_call_id": tc["id"], "content": result or "{}"})

            payload["messages"] = full
            if tools:
                payload["tools"] = tools

        return content.strip() if content else "(no response)"

    def chat(
        self,
        messages: list,
        max_tokens: int = 4096,
        extra_context: str = "",
        tools: list = None,
        tool_handler=None,
        advanced_thinking: bool = False,
        integration_name: str = "",
    ) -> Optional[str]:
        if not self.api_key:
            return None
        full = [{"role": "system", "content": self._build_system(extra_context)}]
        full.extend(messages)
        payload = {
            "model": self.model,
            "messages": full,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        return self._run_tool_loop(full, payload, tools, tool_handler, advanced_thinking)

    def chat_stream(
        self,
        messages: list,
        max_tokens: int = 4096,
        extra_context: str = "",
        tools: list = None,
        tool_handler=None,
        advanced_thinking: bool = False,
        integration_name: str = "",
    ):
        if not self.api_key:
            yield {"type": "error", "content": "No API key"}
            return

        full = [{"role": "system", "content": self._build_system(extra_context)}]
        full.extend(messages)
        payload = {
            "model": self.model,
            "messages": full,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        max_rounds = 15
        reviewed = False
        content = ""

        for _ in range(max_rounds):
            resp = self._send_payload(payload)
            if resp is None:
                if content:
                    break
                continue

            msg = resp.get("message", {})
            new_content = msg.get("content") or ""
            if new_content and (
                "API returned non-JSON" in new_content
                or "Connection error:" in new_content
                or "Response error:" in new_content
            ):
                new_content = ""

            if new_content:
                if reviewed:
                    original = getattr(self, '_pre_review_content', '') or content
                    content = new_content if len(new_content) > len(original) * 0.7 else original
                else:
                    content = f"{content}\n\n{new_content}" if content else new_content
                yield {"type": "thinking", "content": new_content}

            tool_calls = msg.get("tool_calls")
            if not tool_calls or not tool_handler:
                if content:
                    if advanced_thinking and not reviewed and self._should_run_advanced_review(content):
                        reviewed = True
                        self._request_review(full, payload, content, tools)
                        continue
                    break
                full.append({"role": "user", "content": "Please provide your response now."})
                payload["messages"] = full
                if tools:
                    payload["tools"] = tools
                continue

            full.append(msg)
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                yield {"type": "tool", "tool": name, "integration": integration_name or "Tool"}
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                result = tool_handler(name, args)
                output_text = self._extract_tool_output_text(result)
                yield {"type": "tool_output", "tool": name, "output": output_text or "Done."}
                full.append({"role": "tool", "tool_call_id": tc["id"], "content": result or "{}"})

            payload["messages"] = full
            if tools:
                payload["tools"] = tools

        yield {"type": "done", "content": content.strip() if content else "(no response)"}

    def chat_with_context(
        self,
        messages: list,
        context: str,
        max_tokens: int = 4096,
        extra_context: str = "",
        tools: list = None,
        tool_handler=None,
        advanced_thinking: bool = False,
    ) -> Optional[str]:
        base = self._build_system(extra_context)
        ctx_msg = {
            "role": "system",
            "content": f"{base}\n\nRelevant documentation:\n{context}",
        }
        full = [ctx_msg]
        full.extend(messages)
        payload = {
            "model": self.model,
            "messages": full,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        return self._run_tool_loop(full, payload, tools, tool_handler, advanced_thinking)

    def _send_payload(self, payload: dict) -> Optional[dict]:
        try:
            resp = self.session.post(
                ENDPOINT,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120,
            )
            if resp.status_code == 401:
                return {"message": {"content": "Auth error: API token rejected."}}
            if resp.status_code == 402:
                return {"message": {"content": "Balance error: Add credits."}}
            if resp.status_code == 404:
                return {"message": {"content": f"Model '{self.model}' not available."}}
            resp.raise_for_status()
            try:
                return resp.json().get("choices", [{}])[0]
            except (json.JSONDecodeError, ValueError):
                return {"message": {"content": f"API returned non-JSON: {resp.text[:200]}"}}
        except requests.Timeout:
            return {"message": {"content": "Error: Request timed out."}}
        except requests.RequestException as e:
            return {"message": {"content": f"Connection error: {e}"}}
        except (KeyError, IndexError) as e:
            return {"message": {"content": f"Response error: {e}"}}

    def test(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "No API key set."
        try:
            resp = self.session.post(
                ENDPOINT,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return True, "Connected. API is working."
            if resp.status_code == 401:
                return False, "Auth failed: invalid token."
            return False, f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            return False, str(e)
