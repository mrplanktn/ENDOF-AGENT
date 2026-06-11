#!/usr/bin/env bash
# ==============================================================================
# NexusAgent Installer
# ==============================================================================
set -euo pipefail

NEXUS_VERSION="${NEXUS_VERSION:-latest}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.nexusagent}"
PYTHON_MIN="3.11"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo -e "${BLUE}"
echo "  ╔═══════════════════════════════════════╗"
echo "  ║        NexusAgent Installer           ║"
echo "  ║   The Universal AI Agent Framework    ║"
echo "  ╚═══════════════════════════════════════╝"
echo -e "${NC}"

# ------------------------------------------------------------------
# Check Python version
# ------------------------------------------------------------------
info "Checking Python version..."
if command -v python3 &>/dev/null; then
    PY_CMD="python3"
elif command -v python &>/dev/null; then
    PY_CMD="python"
else
    error "Python 3 not found. Please install Python >= $PYTHON_MIN"
fi

PY_VERSION=$($PY_CMD --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    error "Python $PYTHON_MIN+ required. Found: $PY_VERSION"
fi
success "Python $PY_VERSION detected"

# ------------------------------------------------------------------
# Create installation directory
# ------------------------------------------------------------------
info "Creating installation directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# ------------------------------------------------------------------
# Install via pip
# ------------------------------------------------------------------
info "Installing NexusAgent..."

if [ "$NEXUS_VERSION" = "latest" ]; then
    $PY_CMD -m pip install --upgrade pip
    $PY_CMD -m pip install nexusagent
else
    $PY_CMD -m pip install "nexusagent==$NEXUS_VERSION"
fi

success "NexusAgent installed"

# ------------------------------------------------------------------
# Create default config
# ------------------------------------------------------------------
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    info "Creating default configuration..."
    mkdir -p "$INSTALL_DIR"
    cat > "$INSTALL_DIR/config.yaml" << 'EOF'
# NexusAgent Configuration
model:
  default_provider: "openai"
  providers:
    openai:
      model: "gpt-4o"

memory:
  enabled: true
  db_path: "~/.nexusagent/memory.db"

terminal:
  theme: "dark"
EOF
    success "Default config created at $INSTALL_DIR/config.yaml"
fi

# ------------------------------------------------------------------
# Verify installation
# ------------------------------------------------------------------
info "Verifying installation..."
if command -v nexus &>/dev/null; then
    success "nexus command available"
    nexus --version
else
    warn "nexus not in PATH. Try: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo ""
success "Installation complete!"
echo ""
echo "  Next steps:"
echo "    1. Set your API key:  export OPENAI_API_KEY='sk-...'"
echo "    2. Start chatting:    nexus chat"
echo "    3. Run setup wizard:  nexus setup"
echo ""
echo "  Documentation: https://github.com/nexusagent/nexusagent"
echo ""
