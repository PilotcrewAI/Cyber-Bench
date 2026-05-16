#!/usr/bin/env bash
# Setup script for memory-vuln-bench
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== memory-vuln-bench setup ==="

# ── Prerequisites check ──────────────────────────────────────────────────────
check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "ERROR: '$1' not found. Please install it first." >&2
        exit 1
    fi
}

check_cmd docker
check_cmd python3

PYTHON_VERSION=$(python3 -c 'import sys; print(sys.version_info >= (3, 11))')
if [[ "$PYTHON_VERSION" != "True" ]]; then
    echo "ERROR: Python 3.11+ is required." >&2
    exit 1
fi

echo "✓ Docker found: $(docker --version)"
echo "✓ Python found: $(python3 --version)"

# ── .env check ───────────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
    cp .env.example .env
    echo ""
    echo "WARNING: .env created from template."
    echo "  Please edit .env and add your ANTHROPIC_API_KEY and HF_TOKEN before continuing."
    echo ""
fi

# ── Python dependencies ───────────────────────────────────────────────────────
echo ""
echo "Installing Python dependencies..."
pip3 install -r requirements.txt --quiet

# ── Results directories ───────────────────────────────────────────────────────
mkdir -p results/reports

# ── Pull Docker images ────────────────────────────────────────────────────────
echo ""
echo "Pulling ARVO Docker images (this may take a while)..."

ARVO_IDS=("1273" "1972" "1076" "2124")

for arvo_id in "${ARVO_IDS[@]}"; do
    for suffix in "vul" "fix"; do
        image="n132/arvo:${arvo_id}-${suffix}"
        echo "  Pulling $image ..."
        if docker pull "$image" --quiet 2>/dev/null; then
            echo "  ✓ $image"
        else
            echo "  ✗ $image — NOT AVAILABLE (will fail at runtime)"
        fi
    done
done

# ── Fetch task data from HuggingFace ─────────────────────────────────────────
echo ""
echo "Fetching task data from HuggingFace (requires HF_TOKEN)..."
python3 -c "
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
token = os.environ.get('HF_TOKEN', '')
if not token or token.startswith('hf_...'):
    print('  SKIP: HF_TOKEN not set — run manually: python -c \"from pipeline.fetch_tasks import fetch_all; fetch_all()\"')
    sys.exit(0)
from pipeline.fetch_tasks import fetch_all
fetch_all(token)
"

# ── Initialise DB ─────────────────────────────────────────────────────────────
echo ""
echo "Initialising SQLite database..."
python3 -c "
import sys; sys.path.insert(0, '.')
from pipeline.db import init_db
init_db()
print('  ✓ results/runs.db ready')
"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Ensure ANTHROPIC_API_KEY and HF_TOKEN are set in .env"
echo "  2. python scripts/run_pipeline.py --verify-gt"
echo "  3. python scripts/run_pipeline.py --all"
