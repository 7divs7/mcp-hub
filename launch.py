import subprocess
import time
import sys
import os

def run_process(command, cwd):
    """Run a subprocess and stream its output."""
    return subprocess.Popen(
        command,
        cwd=cwd,
        stdout=sys.stdout,
        stderr=sys.stderr,
        shell=False,
    )

def main():
    project_root = os.path.join(os.path.dirname(__file__), "src", "mcp_hub")

    print("🚀 Launching MCP Hub...")
    print("→ Starting backend (FastAPI)...")

    backend = run_process(
        ["uv", "run", "uvicorn", "backend:app", "--reload", "--port", "8000"],
        cwd=project_root,
    )

    # Give backend a moment to spin up
    time.sleep(2)

    print("→ Starting frontend (Streamlit)...")
    frontend = run_process(
        ["uv", "run", "streamlit", "run", "frontend.py"],
        cwd=project_root,
    )

    print("\nBoth services are running:")
    print("   • Backend:  http://localhost:8000")
    print("   • Frontend: http://localhost:8501")
    print("   Press Ctrl+C to stop.\n")

    try:
        backend.wait()
        frontend.wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down MCP Hub...")
        backend.terminate()
        frontend.terminate()
        sys.exit(0)

if __name__ == "__main__":
    main()
