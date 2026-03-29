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
for s in SESSION_STRINGS:
    if s:
        clients.append(TelegramClient(StringSession(s), api_id, api_hash))

if not clients:
    raise RuntimeError("No sessions loaded")

task_queue: asyncio.Queue = asyncio.Queue()

# user_id -> {"msg_id": int, "client_index": int}
USER_TASK_STATE = {}
client_index = 0


def get_next_client_index() -> int:
    global client_index
    idx = client_index % len(clients)
    client_index += 1
    return idx


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


def post_result(user_id: int, success: bool):
    try:
        r = requests.post(
            f"{API_URL}/result",
            json={
                "user_id": user_id,
                "status": "success" if success else "fail",
            },
            timeout=10,
        )
        print("RESULT POST:", r.status_code, user_id, success)
    except Exception as e:
        print("RESULT POST ERROR:", e)


def post_task(user_id: int, task_text: str):
    try:
        r = requests.post(
            f"{API_URL}/task",
            json={
                "user_id": user_id,
                "task": task_text,
            },
            timeout=15,
        )
        print("TASK POST:", r.status_code, user_id)
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

    USER_TASK_STATE[user_id] = {
        "msg_id": msg_id,
        "client_index": idx,
    }

    print("TASK GOT:", user_id, "msg:", msg_id)
    post_task(user_id, final.text)


async def handle_done(user_id: int):
    state = USER_TASK_STATE.get(user_id)
    if not state:
        print("NO TASK STATE FOR USER:", user_id)
        return

    msg_id = state["msg_id"]
    idx = state["client_index"]
    client = clients[idx]

    print("DONE CHECK:", user_id, "client:", idx, "msg:", msg_id)

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

        print("CHECK:", text[:120])

        if "how to logout" in text:
            post_result(user_id, True)
            return

        if "recovery email" in text or "haven't added recovery email" in text:
            post_result(user_id, False)
            return

    print("NO UPDATE DETECTED")


async def worker():
    while True:
        job = await task_queue.get()
        try:
            jtype = job.get("type")
            user_id = int(job.get("user"))

            if jtype == "fetch":
                await fetch_task(user_id)
            elif jtype == "done":
                await handle_done(user_id)
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
                await task_queue.put({
                    "type": data["type"],
                    "user": int(data["user"]),
                })
                print("JOB RECEIVED:", data)

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
