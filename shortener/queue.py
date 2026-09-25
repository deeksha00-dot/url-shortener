import os

import redis


CLICK_STREAM = "shortener:clicks:stream"
CONSUMER_GROUP = "analytics-workers"
DEAD_LETTER_STREAM = "shortener:clicks:dead"


queue_client = redis.Redis(
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


def enqueue_click(url_id):

    event_id = queue_client.xadd(
        CLICK_STREAM,
        {
            "url_id": str(url_id)
        }
    )

    return event_id