#!/bin/bash

# Installation script for Bill Print webapp

echo "=================================="
echo "Bill Print Webapp - Installation"
echo "=================================="
echo ""
echo "⚠️  IMPORTANT: If the app is currently running, stop it first!"
echo "   (Press Ctrl+C in the Terminal window running the server)"
echo ""

# Clear stale Python bytecode from any previous install
echo "Clearing cached bytecode..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null
echo "✅ Bytecode cache cleared"
echo ""

# Check Python version
echo "Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed"
    echo "Please install Python 3.8+ from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo "✅ Found Python $PYTHON_VERSION"
echo ""

# Check pip
echo "Checking pip..."
if ! command -v pip3 &> /dev/null; then
    echo "❌ Error: pip3 is not installed"
    exit 1
fi
echo "✅ pip3 is available"
echo ""

# Install dependencies
echo "Installing Python dependencies..."
echo "This may take a few minutes..."
echo ""

pip3 install --user -r requirements.txt

if [ $? -ne 0 ]; then
    echo "❌ Error: Failed to install dependencies"
    exit 1
fi

echo ""
echo "✅ Dependencies installed successfully"
echo ""

# Make scripts executable
echo "Making scripts executable..."
chmod +x run.sh
chmod +x install.sh
echo "✅ Scripts are now executable"
echo ""

# Create directories
echo "Creating necessary directories..."
mkdir -p uploads output/bills
echo "✅ Directories created"
echo ""

# Create desktop shortcut for macOS
echo "Creating desktop shortcut..."
DESKTOP_PATH="$HOME/Desktop/BatchBill.command"
APP_PATH="$(pwd)"

cat > "$DESKTOP_PATH" << EOF
#!/bin/bash
cd "$APP_PATH"
./run.sh
EOF

chmod +x "$DESKTOP_PATH"
echo "✅ Desktop shortcut created: ~/Desktop/BatchBill.command"
echo ""

echo "=================================="
echo "✅ Installation Complete!"
echo "=================================="
echo ""
echo "To start the application:"
echo "  1. Double-click 'BatchBill.command' on your Desktop"
echo "  2. Or run: ./run.sh"
echo ""
echo "The webapp will open in your default browser at http://localhost:5003"
echo ""
