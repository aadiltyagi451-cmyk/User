import os
import re
import asyncio
import time
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

# ================= CONFIG =================
api_id = 36180474
api_hash = "1f4ecc2133837a8a3c307f676cb95f88"

SOURCE = "@GmailFarmerBot"
API_URL = "https://worker-production-70084.up.railway.app"

SESSION_STRINGS = [
    os.getenv("SESSION1"),
    os.getenv("SESSION2"),
    os.getenv("SESSION3"),
]

clients = [TelegramClient(StringSession(s), api_id, api_hash) for s in SESSION_STRINGS if s]

if not clients:
    raise RuntimeError("No sessions loaded")

SESSION_LOCKS = [asyncio.Lock() for _ in clients]

task_queue = asyncio.Queue()
USER_TASK_STATE = {}
client_index = 0

# ================= HELPERS =================

def get_next_client():
    global client_index
    idx = client_index % len(clients)
    client_index += 1
    return idx, clients[idx]


def extract_task_id(text):
    m = re.search(r"Task ID:\s*`?([\w\-]+)`?", text)
    return m.group(1) if m else None


def post_task(user_id, text, task_id, msg_id):
    try:
        requests.post(f"{API_URL}/task", json={
            "user_id": user_id,
            "task": text,
            "task_id": task_id,
            "msg_id": msg_id
        }, timeout=30)
    except Exception as e:
        print("POST TASK ERROR:", e)


def post_result(user_id, success, task_id):
    try:
        requests.post(f"{API_URL}/result", json={
            "user_id": user_id,
            "task_id": task_id,
            "status": "success" if success else "fail"
        }, timeout=30)
    except Exception as e:
        print("POST RESULT ERROR:", e)


async def click_button(msg, keywords):
    if not msg.buttons:
        return False

    for row in msg.buttons:
        for btn in row:
            text = (btn.text or "").lower()
            for k in keywords:
                if k in text:
                    try:
                        await msg.click(text=btn.text)
                        return True
                    except:
                        pass
    return False


# ================= TASK FETCH =================

async def fetch_task(user_id):
    idx, client = get_next_client()

    async with SESSION_LOCKS[idx]:
        try:
            # 🔥 Step 1: send command
            await client.send_message(SOURCE, "➕ Register a new account")
            await asyncio.sleep(2)

            # 🔥 Step 2: get latest message safely
            msgs = await client.get_messages(SOURCE, limit=1)
            if not msgs:
                print("No message received")
                return

            msg = msgs[0]
            msg_id = msg.id

            await asyncio.sleep(2)

            # 🔥 Step 3: click buttons (if any)
            for step in [["done"], ["complete"], ["confirm"]]:
                msg = await client.get_messages(SOURCE, ids=msg_id)
                await click_button(msg, step)
                await asyncio.sleep(1)

            # 🔥 Step 4: final message fetch
            final = await client.get_messages(SOURCE, ids=msg_id)
            text = final.text or ""

            if not text:
                print("Empty task text")
                return

            # 🔥 UNIQUE task id fix
            task_id = extract_task_id(text) or f"{user_id}_{msg_id}_{int(time.time())}"

            USER_TASK_STATE[user_id] = {
                "msg_id": msg_id,
                "client": idx,
                "task_id": task_id,
                "retry": 0
            }

            print("TASK FETCHED:", task_id)

            post_task(user_id, text, task_id, msg_id)

        except Exception as e:
            print("FETCH ERROR:", e)


# ================= CONFIRM AGAIN =================

async def handle_confirm(user_id, job_msg_id=None):
    state = USER_TASK_STATE.get(user_id)
    if not state:
        return

    idx = state["client"]
    client = clients[idx]

    msg_id = job_msg_id or state["msg_id"]
    task_id = state["task_id"]

    async with SESSION_LOCKS[idx]:
        try:
            msg = await client.get_messages(SOURCE, ids=msg_id)

            if not await click_button(msg, ["done", "✓"]):
                await click_button(msg, ["check"])

            for _ in range(30):
                await asyncio.sleep(0.7)
                updated = await client.get_messages(SOURCE, ids=msg_id)
                text = (updated.text or "").lower()

                # ✅ SUCCESS
                if "how to logout" in text or "done" in text:
                    post_result(user_id, True, task_id)
                    return

                # ❌ FAIL
                if "not done" in text or "try again" in text:
                    state["retry"] += 1

                    if state["retry"] > 2:
                        post_result(user_id, False, task_id)
                        return

                    print("RETRYING...")

                    if await click_button(updated, ["retry", "again"]):
                        await asyncio.sleep(2)
                        return await handle_confirm(user_id, msg_id)

                    post_result(user_id, False, task_id)
                    return

        except Exception as e:
            print("CONFIRM ERROR:", e)


# ================= WORKER =================

async def worker():
    while True:
        job = await task_queue.get()
        try:
            if job["type"] == "fetch":
                await fetch_task(job["user"])

            elif job["type"] == "confirm":
                await handle_confirm(
                    job["user"],
                    job.get("msg_id")
                )

        except Exception as e:
            print("WORKER ERROR:", e)

        task_queue.task_done()


# ================= API POLL =================

async def poll_api():
    while True:
        try:
            r = requests.get(f"{API_URL}/get-task", timeout=30)
            data = r.json()

            if data:
                await task_queue.put(data)

        except Exception as e:
            print("API POLL ERROR:", e)

        await asyncio.sleep(1)


# ================= MAIN =================

async def main():
    for i, c in enumerate(clients):
        await c.start()
        print("CLIENT READY:", i)

    for _ in clients:
        asyncio.create_task(worker())

    asyncio.create_task(poll_api())

    while True:
        await asyncio.sleep(1)


asyncio.run(main())
