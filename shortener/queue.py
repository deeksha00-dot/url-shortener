import os

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry


CLICK_STREAM = "shortener:clicks:stream"
CONSUMER_GROUP = "analytics-workers"
DEAD_LETTER_STREAM = "shortener:clicks:dead"


# If Redis is down we want to fail fast and fall back to the database, not
# make the visitor wait. Short timeouts, and NO retries: redis-py retries
# failed connections with exponential backoff by default, which made every
# call take about 3 seconds when Redis was down.
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
    socket_connect_timeout=1,
    socket_timeout=1,
    retry=Retry(NoBackoff(), 0),
)


def enqueue_click(url_id):

    event_id = queue_client.xadd(
        CLICK_STREAM,
        {
            "url_id": str(url_id)
        }
    )

    return event_id
