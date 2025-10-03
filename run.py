#!/usr/bin/env python3
"""Simple CLI to run Image Trashing Service locally using uv venv."""

import os
import sys
import subprocess
import socket
from pathlib import Path

def main():
    project_root = Path(__file__).parent
    venv_path = project_root / ".venv"
    python_venv = venv_path / "bin" / "python"

    # Create venv if it doesn't exist
    if not venv_path.exists():
        print("Creating virtual environment with uv...")
        subprocess.run(["uv", "venv"], cwd=project_root, check=True)

    # Install dependencies if not already installed
    marker_file = venv_path / ".deps_installed"
    if not marker_file.exists():
        print("Installing dependencies with uv...")
        subprocess.run(
            ["uv", "pip", "install", "flask", "pillow", "pytest", "pytest-cov"],
            cwd=project_root,
            check=True
        )
        marker_file.touch()

    # Run the app using the venv Python
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    # Determine the gallery root from CLI arguments or default to current directory
    gallery_root_arg_value = "."
    if len(sys.argv) > 1:
        gallery_root_arg_value = sys.argv[1]
    
    # Resolve the gallery root to an absolute path immediately
    resolved_gallery_root = Path(project_root / gallery_root_arg_value).resolve()

    # Get local IP address for network access info
    def get_local_ip():
        try:
            # Connect to an external address to determine local IP
            # This doesn't actually send data, just determines the route
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return None

    local_ip = get_local_ip()

    print("\n" + "="*60)
    print("Image Trashing Service")
    print("="*60)
    print(f"Gallery: {resolved_gallery_root}")
    print(f"\nAccess URLs:")
    print(f"  Local:   http://localhost:8000")
    if local_ip:
        print(f"  Network: http://{local_ip}:8000")
    print("\nPress Ctrl+C to stop")
    print("="*60 + "\n")

    try:
        subprocess.run(
            [str(python_venv), "-m", "igallery.app", "--gallery-root", str(resolved_gallery_root)] + sys.argv[2:],
            cwd=project_root,
            env=env
        )
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C - the subprocess already handled it
        sys.exit(0)

if __name__ == '__main__':
    main()
