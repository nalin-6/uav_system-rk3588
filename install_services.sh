#!/bin/bash
# 安装 systemd 用户服务（树莓派5 conda环境）
set -e

REPO_ROOT="$HOME/uav_system-rk3588"
PYTHON="$HOME/miniconda3/envs/yolo/bin/python"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SYSTEMD_DIR"

# uav-yolo.service
cat > "$SYSTEMD_DIR/uav-yolo.service" << EOF
[Unit]
Description=UAV YOLO vision and MJPEG stream
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_ROOT
ExecStart=$PYTHON -u -m yolo_app.main --config config/yolo.yaml
Restart=on-failure
RestartSec=2
Environment=PATH=$HOME/miniconda3/envs/yolo/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
EOF

# uav-app.service
cat > "$SYSTEMD_DIR/uav-app.service" << EOF
[Unit]
Description=UAV control application and Web UI
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_ROOT
ExecStart=$PYTHON -u -m app.main --send-commands false
Restart=on-failure
RestartSec=2
Environment=PATH=$HOME/miniconda3/envs/yolo/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
EOF

echo "Service files created."

# Enable lingering for user (so services run without login)
loginctl enable-linger $(whoami) 2>/dev/null || true

# Reload and enable services
systemctl --user daemon-reload
systemctl --user enable uav-yolo.service uav-app.service
systemctl --user restart uav-yolo.service uav-app.service

sleep 2
echo ""
echo "=== Service Status ==="
systemctl --user status uav-yolo.service --no-pager || true
echo ""
systemctl --user status uav-app.service --no-pager || true
echo ""
echo "=== Done ==="
