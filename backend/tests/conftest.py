import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "postgresql+psycopg://manualmind:manualmind@127.0.0.1:5432/manualmind_test"
os.environ["AUTO_MIGRATE"] = "true"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["EMBED_WORKER"] = "false"
os.environ["LLM_ANSWERS"] = "false"
os.environ["OPENAI_API_KEY"] = ""
os.environ["MCP_SERVER_URL"] = "http://127.0.0.1:8097/mcp"
os.environ["MCP_PORT"] = "8097"
os.environ["STORAGE_LOCAL_PATH"] = "/tmp/manualmind-test-storage"
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://127.0.0.1:4178,http://localhost:4178"

_mcp = None


def pytest_sessionstart(session):
    global _mcp
    if _port_open(8097):
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "mcp_servers")
    _mcp = subprocess.Popen(
        [sys.executable, "-m", "manufacturer"],
        cwd=str(ROOT / "mcp_servers"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if _port_open(8097):
            return
        if _mcp.poll() is not None:
            output = _mcp.stdout.read().decode() if _mcp.stdout else ""
            raise RuntimeError(f"MCP server exited early:\n{output}")
        time.sleep(0.2)
    raise RuntimeError("MCP server did not open port 8097")


def pytest_sessionfinish(session, exitstatus):
    if _mcp is not None and _mcp.poll() is None:
        _mcp.terminate()
        try:
            _mcp.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _mcp.kill()


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0
