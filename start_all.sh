#!/bin/bash
# Start all three services for local testing.
# Usage: bash start_all.sh
# Stop: bash stop_all.sh

cd /home/digvijay/Digvijay/Verdikt/backend

# Kill anything still running
pkill -f "voice.agent" 2>/dev/null
pkill -f "uvicorn api.main" 2>/dev/null
pkill -f "vite" 2>/dev/null
sleep 2

# Clean up LiveKit rooms
set -a; source .env; set +a
python3 -c "
from livekit import api
from shared.config import get_settings
import asyncio
async def c():
    s = get_settings()
    lk = api.LiveKitAPI(url=s.livekit_url, api_key=s.livekit_api_key, api_secret=s.livekit_api_secret)
    resp = await lk.room.list_rooms(api.ListRoomsRequest())
    for r in resp.rooms:
        await lk.room.delete_room(api.DeleteRoomRequest(room=r.name))
    await lk.aclose()
asyncio.run(c())
" 2>/dev/null

# Start API
nohup bash -c 'set -a; source .env; set +a; uvicorn api.main:app --reload --port 8000' > /tmp/api.log 2>&1 &
echo "API:        PID $! → /tmp/api.log"

# Start voice worker
nohup bash -c 'set -a; source .env; set +a; python -m voice.agent dev' > /tmp/voice_worker.log 2>&1 &
echo "Worker:     PID $! → /tmp/voice_worker.log"

# Start frontend
cd /home/digvijay/Digvijay/Verdikt/frontend
nohup npx vite --port 5174 > /tmp/frontend.log 2>&1 &
echo "Frontend:   PID $! → /tmp/frontend.log"

sleep 5
echo ""
echo "=== STATUS ==="
echo "API:        $(curl -s http://localhost:8000/health 2>&1 || echo 'DOWN')"
grep -a "registered worker" /tmp/voice_worker.log | tail -1 | sed 's/.*registered/Worker:     registered/'
grep "Local:" /tmp/frontend.log | tail -1 | sed 's/.*Local:/Frontend:  /'
echo ""
echo "Generate a test token:"
echo "  cd backend && python3 scripts/test_ai_call.py"