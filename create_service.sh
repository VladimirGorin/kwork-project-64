#!/bin/bash

CURRENT_DIR=$(pwd)

SERVICE_NAME=$(basename "$CURRENT_DIR")

cat <<EOF > /etc/systemd/system/$SERVICE_NAME.service
[Unit]
Description=$SERVICE_NAME
[Service]
Type=simple
ExecStart=$CURRENT_DIR/venv/bin/python $CURRENT_DIR/main.py
WorkingDirectory=$CURRENT_DIR
Restart=always
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

systemctl enable $SERVICE_NAME
systemctl start $SERVICE_NAME

echo "Service $SERVICE_NAME is running!"
