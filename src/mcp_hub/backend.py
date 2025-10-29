import os
import re
import yaml
import json
from typing import List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack

from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

from llm_adapter import LLMAdapter

load_dotenv()

# -------------------
# Load model configs
# -------------------

project_root = Path(os.getenv("PROJECT_ROOT")).resolve()
MODEL_CONFIG_PATH = project_root / "models_config.yaml"
MCP_CONFIG_PATH = project_root / "mcp_servers_config.yaml"

with open(MODEL_CONFIG_PATH, "r") as f:
    supported_models = yaml.safe_load(f)

# -----------------------------
# MCP Client Wrapper
# -----------------------------
class MCPClient:
    """
    A multi-server MCP client that manages concurrent MCP connections,
    lists their tools, and allows invoking them dynamically.
    """

    def __init__(self):
        self.exit_stack = AsyncExitStack()
        self.sessions: Dict[str, ClientSession] = {}
        self.active_servers: Dict[str, bool] = {}

    # -----------------------------
    # Connection Management
    # -----------------------------
    async def connect_to_server(self, name: str, command: str, args: list, cwd: str = None):
        """
        Connects to an MCP server via stdio and initializes a session.
        """
        server_params = StdioServerParameters(command=command, args=args, cwd=cwd)
        read_stream, write_stream = await self.exit_stack.enter_async_context(stdio_client(server_params))
        session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()

        self.sessions[name] = session
        self.active_servers[name] = True
        print(f"✅ Connected to MCP server: {name}")

    async def cleanup(self):
        """Gracefully closes all active sessions."""
        await self.exit_stack.aclose()
        print("Cleaned up all MCP server sessions.")

    # -----------------------------
    # Tool Discovery
    # -----------------------------
    async def list_all_tools(self) -> List[Dict[str, str]]:
        """
        Lists all available tools from connected MCP servers.
        Returns a list of dicts with server name, tool name, and description.
        """
        tools = []
        for name, session in self.sessions.items():
            if not self.active_servers.get(name, False):
                continue
            response = await session.list_tools()
            for tool in response.tools:
                tools.append({
                    "server": name,
                    "tool_name": tool.name,
                    "description": tool.description
                })
        return tools

    # -----------------------------
    # Query Processing
    # -----------------------------
    async def process_query(self, chat_client, model_id: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Handles an LLM query and automatically determines if any connected tool should be invoked.
        """
        # Aggregate tools from all active sessions
        available_tools = []
        for name, session in self.sessions.items():
            if not self.active_servers.get(name, False):
                continue
            response = await session.list_tools()
            for tool in response.tools:
                available_tools.append({
                    "type": "function",
                    "function": {
                        "name": f"{name}:{tool.name}",  # Namespaced to avoid collisions
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })

        # First LLM reasoning call
        completion = chat_client.chat.completions.create(
            model=model_id,
            messages=[
                *messages,
                {
                    "role": "system",
                    "content": (
                        "Before answering, think step by step and explain: "
                        "Do you need to call a tool? Which one and why? "
                        "Then either call the tool or answer directly."
                    ),
                },
            ],
            tools=available_tools,
            tool_choice="auto",
        )

        msg = completion.choices[0].message

        # Case 1: No tool call
        if msg.content and not msg.tool_calls:
            return {"text": msg.content, "tool_used": None}

        # Case 2: Tool invoked
        if msg.tool_calls:
            tool_call = msg.tool_calls[0]
            full_tool_name = tool_call.function.name
            server_name, tool_name = full_tool_name.split(":", 1)
            tool_args = json.loads(tool_call.function.arguments)

            print(f"[DEBUG] Tool called → Server: {server_name}, Tool: {tool_name}, Args: {tool_args}")

            session = self.sessions.get(server_name)
            if not session:
                return {"text": f"Error: server '{server_name}' not connected.", "tool_used": None}

            tool_result = await session.call_tool(tool_name, tool_args)
            result = (
                tool_result.structuredContent["result"]
                if hasattr(tool_result, "structuredContent") and "result" in tool_result.structuredContent
                else tool_result
            )

            # Second pass for natural response
            final_prompt = f"""
            The user asked: "{messages[-1]['content']}"
            The tool returned: "{result}"
            Please summarize and respond naturally.
            """

            final_completion = chat_client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": final_prompt}],
            )
            final_answer = final_completion.choices[0].message.content

            return {"text": final_answer, "tool_used": f"{server_name}:{tool_name}"}

        return {"text": "No response from model.", "tool_used": None}



# -----------------------------
# FastAPI App
# -----------------------------
app = FastAPI(title="Recallix Backend")

mcp_client = MCPClient()

@app.on_event("startup")
async def startup_event():
    # Load YAML config file
    if not os.path.exists(MCP_CONFIG_PATH):
        print(f"No config.yaml found at {MCP_CONFIG_PATH}")
        return

    with open(MCP_CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    if config is None:
        print("Config file is empty or invalid YAML")
        return

    servers = config.get("servers", [])
    print(f"Starting {len(servers)} MCP servers...")

    # Connect to each MCP server in config
    for srv in servers:
        print(srv)
        try:
            await mcp_client.connect_to_server(
                name=srv["name"],
                command=srv["command"],
                args=srv["args"],
                cwd=srv["cwd"]
            )
            mcp_client.active_servers[srv["name"]] = {
                    "status": "running",
                    "active": True,
                    "cwd": srv["cwd"]
                }
            print(f"✅ Connected to {srv['name']}")
        except Exception as e:
            print(f"❌ Failed to start {srv['name']}: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down all MCP servers...")
    await mcp_client.cleanup()

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    provider: str
    model: str

@app.get("/servers")
async def get_active_servers():
    """Return currently active MCP servers"""
    try:
        return JSONResponse({"servers": mcp_client.active_servers})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- Utility: Remove reasoning traces ---
def remove_reasoning_thoughts(text: str) -> str:
    """Remove reasoning traces (internal thoughts) from model output across various model families."""
    if not isinstance(text, str):
        return text

    patterns = [
        r"<think>.*?</think>",                   # DeepSeek R1, generic XML-style tag
        r"<thinking>.*?</thinking>",             # Anthropic Claude Opus
        r"\[Reasoning\].*?\[/Reasoning\]",       # Qwen2.5 Reasoner format
        r"\[Thoughts?\].*?\[/Thoughts?\]",       # Optional Thoughts tag variant
        r"(?i)\*\*Thought:?[^*\n]*",             # Markdown bold 'Thought:' prefix
        r"(?i)\*Reasoning:?[^*\n]*",             # Markdown italic 'Reasoning:' prefix
        r"(?i)(?:let['’]s reason step by step:).*",  # OpenAI o1 style reasoning intro
        r"(?i)(?:let['’]s think step by step:).*",   # Alternative phrase variant
        r"(?i)(?:thinking process:).*",              # Some open-source models
    ]

    cleaned_text = text
    for pattern in patterns:
        cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.DOTALL)

    # Clean extra whitespace/newlines
    cleaned_text = re.sub(r"\n{2,}", "\n\n", cleaned_text).strip()

    return cleaned_text



@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        print("request received: " + req.provider, req.model)
        llm = LLMAdapter(
            provider=req.provider,
            model=req.model
        )
        model_id = supported_models[req.provider][req.model]["model_id"]
        
        response = await mcp_client.process_query(llm.client, model_id, req.messages)

        # Extract reasoning if the model returns structured fields
        message = response.get("text", "")
        reasoning = None

        # Check if the LLM client provides structured fields
        if isinstance(message, dict):
            reasoning = message.get("reasoning_content")
            message = message.get("content", "")

        # Or if it’s a list (Anthropic / OpenAI o1 style)
        elif isinstance(message, list):
            reasoning_blocks = [
                block.get("text", "")
                for block in message
                if block.get("type") in ("reasoning", "thinking", "system")
            ]
            reasoning = "\n".join(reasoning_blocks)
            message = next(
                (block.get("text") for block in message if block.get("type") == "output_text"),
                message,
            )
        
        # Not need as of now
        # # Decide whether to include reasoning based on env var or config
        # SHOW_REASONING = os.getenv("SHOW_REASONING", "false").lower() == "true"

        # if SHOW_REASONING and reasoning:
        #     final_content = f"<think>{reasoning}</think>\n\n{message}"
        # else:
        #     # Strip reasoning traces if user doesn't want to see them
        #     final_content = remove_reasoning_thoughts(message)

        final_content = remove_reasoning_thoughts(message)

        return JSONResponse(content={
            "choices": [
                {"message": {"role": "assistant", "content": final_content}}
            ],
            "tool_used": response.get("tool_used", None)
        })

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    

@app.post("/upload-config")
async def upload_config(file: UploadFile = File(...)):
    """Accepts YAML config and starts all MCP servers."""
    try:
        # Save the uploaded file
        contents = await file.read()
        with open(MCP_CONFIG_PATH, "wb") as f:
            f.write(contents)
        
        # Load the yaml config
        config_data = yaml.safe_load(contents)
        servers = config_data.get("servers", [])
        active_servers = {}

        print(f"Starting {len(servers)} MCP servers...")

        # Connect to each MCP server in config
        for srv in servers:
            try:
                await mcp_client.connect_to_server(
                    name=srv["name"],
                    command=srv["command"],
                    args=srv["args"],
                    cwd=srv["cwd"]
                )
                active_servers[srv["name"]] = {
                    "status": "running",
                    "active": True,
                    "cwd": srv["cwd"]
                }
                print(f"✅ Connected to {srv['name']}")
            except Exception as e:
                active_servers[srv["name"]] = {
                    "status": f"error: {e}",
                    "active": False
                }
                print(f"❌ Failed to start {srv['name']}: {e}")


        return JSONResponse({"servers": active_servers})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    