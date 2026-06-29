"""Integration test: Agora Matrix wakeup bridge against real Dendrite on ARM.

Run: .venv/bin/python tests/integration/test_matrix_wakeup_live.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agora.coordinator import matrix_wakeup

# ARM Dendrite connection details
HOMESERVER = "http://10.0.0.25:8008"
ACCESS_TOKEN = "kYDKozzEjZn_OeUx0-0Y0D3Jau8MWl7qcnlyOOMR9DM"
ROOM_ID = "!ThjFu3Ngw9JvfbRZ:agora.local"
BOT_USER_ID = "@agora-bot:agora.local"

# Simulated agent Matrix user ID (we'll use the bot itself as target for testing)
AGENT_MATRIX_ID = "@agora-bot:agora.local"


async def test_configure_and_send():
    """Test: configure Matrix client and send a wakeup message."""
    print("1. Configuring Matrix wakeup client...")
    matrix_wakeup.configure_matrix(
        homeserver_url=HOMESERVER,
        access_token=ACCESS_TOKEN,
        room_id=ROOM_ID,
        bot_user_id=BOT_USER_ID,
    )
    print(f"   ✓ Configured: homeserver={HOMESERVER} room={ROOM_ID} bot={BOT_USER_ID}")

    print("2. Sending wakeup message...")
    result = await matrix_wakeup.send_wakeup_message(
        agent_matrix_id=AGENT_MATRIX_ID,
        agent_name="Test Agent",
        pending_count=3,
        pending_summary=[
            "📋 Task assigned: Implement auth module",
            "💬 Message from reviewer: Please fix the test",
            "🔄 Pipeline: review stage completed",
        ],
    )
    assert result, "send_wakeup_message returned False!"
    print("   ✓ Wakeup message sent successfully!")

    print("3. Verifying message arrived in room...")
    # Use raw HTTP to read back the message
    import urllib.request, json
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    url = f"{HOMESERVER}/_matrix/client/r0/rooms/{ROOM_ID}/messages?dir=b&limit=3"
    req = urllib.request.Request(url, headers=headers)
    resp = json.loads(urllib.request.urlopen(req).read())
    
    messages = []
    for chunk in resp.get("chunk", []):
        if chunk.get("type") == "m.room.message":
            body = chunk.get("content", {}).get("body", "")
            messages.append(body)
    
    assert any("Agora Wakeup" in m for m in messages), f"Wakeup message not found in: {messages}"
    print(f"   ✓ Message verified in room ({len(messages)} messages found)")
    print(f"   Last message preview: {messages[0][:100] if messages else 'N/A'}")

    print("\n4. Closing client...")
    await matrix_wakeup.close()
    print("   ✓ Client closed")

    print("\n✅ ALL TESTS PASSED — Matrix wakeup bridge is working!")


if __name__ == "__main__":
    asyncio.run(test_configure_and_send())
