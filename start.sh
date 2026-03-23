#!/usr/bin/env bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}${BOLD}"
echo "  ⚡ AutoAgent — Autonomous AI Code Execution Agent"
echo -e "${NC}"

# ── Check prerequisites ────────────────────────────────────────────────
check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo -e "${RED}✗ $1 not found. $2${NC}"
    exit 1
  else
    echo -e "${GREEN}✓ $1 found: $(command -v $1)${NC}"
  fi
}

echo -e "\n${BOLD}Checking prerequisites...${NC}"
check_cmd python3   "Install Python 3.10+: https://python.org"
check_cmd git       "Install Git: https://git-scm.com"
check_cmd node      "Install Node.js 18+: https://nodejs.org"
check_cmd npm       "Install Node.js 18+: https://nodejs.org"

# ── Check Ollama ───────────────────────────────────────────────────────
echo -e "\n${BOLD}Checking Ollama...${NC}"
if command -v ollama &>/dev/null; then
  echo -e "${GREEN}✓ Ollama found${NC}"
  if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Ollama is running${NC}"
  else
    echo -e "${YELLOW}⚠ Starting Ollama daemon...${NC}"
    ollama serve &>/dev/null &
    sleep 3
    echo -e "${GREEN}✓ Ollama started${NC}"
  fi
else
  echo -e "${YELLOW}⚠ Ollama not found. Running in fallback mode (deterministic).${NC}"
  echo -e "  Install Ollama: https://ollama.com/download"
fi

# ── Backend ────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Setting up backend...${NC}"
cd "$(dirname "$0")/backend"

if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

echo "Installing backend dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Backend dependencies installed${NC}"

echo -e "\n${BOLD}Starting backend on port 8000...${NC}"
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
echo -e "${GREEN}✓ Backend started (PID: $BACKEND_PID)${NC}"
cd ..

# ── Frontend ───────────────────────────────────────────────────────────
echo -e "\n${BOLD}Setting up frontend...${NC}"
cd frontend

if [ ! -d "node_modules" ]; then
  echo "Installing frontend dependencies (this may take a moment)..."
  npm install --silent
fi

echo -e "${GREEN}✓ Frontend dependencies installed${NC}"
echo -e "\n${BOLD}Starting frontend on port 3000...${NC}"
npm start &
FRONTEND_PID=$!
cd ..

# ── Done ────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}✅ AutoAgent is running!${NC}"
echo -e "   Frontend: ${CYAN}http://localhost:3000${NC}"
echo -e "   Backend:  ${CYAN}http://localhost:8000${NC}"
echo -e "   API Docs: ${CYAN}http://localhost:8000/docs${NC}"
echo -e "\n   Press ${BOLD}Ctrl+C${NC} to stop all services\n"

# ── Cleanup on exit ─────────────────────────────────────────────────────
cleanup() {
  echo -e "\n${YELLOW}Shutting down...${NC}"
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
  echo -e "${GREEN}Done.${NC}"
}
trap cleanup SIGINT SIGTERM

wait
