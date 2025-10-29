import os
import time
import yaml
import requests
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

CHATBOT_NAME = "MCPHub"
VERSION = "v0.4" 

st.set_page_config(page_title=f"{CHATBOT_NAME}", page_icon="🤖")

load_dotenv()

project_root = Path(os.getenv("PROJECT_ROOT")).resolve()
MODEL_CONFIG_PATH = project_root / "models_config.yaml"
MCP_CONFIG_PATH = project_root / "mcp_servers_config.yaml"

# --- Load model configs ---
with open(MODEL_CONFIG_PATH, "r") as f:
    MODELS_CONFIG = yaml.safe_load(f)

# --- Header ---
st.markdown(
    f"""
    <div style="display: flex; flex-direction: column; align-items: flex-start; margin-bottom: 15px;">
        <h2 style="margin: 0; padding: 0;">{CHATBOT_NAME} 🤖</h2>
        <small style="color: gray;">Version: {VERSION}</small>
    </div>
    """,
    unsafe_allow_html=True
)

st.write("Ready to begin? Load your MCP config and bring your AI tools online.")

# --- Sidebar: Model selection ---
st.sidebar.header("Model Configuration")

provider = st.sidebar.selectbox(
    "Select Provider", options=list(MODELS_CONFIG.keys()), index=0
)
model = st.sidebar.selectbox(
    "Select Model", options=list(MODELS_CONFIG[provider].keys()), index=0
)
st.sidebar.success(f"Using {provider} → {model}")

# Reset chat on model change
if "selected_model" not in st.session_state:
    st.session_state.selected_model = model
if model != st.session_state.selected_model:
    st.session_state.messages = []
    st.session_state.selected_model = model
    st.sidebar.info("🔄 Chat history cleared — switched to new model.")

st.caption(f"Currently using: **{provider} → {model}**")
st.sidebar.divider()

# --- API Endpoints ---
API_URL = "http://127.0.0.1:8000/chat"
UPLOAD_URL = "http://127.0.0.1:8000/upload-config"
# TOGGLE_URL = "http://127.0.0.1:8000/toggle-active"  # 👈 NEW: soft toggle endpoint
SERVERS_URL = "http://127.0.0.1:8000/servers"

# --- Fetch existing servers on load ---
# Fetch existing servers from backend (on first load)
if "servers" not in st.session_state:
    try:
        res = requests.get(SERVERS_URL)
        res.raise_for_status()
        data = res.json()
        st.session_state.servers = data.get("servers", {})
    except Exception as e:
        st.session_state.servers = {}
        st.sidebar.warning(f"⚠️ Could not load active servers: {e}")

# --- Session state initialization ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "servers" not in st.session_state:
    st.session_state.servers = {}

# --- Sidebar: MCP Orchestration ---
st.sidebar.header("MCP Server Orchestration")

config_input_method = st.sidebar.radio(
    "Choose how to provide MCP configs:",
    ["📁 Upload YAML File", "✏️ Paste YAML"],
    index=0
)

uploaded_config = None

# Option 1: File upload
if config_input_method == "📁 Upload YAML File":
    uploaded_file = st.sidebar.file_uploader("Upload MCP Config (.yaml)", type=["yaml", "yml"])
    if uploaded_file is not None:
        uploaded_config = uploaded_file.getvalue().decode("utf-8")

# Option 2: Paste config
else:
    pasted_yaml = st.sidebar.text_area(
        "Paste MCP configuration(s):",
        placeholder="servers:\n  - name: recallix_math\n    command: python math_server.py\n    cwd: ./math_tools \nThis will overwrite any previously loaded config.",
        height=200
    )
    if pasted_yaml.strip():
        uploaded_config = pasted_yaml

# --- Start servers ---
if uploaded_config:
    if st.sidebar.button("🚀 Start MCP Servers"):
        with st.spinner("Starting servers..."):
            try:
                res = requests.post(
                    UPLOAD_URL,
                    files={"file": (MCP_CONFIG_PATH, uploaded_config, "application/x-yaml")}
                )
                res.raise_for_status()
                data = res.json()
                st.session_state.servers = data.get("servers", {})
                st.sidebar.success("✅ Servers started successfully!")
            except Exception as e:
                st.sidebar.error(f"Failed to start servers: {e}")



# --- Active server list ---
st.set_page_config(layout="wide")

# Mock initial state
if "servers" not in st.session_state:
    st.session_state.servers = {
        "Server-A": {"status": "running", "active": True},
        "Server-B": {"status": "idle", "active": False},
    }

st.sidebar.subheader("Active MCP Servers")

for name, details in st.session_state.servers.items():
    active = details.get("active", True)

    col1, col2 = st.sidebar.columns([5, 1], gap="small")
    with col1:
        st.markdown(f"<span style='color:white;font-weight:500;'>{name}</span>", unsafe_allow_html=True)

    with col2:
        btn_label = "🟢" if active else "⚪"

        # Button click toggles active state
        if st.button(btn_label, key=f"toggle_{name}"):
            new_state = not active
            st.session_state.servers[name]["active"] = new_state  # Update immediately
            # Need to fix backend to support this
            # try:
            #     # Call backend to persist state
            #     res = requests.patch(f"{TOGGLE_URL}/{name}", json={"active": new_state})
            #     res.raise_for_status()
            # except Exception as e:
            #     st.sidebar.error(f"Failed to update {name}: {e}")
            # st.rerun()  # Trigger re-render with new state

st.sidebar.divider()



# --- Chat history display ---

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- Chat input ---
if prompt := st.chat_input("Type your message here..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    assistant_msg = st.empty()
    ai_reply = ""

    try:
        # Send full conversation + active servers
        active_servers = [name for name, s in st.session_state.servers.items() if s.get("active", True)]
        response = requests.post(
            API_URL,
            json={
                "messages": st.session_state.messages,
                "provider": provider,
                "model": model,
                "active_servers": active_servers, 
            },
            timeout=60,
        )

        response.raise_for_status()
        data = response.json()

        # --- Extract AI response ---
        choices = data.get("choices", [])
        tool_used = data.get("tool_used")

        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if isinstance(content, str):
                ai_reply = content
            elif isinstance(content, list):
                ai_reply = next(
                    (item.get("text") for item in content if item.get("type") == "text" and item.get("text")),
                    None
                ) or "Error: No text found in structured response."
            else:
                ai_reply = f"Error: Unsupported content format {type(content)}"
        else:
            ai_reply = f"Error: Invalid response format from API. Details: {data}"

        if tool_used:
            ai_reply += f"\n\n (Tool used: {tool_used})"

    except requests.exceptions.RequestException as e:
        ai_reply = f"Error: Could not connect to backend. Details: {e}"

    # --- Streaming effect ---
    display_text = ""
    for char in ai_reply:
        display_text += char
        assistant_msg.markdown(display_text)
        time.sleep(0.005)

    # Save AI response
    st.session_state.messages.append({"role": "assistant", "content": ai_reply})


