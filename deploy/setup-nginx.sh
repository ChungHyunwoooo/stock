#!/bin/bash
# Run with: sudo bash deploy/setup-nginx.sh
set -e

NGINX_CONF="/etc/nginx/sites-enabled/streamlit"

# Check if already patched
if grep -q "/stock/" "$NGINX_CONF" 2>/dev/null; then
    echo "TSE location blocks already exist in nginx config. Skipping."
else
    # Insert TSE blocks before the closing }
    sed -i '/^}$/i\
\
      # TSE - Trading Strategy Engine (Next.js frontend)\
      location /stock/ {\
          proxy_pass http://127.0.0.1:3000/stock/;\
          proxy_http_version 1.1;\
          proxy_set_header Host $host;\
          proxy_set_header X-Real-IP $remote_addr;\
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\
          proxy_set_header Upgrade $http_upgrade;\
          proxy_set_header Connection "upgrade";\
          proxy_buffering off;\
      }\
\
      # TSE - FastAPI backend\
      location /stock/api/ {\
          proxy_pass http://127.0.0.1:8001/api/;\
          proxy_http_version 1.1;\
          proxy_set_header Host $host;\
          proxy_set_header X-Real-IP $remote_addr;\
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\
          proxy_read_timeout 300;\
          proxy_buffering off;\
      }' "$NGINX_CONF"
    echo "TSE location blocks added to $NGINX_CONF"
fi

# Test and reload
nginx -t && systemctl reload nginx
echo "nginx reloaded. TSE available at http://hwchung.iptime.org/stock/"
