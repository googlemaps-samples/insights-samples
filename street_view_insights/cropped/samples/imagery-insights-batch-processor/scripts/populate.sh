#!/bin/bash
set -e

# Get the directory of this script
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE}" )" &> /dev/null && pwd )

# Activate virtual environment from project root
source "$SCRIPT_DIR/../.venv/bin/activate"

# Run the populate script
python3 "$SCRIPT_DIR/../src/populate_with_cloud_run.py"