#!/usr/bin/env python3
"""
DragonCP Web UI Startup Script
Handles environment setup and launches the web interface with virtual environment support
"""

import os
import sys
import shutil
import subprocess
import venv
from pathlib import Path

def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 12):
        print("❌ Error: Python 3.12 or higher is required")
        print(f"Current version: {sys.version}")
        sys.exit(1)
    print(f"✅ Python version: {sys.version.split()[0]}")

def find_venv():
    """Find virtual environment in current directory"""
    venv_paths = [
        "venv",
        "env", 
        ".venv",
        ".env"
    ]
    
    for venv_name in venv_paths:
        venv_path = Path(venv_name)
        if venv_path.exists() and venv_path.is_dir():
            # Check if it's actually a virtual environment
            if (venv_path / "bin" / "python").exists() or (venv_path / "Scripts" / "python.exe").exists():
                return venv_path
    return None

def create_venv():
    """Create a new virtual environment"""
    print("📦 Creating virtual environment...")
    
    try:
        venv.create("venv", with_pip=True)
        print("✅ Virtual environment created: venv/")
        return Path("venv")
    except Exception as e:
        print(f"❌ Failed to create virtual environment: {e}")
        return None

def activate_venv(venv_path):
    """Activate virtual environment and return the Python executable path"""
    if os.name == 'nt':  # Windows
        python_exe = venv_path / "Scripts" / "python.exe"
        pip_exe = venv_path / "Scripts" / "pip.exe"
    else:  # Unix/Linux/macOS
        python_exe = venv_path / "bin" / "python"
        pip_exe = venv_path / "bin" / "pip"
    
    if not python_exe.exists():
        print(f"❌ Python executable not found in virtual environment: {python_exe}")
        return None, None
    
    print(f"✅ Using virtual environment: {venv_path}")
    return python_exe, pip_exe

def install_dependencies(pip_exe):
    """Install dependencies using the virtual environment's pip"""
    if not pip_exe or not pip_exe.exists():
        print("❌ pip executable not found in virtual environment")
        return False
    
    print("📦 Installing dependencies in virtual environment...")
    try:
        result = subprocess.run([str(pip_exe), "install", "-r", "requirements.txt"], 
                              capture_output=True, text=True, check=True)
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        print(f"Error output: {e.stderr}")
        return False

def check_dependencies_in_venv(python_exe):
    """Check if required dependencies are installed in virtual environment"""
    try:
        result = subprocess.run([str(python_exe), "-c", 
                               "import flask, flask_socketio, paramiko"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ All required dependencies are installed in virtual environment")
            return True
        else:
            print("❌ Missing dependencies in virtual environment")
            return False
    except Exception as e:
        print(f"❌ Error checking dependencies: {e}")
        return False

def setup_environment():
    """Setup environment file if it doesn't exist"""
    env_file = "dragoncp_env.env"
    sample_env = "dragoncp_env_sample.env"
    
    if not os.path.exists(env_file):
        if os.path.exists(sample_env):
            print("📋 Creating environment file from sample...")
            shutil.copy(sample_env, env_file)
            print("✅ Environment file created: dragoncp_env.env")
            print("⚠️  Please edit dragoncp_env.env with your server details before running")
            return False
        else:
            print("❌ Environment file not found and sample not available")
            print("Please create dragoncp_env.env manually")
            return False
    else:
        print("✅ Environment file found: dragoncp_env.env")
        return True

def check_rsync():
    """Check if rsync is available"""
    try:
        result = subprocess.run(['rsync', '--version'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✅ rsync is available")
            return True
        else:
            print("❌ rsync is not working properly")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("❌ rsync is not installed or not in PATH")
        print("Please install rsync to enable file transfers")
        return False

def create_directories():
    """Create necessary directories"""
    dirs = ['templates', 'static']
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
    print("✅ Directories created/verified")

def main():
    """Main startup function"""
    print("🐉 DragonCP Web UI Startup")
    print("=" * 40)
    
    # Check Python version
    check_python_version()
    
    # Find or create virtual environment
    venv_path = find_venv()
    
    if venv_path is None:
        print("📦 No virtual environment found")
        response = input("Would you like to create a virtual environment? (y/n): ").lower().strip()
        
        if response in ['y', 'yes']:
            venv_path = create_venv()
            if venv_path is None:
                print("❌ Failed to create virtual environment")
                sys.exit(1)
        else:
            print("⚠️  Running without virtual environment (not recommended)")
            python_exe = sys.executable
            pip_exe = None
            # Try to find pip
            try:
                import pip
                pip_exe = subprocess.run([sys.executable, "-m", "pip", "--version"], 
                                       capture_output=True, text=True)
                if pip_exe.returncode == 0:
                    pip_exe = [sys.executable, "-m", "pip"]
            except ImportError:
                pass
    else:
        print(f"✅ Found virtual environment: {venv_path}")
    
    # Activate virtual environment
    if venv_path:
        python_exe, pip_exe = activate_venv(venv_path)
        if python_exe is None:
            print("❌ Failed to activate virtual environment")
            sys.exit(1)
    else:
        python_exe = sys.executable
        pip_exe = [sys.executable, "-m", "pip"]
    
    # Check and install dependencies
    if not check_dependencies_in_venv(python_exe):
        if pip_exe:
            if not install_dependencies(pip_exe):
                print("❌ Failed to install dependencies")
                sys.exit(1)
        else:
            print("❌ Cannot install dependencies - pip not available")
            sys.exit(1)
    
    # Setup environment
    if not setup_environment():
        print("\n📝 Please configure your environment file and run again")
        sys.exit(1)
    
    # Check rsync
    if not check_rsync():
        print("\n⚠️  rsync is required for file transfers")
        print("The web UI will work but transfers will fail")
    
    # Create directories
    create_directories()
    
    print("\n🚀 Starting DragonCP Web UI...")
    print("📱 Access the interface at: http://localhost:5000")
    print("🔄 Press Ctrl+C to stop the server")
    print("=" * 40)
    
    # Import and run the app using the virtual environment's Python
    try:
        # Change to the directory containing app.py
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        
        # Run the app using the virtual environment's Python
        result = subprocess.run([str(python_exe), "app.py"])
        
        if result.returncode != 0:
            print(f"\n❌ Application exited with code: {result.returncode}")
            sys.exit(result.returncode)
            
    except KeyboardInterrupt:
        print("\n👋 DragonCP Web UI stopped")
    except Exception as e:
        print(f"\n❌ Error starting application: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main() 