import os
import re
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
for s in SESSION_STRINGS:
    if s:
        clients.append(TelegramClient(StringSession(s), api_id, api_hash))

if not clients:
    raise RuntimeError("No sessions loaded")

task_queue: asyncio.Queue = asyncio.Queue()

# user_id -> list of tasks in order
# each item = {"task_id": str, "msg_id": int, "client_index": int, "text": str, "created_at": int}
USER_TASK_STATE = {}

client_index = 0


def get_next_client_index() -> int:
    global client_index
    idx = client_index % len(clients)
    client_index += 1
    return idx


def extract_task_id(task_text: str) -> str | None:
    if not task_text:
        return None

    m = re.search(r"Task ID:\s*`?([A-Za-z0-9_\-]+)`?", task_text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.search(r"🆔\s*Task ID:\s*`?([A-Za-z0-9_\-]+)`?", task_text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return None


def ensure_user_bucket(user_id: int):
    if user_id not in USER_TASK_STATE:
        USER_TASK_STATE[user_id] = []


def add_task_state(user_id: int, task_id: str, msg_id: int, client_index_value: int, text: str):
    ensure_user_bucket(user_id)

    # duplicate task_id skip
    for item in USER_TASK_STATE[user_id]:
        if item["task_id"] == task_id:
            return

    USER_TASK_STATE[user_id].append({
        "task_id": task_id,
        "msg_id": msg_id,
        "client_index": client_index_value,
        "text": text,
        "created_at": int(asyncio.get_event_loop().time()),
    })

    # safety cap
    if len(USER_TASK_STATE[user_id]) > 10:
        USER_TASK_STATE[user_id] = USER_TASK_STATE[user_id][-10:]


def get_task_state(user_id: int, task_id: str | None = None):
    tasks = USER_TASK_STATE.get(user_id, [])
    if not tasks:
        return None

    if task_id:
        for item in tasks:
            if item["task_id"] == task_id:
                return item
        return None

    # fallback oldest task
    return tasks[0]


def remove_task_state(user_id: int, task_id: str | None = None):
    tasks = USER_TASK_STATE.get(user_id, [])
    if not tasks:
        return

    if task_id:
        USER_TASK_STATE[user_id] = [t for t in tasks if t["task_id"] != task_id]
    else:
        USER_TASK_STATE[user_id] = tasks[1:]

    if not USER_TASK_STATE[user_id]:
        USER_TASK_STATE.pop(user_id, None)


async def smart_click(msg, keyword: str) -> bool:
    if not msg or not msg.buttons:
        return False

    keyword = keyword.lower().strip()

    for row in msg.buttons:
        for btn in row:
            txt = (btn.text or "").lower().strip()

            if keyword == "done":
                if "done" in txt or "✔" in txt or "✓" in txt:
                    await msg.click(text=btn.text)
                    return True

            elif keyword == "complete":
                if "complete" in txt:
                    await msg.click(text=btn.text)
                    return True

            elif keyword == "confirm":
                if "confirm" in txt or "click again" in txt:
                    await msg.click(text=btn.text)
                    return True

    return False


async def wait_for_button(client: TelegramClient, msg_id: int, keyword: str, timeout: float = 8.0):
    steps = int(timeout / 0.2)
    for _ in range(steps):
        msg = await client.get_messages(SOURCE, ids=msg_id)
        if msg and msg.buttons:
            for row in msg.buttons:
                for btn in row:
                    txt = (btn.text or "").lower().strip()

                    if keyword == "done" and ("done" in txt or "✔" in txt or "✓" in txt):
                        return msg
                    if keyword == "complete" and "complete" in txt:
                        return msg
                    if keyword == "confirm" and ("confirm" in txt or "click again" in txt):
                        return msg

        await asyncio.sleep(0.2)

    return None


def post_result(user_id: int, success: bool, task_id: str | None = None):
    payload = {
        "user_id": user_id,
        "status": "success" if success else "fail",
    }
    if task_id:
        payload["task_id"] = task_id

    try:
        r = requests.post(
            f"{API_URL}/result",
            json=payload,
            timeout=10,
        )
        print("RESULT POST:", r.status_code, user_id, success, task_id)
    except Exception as e:
        print("RESULT POST ERROR:", e)


def post_task(user_id: int, task_text: str, task_id: str | None = None):
    payload = {
        "user_id": user_id,
        "task": task_text,
    }
    if task_id:
        payload["task_id"] = task_id

    try:
        r = requests.post(
            f"{API_URL}/task",
            json=payload,
            timeout=15,
        )
        print("TASK POST:", r.status_code, user_id, task_id)
    except Exception as e:
        print("TASK POST ERROR:", e)


async def fetch_task(user_id: int):
    idx = get_next_client_index()
    client = clients[idx]

    print("FETCH TASK:", user_id, "client:", idx)

    await client.send_message(SOURCE, "➕ Register a new account")
    await asyncio.sleep(0.6)

    msg = (await client.get_messages(SOURCE, limit=1))[0]
    msg_id = msg.id

    msg = await wait_for_button(client, msg_id, "done")
    if not msg:
        print("DONE not found in fetch flow")
        return

    await smart_click(msg, "done")

    msg = await wait_for_button(client, msg_id, "complete")
    if not msg:
        print("COMPLETE not found")
        return

    await smart_click(msg, "complete")

    msg = await wait_for_button(client, msg_id, "confirm")
    if not msg:
        print("CONFIRM not found")
        return

    await smart_click(msg, "confirm")
    await asyncio.sleep(0.5)

    final = await client.get_messages(SOURCE, ids=msg_id)
    if not final or not (final.text or "").strip():
        print("FINAL TASK EMPTY")
        return

    task_text = final.text
    task_id = extract_task_id(task_text)

    if not task_id:
        # fallback unique id if bot text lacks Task ID
        task_id = f"{user_id}_{msg_id}"

    add_task_state(user_id, task_id, msg_id, idx, task_text)

    print("TASK GOT:", user_id, "msg:", msg_id, "task_id:", task_id)
    post_task(user_id, task_text, task_id)


async def handle_done(user_id: int, task_id: str | None = None):
    state = get_task_state(user_id, task_id)
    if not state:
        print("NO TASK STATE FOR USER:", user_id, "task_id:", task_id)
        return

    msg_id = state["msg_id"]
    idx = state["client_index"]
    real_task_id = state["task_id"]
    client = clients[idx]

    print("DONE CHECK:", user_id, "client:", idx, "msg:", msg_id, "task_id:", real_task_id)

    msg = await client.get_messages(SOURCE, ids=msg_id)
    if not msg:
        print("MESSAGE NOT FOUND")
        return

    if not await smart_click(msg, "done"):
        print("Done button not found")
        return

    print("DONE CLICKED")

    for _ in range(30):
        await asyncio.sleep(0.4)
        updated = await client.get_messages(SOURCE, ids=msg_id)
        text = (updated.text or "").lower()

        print("CHECK:", text[:160])

        if "how to logout" in text:
            post_result(user_id, True, real_task_id)
            remove_task_state(user_id, real_task_id)
            return

        if "recovery email" in text or "haven't added recovery email" in text:
            post_result(user_id, False, real_task_id)
            return

    print("NO UPDATE DETECTED")


async def worker():
    while True:
        job = await task_queue.get()
        try:
            jtype = job.get("type")
            user_id = int(job.get("user"))
            task_id = job.get("task_id")

            if jtype == "fetch":
                await fetch_task(user_id)
            elif jtype == "done":
                await handle_done(user_id, task_id)
            else:
                print("UNKNOWN JOB:", job)

        except Exception as e:
            print("WORKER ERROR:", e)

        task_queue.task_done()


async def poll_api():
    while True:
        try:
            r = requests.get(f"{API_URL}/get-task", timeout=15)
            data = r.json()

            if data and data.get("type") in ("fetch", "done") and data.get("user"):
                job = {
                    "type": data["type"],
                    "user": int(data["user"]),
                }

                if data.get("task_id"):
                    job["task_id"] = str(data["task_id"])

                await task_queue.put(job)
                print("JOB RECEIVED:", job)

        except Exception as e:
            print("POLL ERROR:", e)

        await asyncio.sleep(0.5)


async def main():
    for i, client in enumerate(clients):
        await client.start()
        print("USERBOT READY:", i)

    for _ in range(min(5, len(clients))):
        asyncio.create_task(worker())

    asyncio.create_task(poll_api())

    print("FINAL USERBOT RUNNING")

    while True:
        await asyncio.sleep(1)


asyncio.run(main())
