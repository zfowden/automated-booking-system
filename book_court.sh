#!/usr/bin/env bash

# Exit immediately if any command fails
# set -e

# Navigate to project directory (using forward slashes to avoid escaping issues in Git Bash)
cd "C:/Users/zackf/git_repositories/automated-booking-system"

# --- DYNAMIC DATE & INPUT VARIABLES ---
# Calculates the date exactly 6 days from today (YYYY-MM-DD)
DEFAULT_DATE=$(date -d "+6 days" +%Y-%m-%d)

# --- INPUT VARIABLES ---
# Syntax: ${1:-"default_value"} uses argument 1 if provided, otherwise falls back to default
TIME="${2:-"18:00"}"
DURATION="${3:-"60"}"

# Activate virtual environment if it exists
if [ -f ".venv/Scripts/activate" ]; then
    source ".venv/Scripts/activate"
fi


echo "Attempting booking for $DEFAULT_DATE at $TIME for $DURATION minutes..."

# Run the tool via uv
# uv run tennis-book book --date "$DEFAULT_DATE" --time "$TIME" --duration "$DURATION"
uv run tennis-book-job