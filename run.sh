#!/bin/bash
set -e

echo "Starting Selenium Grid via Docker Compose..."
docker-compose up -d

echo "Waiting for Selenium Hub to be ready..."
# Wait up to 30 seconds for Selenium Hub
for i in {1..30}; do
    if curl -s http://localhost:4444/status | grep '"ready": true' > /dev/null; then
        echo "Selenium Hub is ready!"
        break
    fi
    sleep 1
done

echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo ""
echo "Setup complete! You can now run the stress test."
echo "For example:"
echo "./venv/bin/python main.py --url https://meet.jit.si --rooms 2 --users-per-room 3 --duration 60"
echo ""
echo "To scale chrome nodes, use:"
echo "docker-compose up -d --scale chrome=5"
