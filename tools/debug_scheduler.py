from star_attendance.runtime import get_internal_api_client
import asyncio
import json

async def check():
    api = get_internal_api_client()
    status = await api.get_scheduler_status()
    print(json.dumps(status, indent=2))

if __name__ == "__main__":
    asyncio.run(check())
