#!/bin/bash

echo "🐉 DragonCP Web UI - Linux/Mac Launcher"
echo "======================================"

# Function to find virtual environment
find_venv() {
    local venv_paths=("venv" "env" ".venv" ".env")
    
    for venv_name in "${venv_paths[@]}"; do
        if [[ -d "$venv_name" ]]; then
            # Check if it's actually a virtual environment
            if [[ -f "$venv_name/bin/python" ]]; then
                echo "$venv_name"
                return 0
            fi
        fi
    done
    return 1
}

# Function to create virtual environment
create_venv() {
    echo "📦 Creating virtual environment..."
    if python3 -m venv venv; then
        echo "✅ Virtual environment created: venv/"
        return 0
    else
        echo "❌ Failed to create virtual environment"
        return 1
    fi
}

# Function to activate virtual environment
activate_venv() {
    local venv_path="$1"
    echo "✅ Using virtual environment: $venv_path"
    source "$venv_path/bin/activate"
    return 0
}

# Function to install dependencies
install_dependencies() {
    echo "📦 Installing dependencies in virtual environment..."
    if pip install -r requirements.txt; then
        echo "✅ Dependencies installed successfully"
        return 0
    else
        echo "❌ Failed to install dependencies"
        return 1
    fi
}

# Function to check dependencies
check_dependencies() {
    if python -c "import flask, flask_socketio, paramiko" 2>/dev/null; then
        echo "✅ All required dependencies are installed"
        return 0
    else
        echo "❌ Missing dependencies"
        return 1
    fi
}

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed or not in PATH"
    echo "Please install Python 3.12 or higher"
    exit 1
fi

# Check Python version
python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
required_version="3.12"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "❌ Python 3.12 or higher is required"
    echo "Current version: $python_version"
    exit 1
fi

echo "✅ Python version: $python_version"

# Find or create virtual environment
venv_path=$(find_venv)

if [[ -z "$venv_path" ]]; then
    echo "📦 No virtual environment found"
    read -p "Would you like to create a virtual environment? (y/n): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if create_venv; then
            venv_path="venv"
        else
            exit 1
        fi
    else
        echo "⚠️  Running without virtual environment (not recommended)"
        venv_path=""
    fi
else
    echo "✅ Found virtual environment: $venv_path"
fi

# Activate virtual environment if found
if [[ -n "$venv_path" ]]; then
    if ! activate_venv "$venv_path"; then
        echo "❌ Failed to activate virtual environment"
        exit 1
    fi
fi

# Check and install dependencies
if ! check_dependencies; then
    if ! install_dependencies; then
        echo "❌ Failed to install dependencies"
        exit 1
    fi
fi

# Check if rsync is available
if ! command -v rsync &> /dev/null; then
    echo "⚠️  rsync is not installed"
    echo "File transfers will not work without rsync"
    echo "Please install rsync: sudo apt-get install rsync (Ubuntu/Debian)"
    echo "or: brew install rsync (macOS)"
fi

# Create necessary directories
mkdir -p templates static
echo "✅ Directories created/verified"

# Start the application
echo "🚀 Starting DragonCP Web UI..."
echo "📱 Access the interface at: http://localhost:5000"
echo "🔄 Press Ctrl+C to stop the server"
echo "======================================"

# Run the Python startup script
python3 start.py 