import uvicorn
import socket
import sys
from api.server import app

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

if __name__ == "__main__":
    PORT = 8080
    
    if is_port_in_use(PORT):
        print(f"\n[WARNING] Port {PORT} is already in use!")
        print("It looks like the server is already running (either manually or in the background).")
        print("Skipping duplicate server startup to prevent conflicts.\n")
        sys.exit(0)
        
    # Run the server on port 8080.
    # IV&V C1: bind loopback by default; override with APP_HOST if remote access
    # is genuinely needed (behind a tunnel/VPN, never raw on the LAN).
    import os as _os
    _host = _os.getenv("APP_HOST", "127.0.0.1")
    uvicorn.run("api.server:app", host=_host, port=PORT, reload=True)

