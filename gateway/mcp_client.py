"""MCP Client - Communicates with the Rust mcp-server."""

import asyncio
import json
import subprocess
from typing import AsyncIterator

import httpx
import structlog

from app.config import get_settings
from models import JsonRpcRequest, JsonRpcResponse

logger = structlog.get_logger()


class McpClient:
    """Client for communicating with mcp-server (Rust).
    
    Supports two modes:
    - subprocess: Spawns mcp-server as child process, communicates via stdio
    - http: Connects to running mcp-server via HTTP
    """

    def __init__(self):
        self.settings = get_settings()
        self._process: subprocess.Popen | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._request_id = 0
        self._pending_requests: dict[int | str, asyncio.Future] = {}
        self._read_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the MCP client connection."""
        if self.settings.mcp_server_mode == "subprocess":
            await self._start_subprocess()
        else:
            await self._start_http()

    async def _start_subprocess(self) -> None:
        """Start mcp-server as subprocess."""
        logger.info("Starting mcp-server subprocess", path=self.settings.mcp_server_path)
        
        try:
            self._process = subprocess.Popen(
                [self.settings.mcp_server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )
            
            # Start background reader task
            self._read_task = asyncio.create_task(self._read_responses())
            
            logger.info("mcp-server subprocess started", pid=self._process.pid)
        except Exception as e:
            logger.error("Failed to start mcp-server", error=str(e))
            raise

    async def _start_http(self) -> None:
        """Connect to mcp-server via HTTP."""
        logger.info("Connecting to mcp-server via HTTP", url=self.settings.mcp_server_url)
        self._http_client = httpx.AsyncClient(
            base_url=self.settings.mcp_server_url,
            timeout=30.0,
        )

    async def _read_responses(self) -> None:
        """Background task to read responses from subprocess."""
        if not self._process or not self._process.stdout:
            return

        loop = asyncio.get_event_loop()
        
        while True:
            try:
                # Read line from subprocess stdout in executor
                line = await loop.run_in_executor(
                    None, self._process.stdout.readline
                )
                
                if not line:
                    break  # EOF
                    
                line = line.strip()
                if not line:
                    continue
                    
                logger.debug("Received from mcp-server", response=line[:200])
                
                try:
                    response_data = json.loads(line)
                    response = JsonRpcResponse.model_validate(response_data)
                    
                    # Resolve pending request
                    if response.id in self._pending_requests:
                        future = self._pending_requests.pop(response.id)
                        if not future.done():
                            future.set_result(response)
                except json.JSONDecodeError as e:
                    logger.warning("Invalid JSON from mcp-server", error=str(e))
                    
            except Exception as e:
                logger.error("Error reading from mcp-server", error=str(e))
                break

    async def send_request(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """Send a request to mcp-server and wait for response."""
        async with self._lock:
            self._request_id += 1
            if request.id is None:
                request.id = self._request_id

        if self.settings.mcp_server_mode == "subprocess":
            return await self._send_subprocess(request)
        else:
            return await self._send_http(request)

    async def _send_subprocess(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """Send request via subprocess stdio."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("mcp-server subprocess not running")

        # Create future for response
        future: asyncio.Future[JsonRpcResponse] = asyncio.Future()
        self._pending_requests[request.id] = future

        # Write request to stdin
        request_json = request.model_dump_json()
        logger.debug("Sending to mcp-server", request=request_json[:200])
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: (
                self._process.stdin.write(request_json + "\n"),
                self._process.stdin.flush(),
            )
        )

        # Wait for response with timeout
        try:
            response = await asyncio.wait_for(future, timeout=30.0)
            return response
        except asyncio.TimeoutError:
            self._pending_requests.pop(request.id, None)
            raise TimeoutError(f"Request {request.method} timed out")

    async def _send_http(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """Send request via HTTP."""
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")

        response = await self._http_client.post(
            "/mcp",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return JsonRpcResponse.model_validate(response.json())

    async def stop(self) -> None:
        """Stop the MCP client."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            logger.info("mcp-server subprocess stopped")

        if self._http_client:
            await self._http_client.aclose()

    @property
    def is_running(self) -> bool:
        """Check if client is connected."""
        if self.settings.mcp_server_mode == "subprocess":
            return self._process is not None and self._process.poll() is None
        else:
            return self._http_client is not None


# Global singleton
_mcp_client: McpClient | None = None


async def get_mcp_client() -> McpClient:
    """Get or create MCP client singleton."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = McpClient()
        await _mcp_client.start()
    return _mcp_client


async def shutdown_mcp_client() -> None:
    """Shutdown MCP client."""
    global _mcp_client
    if _mcp_client:
        await _mcp_client.stop()
        _mcp_client = None
