from fastmcp import FastMCP

mcp = FastMCP("mcp_chatmemory")

chat_memory = []

@mcp.tool(name="remember", description="Store a message in memory.")
def remember(message: str) -> str:
    """Store a message in memory."""
    chat_memory.append(message)
    return f"Remembered: '{message}'"

@mcp.tool(name="recall", description="Retrieve the last n messages from memory.")
def recall(n: int = 5) -> list[str]:
    """Retrieve the last n remembered messages."""
    return chat_memory[-n:] if chat_memory else ["No memory yet."]

@mcp.tool(name="clear_memory", description="Clear all stored messages.")
def clear_memory() -> str:
    """Clear the chat memory."""
    chat_memory.clear()
    return "Memory cleared."

if __name__ == "__main__":
    mcp.run()
