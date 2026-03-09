#!/bin/bash
# Run with: sudo bash deploy/fix-nginx-port.sh
set -e
sed -i 's|proxy_pass http://127.0.0.1:8000/api/|proxy_pass http://127.0.0.1:8001/api/|' /etc/nginx/sites-enabled/streamlit
nginx -t && systemctl reload nginx
echo "nginx updated: /stock/api/ now proxies to port 8001"
