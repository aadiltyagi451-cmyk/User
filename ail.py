import os
import asyncio
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

api_id = 36180474
api_hash = "1f4ecc2133837a8a3c307f676cb95f88"

SOURCE = "@GmailFarmerBot"
API_URL = "https://worker-production-70084.up.railway.app"

SESSION_STRINGS = [
    os.getenv("SESSION1"),
    os.getenv("SESSION2"),
    os.getenv("SESSION3"),
    os.getenv("SESSION4"),
    os.getenv("SESSION5"),
    os.getenv("SESSION6"),
    os.getenv("SESSION7"),
    os.getenv("SESSION8"),
    os.getenv("SESSION9"),
    os.getenv("SESSION10"),
]

clients = []
task_queue = asyncio.Queue()

# 🔥 SAME TASK TRACK
USER_TASK_MSG = {}

# ---------------- CREATE CLIENTS ----------------
for s in SESSION_STRINGS:
    if s:
        clients.append(TelegramClient(StringSession(s), api_id, api_hash))

# ---------------- SMART CLICK ----------------
async def smart_click(msg, keyword):
    if msg.buttons:
        for row in msg.buttons:
            for btn in row:
                txt = (btn.text or "").lower()

                if keyword in txt or "✔" in txt or "✓" in txt:
                    await msg.click(text=btn.text)
                    return True
    return False

# ---------------- WAIT BUTTON ----------------
async def wait_for_button(client, keyword, msg_id, timeout=5):
    for _ in range(int(timeout / 0.1)):
        msg = await client.get_messages(SOURCE, ids=msg_id)
        if msg and msg.buttons:
            for row in msg.buttons:
                for btn in row:
                    txt = (btn.text or "").lower()
                    if keyword in txt or "✔" in txt or "✓" in txt:
                        return msg
        await asyncio.sleep(0.1)
    return None

# ---------------- FETCH TASK ----------------
async def fetch_task(client, user_id):

    print("🔥 FETCH TASK:", user_id)

    await client.send_message(SOURCE, "➕ Register a new account")
    await asyncio.sleep(0.5)

    msg = (await client.get_messages(SOURCE, limit=1))[0]
    msg_id = msg.id

    # 🔥 SAVE SAME MESSAGE
    USER_TASK_MSG[user_id] = msg_id

    msg = await wait_for_button(client, "done", msg_id)
    if not msg:
        print("❌ DONE not found")
        return

    await smart_click(msg, "done")

    msg = await wait_for_button(client, "complete", msg_id)
    if not msg:
        print("❌ COMPLETE not found")
        return

    await smart_click(msg, "complete")

    msg = await wait_for_button(client, "confirm", msg_id)
    if not msg:
        print("❌ CONFIRM not found")
        return

    await smart_click(msg, "confirm")

    await asyncio.sleep(0.3)

    final = await client.get_messages(SOURCE, ids=msg_id)

    print("✅ TASK GOT")

    try:
        requests.post(
            f"{API_URL}/task",
            json={
                "user_id": user_id,
                "task": final.text
            },
            timeout=5
        )
    except Exception as e:
        print("API ERROR:", e)

# ---------------- DONE ----------------
async def handle_done(client, user_id):

    print("🔥 DONE CHECK:", user_id)

    msg_id = USER_TASK_MSG.get(user_id)

    if not msg_id:
        print("❌ No stored msg_id")
        return

    msg = await client.get_messages(SOURCE, ids=msg_id)

    if not msg:
        print("❌ Message not found")
        return

    if not await smart_click(msg, "done"):
        print("❌ Done button not found")
        return

    print("✅ DONE CLICKED")

    for _ in range(20):
        await asyncio.sleep(0.5)

        updated = await client.get_messages(SOURCE, ids=msg_id)
        text = (updated.text or "").lower()

        print("CHECK:", text)

        if "how to logout" in text:
            requests.post(f"{API_URL}/result", json={
                "user_id": user_id,
                "status": "success"
            })
            return

        if "recovery email" in text:
            requests.post(f"{API_URL}/result", json={
                "user_id": user_id,
                "status": "fail"
            })
            return

# ---------------- WORKER ----------------
async def worker(client):

    await client.start()
    print("🔥 USERBOT READY")

    while True:
        job = await task_queue.get()

        try:
            if job["type"] == "fetch":
                await fetch_task(client, job["user"])

            elif job["type"] == "done":
                await handle_done(client, job["user"])

        except Exception as e:
            print("ERROR:", e)

        task_queue.task_done()

# ---------------- POLL API ----------------
async def poll_api():

    while True:
        try:
            res = requests.get(f"{API_URL}/get-task", timeout=5)
            data = res.json()

            if data.get("type") == "fetch":
                await task_queue.put(data)

            if data.get("type") == "done":
                await task_queue.put(data)

        except Exception as e:
            print("POLL ERROR:", e)

        await asyncio.sleep(0.5)

# ---------------- MAIN ----------------
async def main():

    for c in clients:
        asyncio.create_task(worker(c))

    asyncio.create_task(poll_api())

    print("🔥 FINAL USERBOT RUNNING")

    while True:
        await asyncio.sleep(1)

asyncio.run(main())
