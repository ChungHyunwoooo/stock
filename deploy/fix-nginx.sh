#!/bin/bash
# Run with: sudo bash deploy/fix-nginx.sh
# Fixes: redirect loop, port 8001
set -e

CONF="/etc/nginx/sites-enabled/streamlit"

# Remove old TSE blocks if they exist
sed -i '/# TSE - Trading Strategy Engine/,/^      }/d' "$CONF"

# Insert new TSE blocks (no trailing slash on location to avoid redirect loop)
sed -i '/^}$/i\
\
      # TSE - Trading Strategy Engine (Next.js frontend)\
      location /stock {\
          proxy_pass http://127.0.0.1:3000;\
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
      }' "$CONF"

nginx -t && systemctl reload nginx
echo "nginx fixed: /stock → :3000, /stock/api/ → :8001"
