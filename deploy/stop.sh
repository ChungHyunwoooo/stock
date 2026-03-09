#!/bin/bash
# Stop TSE services
echo "Stopping TSE services..."
pkill -f "uvicorn api.main:app" 2>/dev/null && echo "  Backend stopped" || echo "  Backend not running"
pkill -f "next dev.*-p 3000" 2>/dev/null && echo "  Frontend stopped" || echo "  Frontend not running"
echo "Done."
