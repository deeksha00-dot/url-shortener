"""Automated tests for the URL shortener.

Most tests use an in-memory cache and a mocked click queue so they run
anywhere (no Redis needed). Two groups need no mocking of Redis itself:

* RedisDownTests   -> points the cache at a port where nothing listens, to
                      prove the app falls back to the database.
* RedisIntegration -> uses a real Redis server (skipped if none is running).

Run:  python manage.py test
"""

import time
from datetime import timedelta
from unittest import mock, skipUnless

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import ClickEvent, URL
from .queue import CLICK_STREAM, queue_client
from .services import create_short_url


LOCMEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Same options as config/settings.py, but pointing at a port where no Redis
# is listening.
DEAD_REDIS_CACHE = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:1/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 1,
            "SOCKET_TIMEOUT": 1,
            "CONNECTION_POOL_KWARGS": {"retry": Retry(NoBackoff(), 0)},
            "IGNORE_EXCEPTIONS": True,
        },
    }
}

PASSWORD = "S3cure-Pass-99"


@override_settings(CACHES=LOCMEM_CACHE)
class BaseTest(TestCase):
    """Creates a logged-in user and replaces the Redis Stream with a mock."""

    def setUp(self):
        cache.clear()

        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.token = Token.objects.create(user=self.user)

        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.token.key}"
        )

        patcher = mock.patch("shortener.services.enqueue_click")
        self.enqueue = patcher.start()
        self.addCleanup(patcher.stop)

    def make_url(self, code="abc123", original="https://example.com/page", **kw):
        return URL.objects.create(
            code=code, original_url=original, owner=self.user, **kw
        )

    def shorten(self, url, **extra):
        return self.client.post(
            "/api/shorten/", {"url": url, **extra}, format="json"
        )


# ----------------------------------------------------------------------
# A. Shortening + validation
# ----------------------------------------------------------------------

class ShortenTests(BaseTest):

    def test_creates_short_url(self):
        response = self.shorten("https://example.com/some/long/path?x=1")

        self.assertEqual(response.status_code, 201)

        short_url = response.json()["short_url"]
        code = short_url.rsplit("/", 1)[1]

        # Format required by the project: http://host/<code>  (no trailing /)
        self.assertEqual(short_url, f"http://testserver/{code}")
        self.assertEqual(len(code), 7)

        stored = URL.objects.get(code=code)
        self.assertEqual(stored.original_url, "https://example.com/some/long/path?x=1")
        self.assertEqual(stored.owner, self.user)
        self.assertEqual(stored.click_count, 0)

    def test_requires_login(self):
        response = APIClient().post(
            "/api/shorten/", {"url": "https://example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_rejects_empty_and_missing_url(self):
        self.assertEqual(self.shorten("").status_code, 400)
        self.assertEqual(
            self.client.post("/api/shorten/", {}, format="json").status_code, 400
        )

    def test_rejects_malformed_urls(self):
        for bad in ["not a url", "example.com", "http://", "https://", "http:/x"]:
            with self.subTest(url=bad):
                self.assertEqual(self.shorten(bad).status_code, 400)

    def test_rejects_unsafe_schemes(self):
        for bad in [
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:text/html,<script>alert(1)</script>",
            "ftp://example.com/file",
            "vbscript:msgbox(1)",
        ]:
            with self.subTest(url=bad):
                self.assertEqual(self.shorten(bad).status_code, 400)

        self.assertEqual(URL.objects.count(), 0)

    def test_rejects_overlong_url(self):
        self.assertEqual(
            self.shorten("https://example.com/" + "a" * 2100).status_code, 400
        )

    def test_generated_codes_are_unique(self):
        # Called through the service (not the API) because the API is
        # rate-limited to 10 creations per minute.
        codes = {
            create_short_url("https://example.com/").code
            for _ in range(500)
        }
        # Same long URL 500 times -> 500 different short codes
        self.assertEqual(len(codes), 500)
        self.assertEqual(URL.objects.count(), 500)

    def test_collision_retries_with_new_code(self):
        self.make_url(code="TAKEN01")

        with mock.patch(
            "shortener.services.generate_short_code",
            side_effect=["TAKEN01", "TAKEN01", "FRESH02"],
        ):
            response = self.shorten("https://example.com/new")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["short_url"].endswith("/FRESH02"))

    def test_gives_up_cleanly_when_every_code_collides(self):
        self.make_url(code="TAKEN01")

        with mock.patch(
            "shortener.services.generate_short_code", return_value="TAKEN01"
        ):
            response = self.shorten("https://example.com/new")

        self.assertEqual(response.status_code, 503)

    def test_custom_alias(self):
        response = self.shorten("https://example.com", custom_alias="my-link_1")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["short_url"], "http://testserver/my-link_1")

    def test_duplicate_alias_returns_409(self):
        self.shorten("https://example.com", custom_alias="dup")
        response = self.shorten("https://example.org", custom_alias="dup")
        self.assertEqual(response.status_code, 409)

    def test_invalid_and_reserved_aliases_rejected(self):
        for alias in ["has space", "semi;colon", "a/b", "x'--", "admin", "API", "app"]:
            with self.subTest(alias=alias):
                self.assertEqual(
                    self.shorten("https://example.com", custom_alias=alias).status_code,
                    400,
                )

    def test_expiry_in_the_past_rejected(self):
        past = (timezone.now() - timedelta(hours=1)).isoformat()
        self.assertEqual(
            self.shorten("https://example.com", expires_at=past).status_code, 400
        )

    def test_sql_injection_in_inputs_is_harmless(self):
        payload = "'; DROP TABLE shortener_url; --"
        self.assertEqual(
            self.shorten("https://example.com", custom_alias=payload).status_code, 400
        )
        self.assertEqual(self.client.get(f"/{payload}").status_code, 404)
        self.assertEqual(self.client.get("/api/urls/1 OR 1=1/").status_code, 404)
        self.assertEqual(URL.objects.count(), 0)  # table still there


# ----------------------------------------------------------------------
# B. Redirect + C. Redis cache
# ----------------------------------------------------------------------

class RedirectTests(BaseTest):

    def test_redirects_to_original_url(self):
        self.make_url()
        response = self.client.get("/abc123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com/page")

    def test_trailing_slash_form_also_works(self):
        self.make_url()
        self.assertEqual(self.client.get("/abc123/").status_code, 302)

    def test_unknown_code_is_404(self):
        self.assertEqual(self.client.get("/doesnotexist").status_code, 404)

    def test_weird_codes_are_404_not_500(self):
        for code in ["%00", "a%20b", "..%2f..%2fetc", "ü", "x" * 500]:
            with self.subTest(code=code):
                self.assertEqual(self.client.get(f"/{code}").status_code, 404)

    def test_only_get_and_head_allowed(self):
        self.make_url()
        self.assertEqual(self.client.post("/abc123").status_code, 405)

    def test_cache_miss_then_hit(self):
        self.make_url()

        first = self.client.get("/abc123")
        second = self.client.get("/abc123")

        self.assertEqual(first["X-Cache"], "MISS")
        self.assertEqual(second["X-Cache"], "HIT")
        self.assertEqual(second["Location"], "https://example.com/page")

    def test_cache_hit_does_not_query_the_database(self):
        self.make_url()
        self.client.get("/abc123")  # fills the cache

        with self.assertNumQueries(0):
            response = self.client.get("/abc123")

        self.assertEqual(response.status_code, 302)

    def test_cache_ttl_is_set(self):
        self.make_url()

        with mock.patch("shortener.views.cache.set") as cache_set:
            self.client.get("/abc123")

        self.assertEqual(cache_set.call_args.kwargs["timeout"], 300)

    def test_cache_ttl_never_outlives_url_expiry(self):
        self.make_url(expires_at=timezone.now() + timedelta(seconds=30))

        with mock.patch("shortener.views.cache.set") as cache_set:
            self.client.get("/abc123")

        self.assertLessEqual(cache_set.call_args.kwargs["timeout"], 30)

    def test_expired_url_returns_410(self):
        self.make_url(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.get("/abc123").status_code, 410)

    def test_url_that_expires_while_cached_returns_410(self):
        self.make_url(expires_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(self.client.get("/abc123").status_code, 302)  # cached

        # Pretend the expiry time has now passed
        cached = cache.get("url:abc123")
        cached["expires_at"] = timezone.now() - timedelta(seconds=1)
        cache.set("url:abc123", cached, timeout=60)

        self.assertEqual(self.client.get("/abc123").status_code, 410)
        self.assertIsNone(cache.get("url:abc123"))  # evicted

    def test_alias_equal_to_a_future_generated_code_no_longer_crashes(self):
        # Regression: the old code derived codes from the database ID, so a
        # custom alias such as "2" made the next auto-generated URL crash
        # with a 500 (UNIQUE constraint failed).
        self.shorten("https://example.com/1", custom_alias="2")
        for _ in range(3):
            self.assertEqual(self.shorten("https://example.com/x").status_code, 201)


# ----------------------------------------------------------------------
# D. Click analytics
# ----------------------------------------------------------------------

class ClickTests(BaseTest):

    def test_get_enqueues_one_click_event(self):
        url = self.make_url()
        self.client.get("/abc123")
        self.enqueue.assert_called_once_with(url.id)

    def test_head_request_is_not_counted(self):
        self.make_url()
        self.client.head("/abc123")
        self.enqueue.assert_not_called()

    def test_404_and_expired_are_not_counted(self):
        self.make_url(code="old", expires_at=timezone.now() - timedelta(days=1))
        self.client.get("/old")
        self.client.get("/missing")
        self.enqueue.assert_not_called()

    def test_click_goes_straight_to_database_when_queue_is_down(self):
        url = self.make_url()
        self.enqueue.side_effect = redis.exceptions.ConnectionError("down")

        for _ in range(3):
            self.assertEqual(self.client.get("/abc123").status_code, 302)

        url.refresh_from_db()
        self.assertEqual(url.click_count, 3)

    def test_worker_counts_events_and_ignores_duplicates(self):
        import worker  # the click-analytics consumer

        url = self.make_url()

        worker.process_event("1700000000000-0", {"url_id": str(url.id)})
        worker.process_event("1700000000001-0", {"url_id": str(url.id)})
        # Redis redelivers an event that was already processed
        worker.process_event("1700000000000-0", {"url_id": str(url.id)})

        url.refresh_from_db()
        self.assertEqual(url.click_count, 2)
        self.assertEqual(ClickEvent.objects.count(), 2)

    def test_worker_rejects_event_for_deleted_url(self):
        import worker

        with self.assertRaises(ValueError):
            worker.process_event("1700000000002-0", {"url_id": "999999"})

        # The failed transaction is rolled back, nothing is half-saved
        self.assertEqual(ClickEvent.objects.count(), 0)


# ----------------------------------------------------------------------
# E. Stats, listing and deleting
# ----------------------------------------------------------------------

class ManagementTests(BaseTest):

    def test_stats_endpoint(self):
        self.make_url(click_count=7)
        data = self.client.get("/api/urls/abc123/").json()

        self.assertEqual(data["code"], "abc123")
        self.assertEqual(data["original_url"], "https://example.com/page")
        self.assertEqual(data["click_count"], 7)
        self.assertIn("created_at", data)
        self.assertIn("expires_at", data)

    def test_list_returns_only_own_urls_newest_first(self):
        bob = User.objects.create_user("bob", password=PASSWORD)
        URL.objects.create(code="bobs", original_url="https://bob.example", owner=bob)
        self.make_url(code="first")
        self.make_url(code="second")

        data = self.client.get("/api/my-urls/").json()

        self.assertEqual([item["code"] for item in data], ["second", "first"])
        self.assertEqual(
            set(data[0]),
            {"code", "original_url", "click_count", "created_at", "expires_at"},
        )

    def test_cannot_see_or_delete_someone_elses_url(self):
        bob = User.objects.create_user("bob", password=PASSWORD)
        URL.objects.create(code="bobs", original_url="https://bob.example", owner=bob)

        self.assertEqual(self.client.get("/api/urls/bobs/").status_code, 404)
        self.assertEqual(self.client.delete("/api/urls/bobs/delete/").status_code, 404)
        self.assertTrue(URL.objects.filter(code="bobs").exists())

    def test_endpoints_require_login(self):
        anon = APIClient()
        self.make_url()
        self.assertEqual(anon.get("/api/my-urls/").status_code, 401)
        self.assertEqual(anon.get("/api/urls/abc123/").status_code, 401)
        self.assertEqual(anon.delete("/api/urls/abc123/delete/").status_code, 401)

    def test_deleted_url_stops_redirecting_even_when_cached(self):
        self.make_url()
        self.assertEqual(self.client.get("/abc123").status_code, 302)  # now cached

        response = self.client.delete("/api/urls/abc123/delete/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(URL.objects.filter(code="abc123").exists())
        self.assertEqual(self.client.get("/abc123").status_code, 404)


# ----------------------------------------------------------------------
# Accounts + rate limiting
# ----------------------------------------------------------------------

@override_settings(CACHES=LOCMEM_CACHE)
class AuthTests(TestCase):

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_register_then_login(self):
        response = self.client.post(
            "/api/register/",
            {"username": "newuser", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("token", response.json())

        login = self.client.post(
            "/api/login/",
            {"username": "newuser", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["token"], response.json()["token"])

    def test_register_rejects_weak_password_and_duplicates(self):
        weak = self.client.post(
            "/api/register/", {"username": "u1", "password": "12345678"}, format="json"
        )
        self.assertEqual(weak.status_code, 400)

        User.objects.create_user("taken", password=PASSWORD)
        duplicate = self.client.post(
            "/api/register/", {"username": "TAKEN", "password": PASSWORD}, format="json"
        )
        self.assertEqual(duplicate.status_code, 400)

    def test_bad_login(self):
        User.objects.create_user("alice", password=PASSWORD)
        response = self.client.post(
            "/api/login/", {"username": "alice", "password": "wrong"}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_login_is_rate_limited(self):
        statuses = [
            self.client.post(
                "/api/login/", {"username": "x", "password": "y"}, format="json"
            ).status_code
            for _ in range(7)
        ]
        self.assertEqual(statuses[:5], [401] * 5)
        self.assertEqual(statuses[5:], [429, 429])

    def test_shorten_is_rate_limited(self):
        user = User.objects.create_user("alice", password=PASSWORD)
        self.client.force_authenticate(user)

        with mock.patch("shortener.services.enqueue_click"):
            statuses = [
                self.client.post(
                    "/api/shorten/", {"url": "https://example.com"}, format="json"
                ).status_code
                for _ in range(12)
            ]
        self.assertEqual(statuses[:10], [201] * 10)
        self.assertEqual(statuses[10:], [429, 429])


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------

@override_settings(CACHES=LOCMEM_CACHE)
class HealthTests(TestCase):

    def test_ok(self):
        with mock.patch("shortener.views.queue_client.ping", return_value=True):
            response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"status": "ok", "database": "up", "redis": "up"}
        )

    def test_degraded_when_redis_is_down(self):
        with mock.patch(
            "shortener.views.queue_client.ping",
            side_effect=redis.exceptions.ConnectionError,
        ):
            response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["redis"], "down")


# ----------------------------------------------------------------------
# Redis unavailable: the whole app must keep working
# ----------------------------------------------------------------------

@override_settings(CACHES=DEAD_REDIS_CACHE)
class RedisDownTests(TestCase):
    """Cache points at a port with no Redis. Only the click queue is patched
    (to fail fast the same way a dead server would)."""

    def setUp(self):
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        patcher = mock.patch(
            "shortener.services.enqueue_click",
            side_effect=redis.exceptions.ConnectionError("down"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_full_flow_without_redis(self):
        created = self.client.post(
            "/api/shorten/", {"url": "https://example.com/x"}, format="json"
        )
        self.assertEqual(created.status_code, 201)  # rate limiter fails open

        code = created.json()["short_url"].rsplit("/", 1)[1]

        for _ in range(2):
            started = time.monotonic()
            response = self.client.get(f"/{code}")
            elapsed = time.monotonic() - started

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], "https://example.com/x")
            self.assertEqual(response["X-Cache"], "MISS")  # always the database

            # Regression: redis-py's default retries made this take ~4 seconds
            self.assertLess(elapsed, 1.0)

        self.assertEqual(URL.objects.get(code=code).click_count, 2)

        deleted = self.client.delete(f"/api/urls/{code}/delete/")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/{code}").status_code, 404)

    def test_login_works_without_redis(self):
        response = APIClient().post(
            "/api/login/", {"username": "alice", "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)


# ----------------------------------------------------------------------
# Real Redis (skipped automatically if no server is running)
# ----------------------------------------------------------------------

def redis_is_running():
    try:
        return bool(queue_client.ping())
    except redis.exceptions.RedisError:
        return False


@skipUnless(redis_is_running(), "needs a running Redis server")
class RedisIntegrationTests(TestCase):

    def setUp(self):
        queue_client.delete(CLICK_STREAM)
        self.addCleanup(queue_client.delete, CLICK_STREAM)

    def test_click_event_lands_in_the_redis_stream(self):
        user = User.objects.create_user("alice", password=PASSWORD)
        url = URL.objects.create(
            code="live1", original_url="https://example.com", owner=user
        )

        response = self.client.get("/live1")

        self.assertEqual(response.status_code, 302)
        events = queue_client.xrange(CLICK_STREAM)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1], {"url_id": str(url.id)})

        # No direct DB update on the normal path: the worker does that later
        url.refresh_from_db()
        self.assertEqual(url.click_count, 0)
