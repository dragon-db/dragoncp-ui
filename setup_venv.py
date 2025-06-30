#!/usr/bin/env python3
"""
DragonCP Web UI - Virtual Environment Setup Script
Helps users create and configure a virtual environment manually
"""

import os
import sys
import subprocess
import venv
from pathlib import Path

def main():
    print("🐉 DragonCP Web UI - Virtual Environment Setup")
    print("=" * 50)
    
    # Check if virtual environment already exists
    venv_paths = ["venv", "env", ".venv", ".env"]
    existing_venv = None
    
    for venv_name in venv_paths:
        venv_path = Path(venv_name)
        if venv_path.exists() and venv_path.is_dir():
            if (venv_path / "bin" / "python").exists() or (venv_path / "Scripts" / "python.exe").exists():
                existing_venv = venv_path
                break
    
    if existing_venv:
        print(f"✅ Virtual environment already exists: {existing_venv}")
        response = input("Would you like to recreate it? (y/n): ").lower().strip()
        if response in ['y', 'yes']:
            print(f"🗑️  Removing existing virtual environment: {existing_venv}")
            import shutil
            shutil.rmtree(existing_venv)
        else:
            print("Virtual environment setup complete!")
            return
    
    # Create virtual environment
    print("📦 Creating virtual environment...")
    try:
        venv.create("venv", with_pip=True)
        print("✅ Virtual environment created: venv/")
    except Exception as e:
        print(f"❌ Failed to create virtual environment: {e}")
        return
    
    # Determine Python and pip executables
    if os.name == 'nt':  # Windows
        python_exe = "venv/Scripts/python.exe"
        pip_exe = "venv/Scripts/pip.exe"
    else:  # Unix/Linux/macOS
        python_exe = "venv/bin/python"
        pip_exe = "venv/bin/pip"
    
    # Upgrade pip
    print("📦 Upgrading pip...")
    try:
        subprocess.run([python_exe, "-m", "pip", "install", "--upgrade", "pip"], 
                      check=True, capture_output=True)
        print("✅ pip upgraded successfully")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to upgrade pip: {e}")
    
    # Install dependencies
    print("📦 Installing dependencies...")
    try:
        subprocess.run([pip_exe, "install", "-r", "requirements.txt"], 
                      check=True, capture_output=True)
        print("✅ Dependencies installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return
    
    # Verify installation
    print("🔍 Verifying installation...")
    try:
        result = subprocess.run([python_exe, "-c", 
                               "import flask, flask_socketio, paramiko; print('All dependencies imported successfully')"], 
                              capture_output=True, text=True, check=True)
        print("✅ All dependencies verified")
    except subprocess.CalledProcessError as e:
        print(f"❌ Dependency verification failed: {e}")
        return
    
    print("\n🎉 Virtual environment setup complete!")
    print("=" * 50)
    print("You can now run the application using:")
    print("  • start.py (recommended)")
    print("  • start.sh (Linux/Mac)")
    print("  • start.bat (Windows)")
    print("  • Or manually: venv/bin/python app.py")

if __name__ == '__main__':
    main() 