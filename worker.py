import os
import socket

import django
import redis

from django.db import transaction
from django.db.models import F


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings"
)

django.setup()

from shortener.models import ClickEvent, URL
from shortener.queue import (
    CLICK_STREAM,
    CONSUMER_GROUP,
    DEAD_LETTER_STREAM,
)


redis_client = redis.Redis(
    host=os.getenv(
        "REDIS_HOST",
        "127.0.0.1"
    ),
    port=int(
        os.getenv(
            "REDIS_PORT",
            "6379"
        )
    ),
    db=0,
    decode_responses=True,
)


CONSUMER_NAME = (
    f"{socket.gethostname()}-{os.getpid()}"
)

MIN_IDLE_TIME_MS = 10_000
MAX_RETRIES = 3


def ensure_consumer_group():
    try:
        redis_client.xgroup_create(
            CLICK_STREAM,
            CONSUMER_GROUP,
            id="0-0",
            mkstream=True
        )

        print(
            f"Created consumer group: {CONSUMER_GROUP}"
        )

    except redis.exceptions.ResponseError as error:
        if "BUSYGROUP" not in str(error):
            raise


def retry_key(message_id):
    return f"shortener:clicks:retry:{message_id}"


def process_event(message_id, data):
    url_id = int(data["url_id"])

    with transaction.atomic():
        event, created = ClickEvent.objects.get_or_create(
            event_id=message_id,
            defaults={
                "url_id": url_id
            }
        )

        if created:
            updated = URL.objects.filter(
                id=url_id
            ).update(
                click_count=F("click_count") + 1
            )

            if updated == 0:
                raise ValueError(
                    f"URL id={url_id} does not exist."
                )

            print(
                f"Processed click event {message_id} "
                f"for URL id={url_id}"
            )

        else:
            print(
                f"Duplicate event ignored: {message_id}"
            )


def send_to_dead_letter_queue(
    message_id,
    data,
    error
):
    redis_client.xadd(
        DEAD_LETTER_STREAM,
        {
            "event_id": message_id,
            "url_id": str(data.get("url_id", "")),
            "error": str(error)
        }
    )

    print(
        f"Moved event {message_id} "
        f"to dead-letter queue."
    )


def acknowledge_success(message_id):
    redis_client.xack(
        CLICK_STREAM,
        CONSUMER_GROUP,
        message_id
    )

    redis_client.delete(
        retry_key(message_id)
    )


def handle_message(message_id, data):
    try:
        process_event(
            message_id,
            data
        )

        acknowledge_success(message_id)

    except Exception as error:
        attempts = redis_client.incr(
            retry_key(message_id)
        )

        print(
            f"Failed event {message_id}. "
            f"Attempt {attempts}/{MAX_RETRIES}. "
            f"Error: {error}"
        )

        if attempts >= MAX_RETRIES:
            send_to_dead_letter_queue(
                message_id,
                data,
                error
            )

            redis_client.xack(
                CLICK_STREAM,
                CONSUMER_GROUP,
                message_id
            )

            redis_client.delete(
                retry_key(message_id)
            )


def recover_stale_messages():
    result = redis_client.xautoclaim(
        CLICK_STREAM,
        CONSUMER_GROUP,
        CONSUMER_NAME,
        MIN_IDLE_TIME_MS,
        "0-0",
        count=10
    )

    claimed_messages = result[1]

    for message_id, data in claimed_messages:
        print(
            f"Recovered stale event: {message_id}"
        )

        handle_message(
            message_id,
            data
        )


ensure_consumer_group()

print("Click analytics worker started...")
print(f"Stream: {CLICK_STREAM}")
print(f"Group: {CONSUMER_GROUP}")
print(f"Consumer: {CONSUMER_NAME}")


while True:

    # Recover messages abandoned by failed workers
    recover_stale_messages()

    messages = redis_client.xreadgroup(
        groupname=CONSUMER_GROUP,
        consumername=CONSUMER_NAME,
        streams={
            CLICK_STREAM: ">"
        },
        count=10,
        block=5000
    )

    if not messages:
        continue

    for stream_name, entries in messages:

        for message_id, data in entries:

            handle_message(
                message_id,
                data
            )