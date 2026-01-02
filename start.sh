#!/bin/bash

# ============================================================================
# DragonCP Web UI - System Launcher (start.sh)
# ============================================================================
# This script handles SYSTEM-LEVEL checks only:
#   - Python 3.12+ availability
#   - System dependencies (rsync, etc.)
#   - Hands off to start.py for Python-level setup
#
# For Python-level setup (venv, requirements, app startup), see start.py
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Minimum Python version required
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12

echo ""
echo -e "${BLUE}🐉 DragonCP Web UI - System Check${NC}"
echo "========================================"

# ============================================================================
# SYSTEM CHECK 1: Python Installation
# ============================================================================
check_python() {
    echo -e "\n${BLUE}[1/3] Checking Python installation...${NC}"
    
    # Try to find python3
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        # Check if 'python' is Python 3
        if python -c "import sys; sys.exit(0 if sys.version_info.major == 3 else 1)" 2>/dev/null; then
            PYTHON_CMD="python"
        else
            echo -e "${RED}❌ Python 3 is not installed or not in PATH${NC}"
            echo ""
            echo "Please install Python 3.12 or higher:"
            echo "  - Ubuntu/Debian: sudo apt install python3.12 python3.12-venv"
            echo "  - RHEL/CentOS:   sudo dnf install python3.12"
            echo "  - macOS:         brew install python@3.12"
            exit 1
        fi
    else
        echo -e "${RED}❌ Python is not installed or not in PATH${NC}"
        echo ""
        echo "Please install Python 3.12 or higher:"
        echo "  - Ubuntu/Debian: sudo apt install python3.12 python3.12-venv"
        echo "  - RHEL/CentOS:   sudo dnf install python3.12"
        echo "  - macOS:         brew install python@3.12"
        exit 1
    fi

    # Check Python version
    PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PYTHON_MAJOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.major)")
    PYTHON_MINOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.minor)")
    
    if [[ "$PYTHON_MAJOR" -lt "$MIN_PYTHON_MAJOR" ]] || \
       [[ "$PYTHON_MAJOR" -eq "$MIN_PYTHON_MAJOR" && "$PYTHON_MINOR" -lt "$MIN_PYTHON_MINOR" ]]; then
        echo -e "${RED}❌ Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR} or higher is required${NC}"
        echo "   Current version: $PYTHON_VERSION"
        echo ""
        echo "Please upgrade Python:"
        echo "  - Ubuntu/Debian: sudo apt install python3.12 python3.12-venv"
        echo "  - RHEL/CentOS:   sudo dnf install python3.12"
        echo "  - macOS:         brew install python@3.12"
        exit 1
    fi

    echo -e "${GREEN}✅ Python ${PYTHON_VERSION} found${NC}"
    
    # Check if venv module is available
    if ! $PYTHON_CMD -c "import venv" 2>/dev/null; then
        echo -e "${RED}❌ Python venv module is not available${NC}"
        echo ""
        echo "Please install the venv module:"
        echo "  - Ubuntu/Debian: sudo apt install python3.12-venv"
        echo "  - RHEL/CentOS:   sudo dnf install python3.12-venv"
        exit 1
    fi
    echo -e "${GREEN}✅ Python venv module available${NC}"
}

# ============================================================================
# SYSTEM CHECK 2: rsync
# ============================================================================
check_rsync() {
    echo -e "\n${BLUE}[2/3] Checking rsync installation...${NC}"
    
    if command -v rsync &> /dev/null; then
        RSYNC_VERSION=$(rsync --version 2>/dev/null | head -1 | awk '{print $3}')
        echo -e "${GREEN}✅ rsync ${RSYNC_VERSION} is available${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  rsync is not installed${NC}"
        echo ""
        echo "rsync is required for file transfers. Please install:"
        echo "  - Ubuntu/Debian: sudo apt install rsync"
        echo "  - RHEL/CentOS:   sudo dnf install rsync"
        echo "  - macOS:         brew install rsync"
        echo ""
        echo -e "${YELLOW}The application will start, but file transfers will not work.${NC}"
        return 1
    fi
}

# ============================================================================
# SYSTEM CHECK 3: Other System Dependencies (extensible)
# ============================================================================
check_other_dependencies() {
    echo -e "\n${BLUE}[3/3] Checking other system dependencies...${NC}"
    
    local all_ok=true
    
    # Check for curl (useful for health checks)
    if command -v curl &> /dev/null; then
        echo -e "${GREEN}✅ curl is available${NC}"
    else
        echo -e "${YELLOW}⚠️  curl is not installed (optional, for health checks)${NC}"
    fi
    
    # Add more system dependency checks here as needed
    # Example:
    # if command -v some_tool &> /dev/null; then
    #     echo -e "${GREEN}✅ some_tool is available${NC}"
    # else
    #     echo -e "${RED}❌ some_tool is required but not installed${NC}"
    #     all_ok=false
    # fi
    
    if [ "$all_ok" = true ]; then
        echo -e "${GREEN}✅ All system dependencies checked${NC}"
    fi
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================
main() {
    # Run system checks
    check_python
    check_rsync
    check_other_dependencies
    
    echo ""
    echo "========================================"
    echo -e "${GREEN}✅ System checks passed${NC}"
    echo "========================================"
    echo ""
    echo -e "${BLUE}Handing off to Python startup script...${NC}"
    echo ""
    
    # Hand off to start.py for Python-level setup
    # Pass the Python command as an environment variable
    export DRAGONCP_PYTHON_CMD="$PYTHON_CMD"
    
    # Run start.py with the system Python to handle venv setup
    exec $PYTHON_CMD start.py "$@"
}

# Run main function
main "$@"
