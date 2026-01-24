#!/bin/bash

# Start the application
echo "Building and starting Subnet Manager..."
docker-compose up -d

echo ""
echo "=================================="
echo "✅ Subnet Manager is running!"
echo "=================================="
echo ""
echo "🌐 Web Interface: http://localhost:5000"
echo "🗄️  Database: PostgreSQL (internal)"
echo ""
echo "📝 To view logs: docker-compose logs -f web"
echo "🛑 To stop: docker-compose down"
echo ""
