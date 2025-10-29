from fastmcp import FastMCP
import datetime
import requests

mcp = FastMCP("mcp_todayinfo")

@mcp.tool(name="get_date", description="Return the current date and time")
def get_date() -> str:
    """Return the current date and time."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@mcp.tool(name="get_weather", description="Return the weather for a given city.")
def get_weather(city: str) -> str:
    """Return weather info for a given city."""
    try:
        url = f"https://wttr.in/{city}?format=3"
        response = requests.get(url)
        return response.text if response.status_code == 200 else "Weather data unavailable"
    except Exception as e:
        return f"Error fetching weather: {e}"

if __name__ == "__main__":
    mcp.run()
