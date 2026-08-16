#!/usr/bin/env bash
# THE final command: one blessed path to the four submission workbooks.
#
#   ./run_final.sh              agent pipeline -> submission/ ; tier1 baseline -> baseline/
#   ./run_final.sh --fallback   BREAK-GLASS ONLY: tier1 seasonal-naive straight
#                               into submission/ (if the agent pipeline is down)
#   ./run_final.sh --with-tier2 also run David's tier2 LLM extraction diff first
#
# Everything (incl. commit hash + validation) tees into logs/final-run-<ts>.log
# — the required clear-run log. agent.run's own receipts log is also written.
#
# Approved by David 16 Aug: tier1 output moves to baseline/ in the default
# path so the two pipelines can never overwrite each other's submission files.
set -euo pipefail
cd "$(dirname "$0")"

STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="logs/final-run-${STAMP}.log"
mkdir -p logs baseline

{
  echo "=== Agents vs Wall Street — EXCALIBUR final run ${STAMP} ==="
  echo "commit: $(git rev-parse HEAD 2>/dev/null || echo 'not a git repo')"
  PY=./.venv/bin/python
  [[ -x "$PY" ]] || PY=python3

  if [[ "${1:-}" == "--with-tier2" ]]; then
    echo "--- tier2: LLM extraction diff (no merge) ---"
    "$PY" tier2/extract.py --diff || echo "tier2 diff failed (non-blocking)"
  fi

  if [[ "${1:-}" == "--fallback" ]]; then
    echo "--- FALLBACK MODE: tier1 seasonal-naive -> submission/ ---"
    "$PY" tier1/forecast.py
  else
    echo "--- tier1 baseline (seasonal-naive) -> baseline/ for comparison ---"
    if "$PY" tier1/forecast.py; then
      mv submission/*.xlsx baseline/ 2>/dev/null || true
      echo "baseline workbooks -> baseline/"
    else
      echo "tier1 baseline failed (non-blocking; agent pipeline is the product)"
    fi
    echo "--- agent pipeline (consensus-anchored ledger) -> submission/ ---"
    "$PY" -m agent.run
  fi

  echo "--- regenerate architecture page from receipts ---"
  "$PY" -m agent.build_html || echo "html generation failed (non-blocking)"

  echo "--- validation ---"
  npm run check:forecasts

  echo "=== done: submission/ ready — upload manually to openstocks.com ==="
} 2>&1 | tee "${LOG}"

echo
echo "Clear-run log saved: ${LOG}"
