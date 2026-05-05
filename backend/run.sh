#!/bin/bash
# Start 1x Dashboard on port 8001
cd "$(dirname "$0")"
echo "Starting 1x Dashboard on http://localhost:8001"
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
