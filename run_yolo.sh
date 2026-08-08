#!/bin/bash
# YOLO App 启动脚本 (树莓派5 conda环境)
set -e

# 使用conda环境的python
PYTHON=~/miniconda3/envs/yolo/bin/python

# 进入项目目录
cd ~/uav_system-rk3588

echo "=== YOLO App (Raspberry Pi 5 + conda) ==="
echo "Python: $PYTHON"
$PYTHON --version
echo "Config: config/yolo.yaml"
echo "Model: $(grep model_path config/yolo.yaml)"
echo "Source: $(grep ^source config/yolo.yaml)"
echo "=========================================="

# 运行yolo_app
exec $PYTHON -m yolo_app.main --config config/yolo.yaml
