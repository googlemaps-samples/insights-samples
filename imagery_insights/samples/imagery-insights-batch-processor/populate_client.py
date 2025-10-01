import json
import os
import sys
import requests
from config import (
    SERVICE_URL,
    BATCH_SIZE,
    STATE_FILE,
)


def get_state():
    """Reads the last processed offset and task_queue_id from the state file."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"offset": 0, "task_queue_id": None}


def save_state(offset, task_queue_id):
    """Saves the current offset and task_queue_id to the state file."""
    with open(STATE_FILE, "w") as f:
        json.dump({"offset": offset, "task_queue_id": task_queue_id}, f)


def populate_tasks(task_queue_id=None):
    """Loops through the BigQuery records in batches, creating tasks for each."""
    if not task_queue_id:
        print("task_queue_id not provided. Running /setup to create a new queue...")
        response = requests.post(f"{SERVICE_URL}/setup")
        if response.status_code != 200:
            print(f"Error: {response.text}")
            return
        task_queue_id = response.json().get("task_queue_id")
        print(f"Created new queue: {task_queue_id}")

    state = get_state()
    offset = state.get("offset", 0)

    while True:
        print(f"Processing batch with offset: {offset}")
        response = requests.post(
            f"{SERVICE_URL}/populate",
            json={"offset": offset, "task_queue_id": task_queue_id},
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 202:
            print(f"Error: {response.text}")
            break

        tasks_created = response.json().get("tasks_created", 0)
        if tasks_created == 0:
            print("No more tasks to create.")
            break

        print(f"Created {tasks_created} tasks.")
        offset += BATCH_SIZE
        save_state(offset, task_queue_id)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        populate_tasks(sys.argv)
    else:
        populate_tasks()