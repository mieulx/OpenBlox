#!/usr/bin/env python3
"""Launcher for Kilo Roblox Studio Helper.
Open http://localhost:8520 in your browser after starting.
"""

import subprocess, sys, os

DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(DIR, "server.py")
PORT = 8520

print(f"Starting Kilo Roblox Studio Helper...")
print(f"Open http://localhost:{PORT} in your browser")
print("Press Ctrl+C to stop the server.\n")

try:
    subprocess.run([sys.executable, SERVER], cwd=DIR)
except KeyboardInterrupt:
    print("\nServer stopped.")
