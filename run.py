#!/usr/bin/env python3
"""Simple CLI to run iGallery locally using uv venv."""

import os
import sys
import subprocess
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
    
    subprocess.run(
        [str(python_venv), "-m", "igallery.app", "--gallery-root", str(resolved_gallery_root)] + sys.argv[2:],
        cwd=project_root,
        env=env
    )

if __name__ == '__main__':
    main()
