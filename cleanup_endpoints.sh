#!/bin/bash
# Clean up old debugpy endpoint files (older than 1 day)
find ~/.debugpy -name "debugpy-endpoints-*.json" -type f -mtime +1 -delete 2>/dev/null
echo "Cleaned up old endpoint files"
