#!/usr/bin/env python3
"""
DragonCP Web UI - Python Startup Script (start.py)
============================================================================
This script handles PYTHON-LEVEL setup:
  - Virtual environment creation/detection
  - Requirements.txt validation and installation
  - Environment file setup
  - Directory creation
  - Frontend build (placeholder)
  - Backend application startup

For system-level checks (Python, rsync), see start.sh
============================================================================
"""

import os
import sys
import shutil
import subprocess
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Set


# ============================================================================
# CONFIGURATION
# ============================================================================

MIN_PYTHON_VERSION = (3, 12)
VENV_NAMES = ["venv", "env", ".venv", ".env"]
REQUIREMENTS_FILE = "requirements.txt"
ENV_FILE = "dragoncp_env.env"
SAMPLE_ENV_FILE = "dragoncp_env_sample.env"
REQUIRED_DIRS = ["templates", "static"]

# Colors for terminal output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color
    
    @staticmethod
    def disable():
        """Disable colors for non-TTY output"""
        Colors.RED = ''
        Colors.GREEN = ''
        Colors.YELLOW = ''
        Colors.BLUE = ''
        Colors.CYAN = ''
        Colors.NC = ''


# Disable colors if not a TTY
if not sys.stdout.isatty():
    Colors.disable()


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def print_header(text: str):
    """Print a section header"""
    print(f"\n{Colors.BLUE}{text}{Colors.NC}")


def print_success(text: str):
    """Print a success message"""
    print(f"{Colors.GREEN}✅ {text}{Colors.NC}")


def print_warning(text: str):
    """Print a warning message"""
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.NC}")


def print_error(text: str):
    """Print an error message"""
    print(f"{Colors.RED}❌ {text}{Colors.NC}")


def print_info(text: str):
    """Print an info message"""
    print(f"{Colors.CYAN}ℹ️  {text}{Colors.NC}")


def ask_yes_no(question: str, default: bool = True) -> bool:
    """Ask a yes/no question and return the answer"""
    suffix = " (Y/n): " if default else " (y/N): "
    try:
        response = input(question + suffix).strip().lower()
        if not response:
            return default
        return response in ['y', 'yes']
    except (EOFError, KeyboardInterrupt):
        print()
        return default


# ============================================================================
# PYTHON VERSION CHECK
# ============================================================================

def check_python_version() -> bool:
    """Check if Python version meets minimum requirements"""
    print_header("[1/6] Checking Python version...")
    
    if sys.version_info < MIN_PYTHON_VERSION:
        print_error(f"Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or higher is required")
        print(f"   Current version: {sys.version}")
        return False
    
    print_success(f"Python {sys.version.split()[0]}")
    return True


# ============================================================================
# VIRTUAL ENVIRONMENT MANAGEMENT
# ============================================================================

def find_venv() -> Optional[Path]:
    """Find existing virtual environment in current directory"""
    for venv_name in VENV_NAMES:
        venv_path = Path(venv_name)
        if venv_path.exists() and venv_path.is_dir():
            # Check if it's actually a virtual environment (Unix or Windows)
            if (venv_path / "bin" / "python").exists() or \
               (venv_path / "Scripts" / "python.exe").exists():
                return venv_path
    return None


def create_venv(venv_name: str = "venv") -> Optional[Path]:
    """Create a new virtual environment"""
    print_info(f"Creating virtual environment: {venv_name}/")
    
    try:
        import venv
        venv.create(venv_name, with_pip=True)
        print_success(f"Virtual environment created: {venv_name}/")
        return Path(venv_name)
    except Exception as e:
        print_error(f"Failed to create virtual environment: {e}")
        return None


def get_venv_executables(venv_path: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """Get Python and pip executables from virtual environment"""
    if os.name == 'nt':  # Windows
        python_exe = venv_path / "Scripts" / "python.exe"
        pip_exe = venv_path / "Scripts" / "pip.exe"
    else:  # Unix/Linux/macOS
        python_exe = venv_path / "bin" / "python"
        pip_exe = venv_path / "bin" / "pip"
    
    if not python_exe.exists():
        print_error(f"Python executable not found: {python_exe}")
        return None, None
    
    if not pip_exe.exists():
        print_warning(f"pip executable not found: {pip_exe}")
        # pip might still work via python -m pip
    
    return python_exe, pip_exe


def setup_venv() -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """Setup virtual environment - find existing or create new"""
    print_header("[2/6] Setting up virtual environment...")
    
    venv_path = find_venv()
    
    if venv_path:
        print_success(f"Found existing virtual environment: {venv_path}/")
    else:
        print_warning("No virtual environment found")
        print()
        
        if ask_yes_no("Create a new virtual environment?"):
            venv_path = create_venv()
            if not venv_path:
                return None, None, None
        else:
            print_error("Virtual environment is required to run this application")
            print_info("Please create a virtual environment manually and try again")
            return None, None, None
    
    python_exe, pip_exe = get_venv_executables(venv_path)
    if not python_exe:
        return None, None, None
    
    print_success(f"Using virtual environment: {venv_path}/")
    return venv_path, python_exe, pip_exe


# ============================================================================
# REQUIREMENTS MANAGEMENT (KEY IMPROVEMENT)
# ============================================================================

def parse_requirements_file(filepath: str = REQUIREMENTS_FILE) -> Dict[str, Optional[str]]:
    """
    Parse requirements.txt and return dict of {package_name: version_spec}
    Handles various formats:
      - package==1.0.0
      - package>=1.0.0
      - package~=1.0.0
      - package (no version)
      - package[extras]==1.0.0
      - Comments and empty lines are ignored
    """
    requirements = {}
    
    if not os.path.exists(filepath):
        print_warning(f"Requirements file not found: {filepath}")
        return requirements
    
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Skip -r, -e, and other pip options
            if line.startswith('-'):
                continue
            
            # Handle package[extras] format
            # Extract package name (before any version specifier or extras)
            match = re.match(r'^([a-zA-Z0-9_-]+)', line)
            if match:
                package_name = match.group(1).lower()
                
                # Extract version spec if present
                version_match = re.search(r'([=<>!~]+.+)$', line.split('[')[0] if '[' in line else line)
                version_spec = version_match.group(1) if version_match else None
                
                requirements[package_name] = version_spec
    
    return requirements


def get_installed_packages(python_exe: Path) -> Dict[str, str]:
    """
    Get list of installed packages in the virtual environment
    Returns dict of {package_name: installed_version}
    """
    installed = {}
    
    try:
        result = subprocess.run(
            [str(python_exe), "-m", "pip", "list", "--format=freeze"],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if '==' in line:
                    parts = line.split('==')
                    package_name = parts[0].lower()
                    version = parts[1] if len(parts) > 1 else ''
                    installed[package_name] = version
    except subprocess.TimeoutExpired:
        print_warning("Timeout getting installed packages")
    except Exception as e:
        print_warning(f"Error getting installed packages: {e}")
    
    return installed


def normalize_package_name(name: str) -> str:
    """Normalize package name for comparison (PyPI is case-insensitive, uses - or _)"""
    return name.lower().replace('_', '-')


def check_requirements(python_exe: Path) -> Tuple[bool, List[str], List[str]]:
    """
    Check if all requirements are installed in the virtual environment
    Returns: (all_installed, missing_packages, outdated_packages)
    """
    print_header("[3/6] Checking Python dependencies...")
    
    required = parse_requirements_file()
    installed = get_installed_packages(python_exe)
    
    if not required:
        print_warning("No requirements found in requirements.txt")
        return True, [], []
    
    # Normalize installed package names for comparison
    installed_normalized = {normalize_package_name(k): v for k, v in installed.items()}
    
    missing = []
    outdated = []
    
    for package, version_spec in required.items():
        normalized_name = normalize_package_name(package)
        
        if normalized_name not in installed_normalized:
            missing.append(package)
        elif version_spec:
            # For exact version match (==), check if versions match
            if version_spec.startswith('=='):
                required_version = version_spec[2:]
                installed_version = installed_normalized[normalized_name]
                if installed_version != required_version:
                    outdated.append(f"{package} (installed: {installed_version}, required: {required_version})")
    
    # Report status
    total_packages = len(required)
    installed_count = total_packages - len(missing)
    
    if missing:
        print_warning(f"Missing packages ({len(missing)}/{total_packages}):")
        for pkg in missing:
            print(f"     - {pkg}")
    
    if outdated:
        print_warning(f"Version mismatch ({len(outdated)}):")
        for pkg in outdated:
            print(f"     - {pkg}")
    
    if not missing and not outdated:
        print_success(f"All {total_packages} required packages are installed")
        return True, [], []
    
    return False, missing, outdated


def install_requirements(pip_exe: Optional[Path], python_exe: Path) -> bool:
    """Install requirements from requirements.txt"""
    print()
    print_info("Installing/updating dependencies from requirements.txt...")
    
    try:
        # Use python -m pip for more reliable execution
        result = subprocess.run(
            [str(python_exe), "-m", "pip", "install", "-r", REQUIREMENTS_FILE],
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            print_success("All dependencies installed successfully")
            return True
        else:
            print_error(f"pip install failed with exit code: {result.returncode}")
            return False
            
    except subprocess.TimeoutExpired:
        print_error("Installation timed out after 5 minutes")
        return False
    except Exception as e:
        print_error(f"Failed to install dependencies: {e}")
        return False


def handle_requirements(python_exe: Path, pip_exe: Optional[Path]) -> bool:
    """Check requirements and install if needed"""
    all_ok, missing, outdated = check_requirements(python_exe)
    
    if all_ok:
        return True
    
    # Ask user if they want to install missing packages
    print()
    if ask_yes_no("Install/update missing dependencies?"):
        if install_requirements(pip_exe, python_exe):
            # Verify installation
            all_ok, missing, outdated = check_requirements(python_exe)
            if all_ok:
                return True
            else:
                print_error("Some packages still missing after installation")
                return False
        else:
            return False
    else:
        print_error("Cannot continue without required dependencies")
        print()
        print("To install manually, run:")
        print(f"  {python_exe} -m pip install -r {REQUIREMENTS_FILE}")
        return False


# ============================================================================
# ENVIRONMENT FILE SETUP
# ============================================================================

def setup_environment_file() -> bool:
    """Setup environment file if it doesn't exist"""
    print_header("[4/6] Checking environment configuration...")
    
    if os.path.exists(ENV_FILE):
        print_success(f"Environment file found: {ENV_FILE}")
        return True
    
    print_warning(f"Environment file not found: {ENV_FILE}")
    
    if os.path.exists(SAMPLE_ENV_FILE):
        print()
        if ask_yes_no(f"Create {ENV_FILE} from sample?"):
            try:
                shutil.copy(SAMPLE_ENV_FILE, ENV_FILE)
                print_success(f"Environment file created: {ENV_FILE}")
                print_warning("Please edit the environment file with your server details")
                print()
                print_info(f"Edit: {os.path.abspath(ENV_FILE)}")
                print()
                
                if not ask_yes_no("Continue with default configuration?", default=False):
                    print_info("Please edit the environment file and run again")
                    return False
                    
                return True
            except Exception as e:
                print_error(f"Failed to create environment file: {e}")
                return False
    else:
        print_error(f"Sample environment file not found: {SAMPLE_ENV_FILE}")
        print_info("Please create the environment file manually")
        return False
    
    return False


# ============================================================================
# DIRECTORY SETUP
# ============================================================================

def create_directories() -> bool:
    """Create necessary directories"""
    print_header("[5/6] Creating directories...")
    
    for dir_name in REQUIRED_DIRS:
        try:
            Path(dir_name).mkdir(exist_ok=True)
        except Exception as e:
            print_error(f"Failed to create directory '{dir_name}': {e}")
            return False
    
    print_success(f"Directories verified: {', '.join(REQUIRED_DIRS)}")
    return True


# ============================================================================
# FRONTEND BUILD (PLACEHOLDER)
# ============================================================================

def build_frontend() -> bool:
    """
    Build frontend application (placeholder for future React integration)
    Currently does nothing, returns True
    """
    # Placeholder for future frontend build
    # When React frontend is added, this will:
    # 1. Check if node/npm is available
    # 2. Check if node_modules exists, run npm install if not
    # 3. Run npm run build
    # 4. Verify build output exists
    
    frontend_path = Path("frontend")
    
    if frontend_path.exists() and (frontend_path / "package.json").exists():
        print_header("[5.5/6] Building frontend (placeholder)...")
        print_info("Frontend build will be implemented when React app is added")
        # TODO: Implement frontend build when React is integrated
        # - Check for node/npm
        # - Run npm install if node_modules missing
        # - Run npm run build
        # - Verify dist/build directory exists
    
    return True


# ============================================================================
# APPLICATION STARTUP
# ============================================================================

def start_application(python_exe: Path) -> int:
    """Start the DragonCP backend application"""
    print_header("[6/6] Starting DragonCP Web UI...")
    
    print()
    print("=" * 50)
    print(f"{Colors.GREEN}🚀 DragonCP Web UI{Colors.NC}")
    print("=" * 50)
    print(f"📱 Access the interface at: {Colors.CYAN}http://localhost:5000{Colors.NC}")
    print(f"🔄 Press {Colors.YELLOW}Ctrl+C{Colors.NC} to stop the server")
    print("=" * 50)
    print()
    
    try:
        # Ensure we're in the correct directory
        script_dir = Path(__file__).parent.absolute()
        os.chdir(script_dir)
        
        # Start the application
        result = subprocess.run([str(python_exe), "app.py"])
        return result.returncode
        
    except KeyboardInterrupt:
        print()
        print(f"\n{Colors.CYAN}👋 DragonCP Web UI stopped{Colors.NC}")
        return 0
    except Exception as e:
        print_error(f"Error starting application: {e}")
        return 1


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main() -> int:
    """Main startup function"""
    print()
    print(f"{Colors.BLUE}🐉 DragonCP Web UI - Python Setup{Colors.NC}")
    print("=" * 50)
    
    # Ensure we're in the script directory
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)
    
    # Step 1: Check Python version
    if not check_python_version():
        return 1
    
    # Step 2: Setup virtual environment
    venv_path, python_exe, pip_exe = setup_venv()
    if not python_exe:
        return 1
    
    # Step 3: Check and install requirements
    if not handle_requirements(python_exe, pip_exe):
        return 1
    
    # Step 4: Setup environment file
    if not setup_environment_file():
        return 1
    
    # Step 5: Create directories
    if not create_directories():
        return 1
    
    # Step 5.5: Build frontend (placeholder)
    if not build_frontend():
        return 1
    
    # Step 6: Start the application
    return start_application(python_exe)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.CYAN}👋 Startup cancelled{Colors.NC}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Colors.RED}❌ Unexpected error: {e}{Colors.NC}")
        sys.exit(1)
