#!/usr/bin/env python3
"""
Test MCP connection, JSON-MCP config generation, and natural language Prompt Compression.
"""

import json
import requests
import sseclient
import uuid
import threading
import time

AGENT_ID = "00000000-0000-0000-0000-000000000000"
CONFIG_URL = f"http://localhost:3020/api/agents/{AGENT_ID}/mcp-config"

def test_mcp_compression():
    print("--- Testing MCP Prompt Compressor Flow ---")
    
    print(f"\n1. Fetching JSON-MCP config from {CONFIG_URL}")
    try:
        config_resp = requests.get(CONFIG_URL)
        if config_resp.status_code == 404:
            print("Agent not found. Proceeding directly to the SSE URL.")
            sse_url = f"http://localhost:3020/api/v1/mcp/sse?agent_id={AGENT_ID}"
        else:
            config_resp.raise_for_status()
            config = config_resp.json()
            print(f"✓ Got Config: {json.dumps(config, indent=2)}")
            servers = config.get("mcpServers", {})
            server_key = list(servers.keys())[0] if servers else None
            sse_url = servers[server_key]["url"] if server_key else f"http://localhost:3020/api/v1/mcp/sse?agent_id={AGENT_ID}"
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch config: {e}. Using default SSE URL.")
        sse_url = f"http://localhost:3020/api/v1/mcp/sse?agent_id={AGENT_ID}"
        
    print(f"\n2. Connecting to SSE endpoint: {sse_url}")
    
    messages_endpoint = None
    got_endpoint = threading.Event()
    
    def sse_reader():
        nonlocal messages_endpoint
        try:
            response = requests.get(sse_url, stream=True, timeout=30)
            if response.status_code == 200:
                print("✓ SSE connection established")
                client = sseclient.SSEClient(response)
                for event in client.events():
                    if event.event == 'endpoint':
                        messages_endpoint = event.data
                        print(f"✓ Received messages endpoint: {messages_endpoint}")
                        got_endpoint.set()
                    elif event.event == 'message':
                        try:
                            data = json.loads(event.data)
                            if "result" in data:
                                print(f"\n✓ Received Tool Result (Compact format expected):")
                                print("--------------------------------------------------")
                                if "content" in data["result"]:
                                    for item in data["result"]["content"]:
                                        if item.get("type") == "text":
                                            print(item.get("text"))
                                else:
                                    print(json.dumps(data["result"], indent=2))
                                print("--------------------------------------------------")
                            elif "error" in data:
                                print(f"✗ Tool Error: {data['error']}")
                        except json.JSONDecodeError:
                            print(f"Received non-JSON message: {event.data}")
            else:
                print(f"✗ SSE connection failed: {response.status_code}")
        except Exception as e:
            print(f"SSE stream closed or failed: {e}")
            
    sse_thread = threading.Thread(target=sse_reader, daemon=True)
    sse_thread.start()
    
    if got_endpoint.wait(timeout=10):
        print("\n3. Sending natural language query to `query_knowledge`...")
        print("   Prompt: 'Could you please tell me how the authentication middleware validates JWT tokens?'")
        
        tool_call_request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": "query_knowledge",
                "arguments": {
                    "intent": "Learn how to use Arena and append nodes in the indextree Rust crate",
                    "keywords": ["indextree", "Arena", "append", "node"],
                    "limit": 3
                }
            }
        }
        
        try:
            post_url = messages_endpoint
            if not post_url.startswith("http"):
                post_url = f"http://localhost:3020{post_url}"
                
            # First send initialize
            init_req = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"}
                }
            }
            requests.post(post_url, json=init_req, headers={"Content-Type": "application/json"})
            time.sleep(0.5)
            
            # Send initialized notification
            initialized_req = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }
            requests.post(post_url, json=initialized_req, headers={"Content-Type": "application/json"})
            time.sleep(0.5)
                
            response = requests.post(
                post_url,
                json=tool_call_request,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code not in (200, 202):
                print(f"✗ Tool call POST failed: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"✗ Tool call request failed: {e}")
            
        # Wait a bit for the SSE stream to receive the response
        time.sleep(4)
    else:
        print("✗ Could not establish proper MCP session (timeout)")
        
    print("\nTest completed.")

if __name__ == "__main__":
    test_mcp_compression()
