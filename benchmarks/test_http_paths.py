import unittest

import httpx

from benchmarks.http_paths import fetch_gateway_presigned_once, shuffled_target_names


class AsyncBytes(httpx.AsyncByteStream):
    def __init__(self, content: bytes):
        self.content = content

    async def __aiter__(self):
        yield self.content


class GatewayPresignedBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_presign_url_before_object(self):
        calls: list[tuple[str, str]] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.raw_path.decode()))
            if request.method == "POST":
                self.assertEqual(request.headers["Authorization"], "Bearer test-token")
                return httpx.Response(
                    200,
                    json={"url": "https://storage.example/bench/object.bin"},
                )
            return httpx.Response(200, stream=AsyncBytes(b"benchmark"))

        transport = httpx.MockTransport(handle_request)
        async with httpx.AsyncClient(transport=transport) as client:
            sample = await fetch_gateway_presigned_once(
                client,
                "https://gateway.example",
                "bucket name",
                "bench/object.bin",
                "test-token",
                len(b"benchmark"),
            )

        self.assertEqual(
            calls,
            [
                ("POST", "/api/v1/buckets/bucket%20name/presign"),
                ("GET", "/bench/object.bin"),
            ],
        )
        self.assertIsNone(sample.error)
        self.assertEqual(sample.bytes_received, len(b"benchmark"))
        self.assertIsNotNone(sample.control_plane_ms)
        self.assertGreaterEqual(sample.total_ms, sample.control_plane_ms or 0)

    async def test_presign_failure_does_not_fetch_object(self):
        calls: list[str] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            calls.append(request.method)
            return httpx.Response(403, json={"detail": "forbidden"})

        transport = httpx.MockTransport(handle_request)
        async with httpx.AsyncClient(transport=transport) as client:
            sample = await fetch_gateway_presigned_once(
                client,
                "https://gateway.example",
                "bucket",
                "object.bin",
                "test-token",
                9,
            )

        self.assertEqual(calls, ["POST"])
        self.assertEqual(sample.status_code, 403)
        self.assertEqual(sample.error, "presign HTTP 403")
        self.assertEqual(sample.bytes_received, 0)


class TargetOrderingTests(unittest.TestCase):
    def test_seeded_order_is_reproducible_and_complete(self):
        targets = {"direct": "a", "gateway": "b", "external": "c"}

        first = shuffled_target_names(targets, seed=42)
        second = shuffled_target_names(targets, seed=42)

        self.assertEqual(first, second)
        self.assertEqual(set(first), set(targets))
        self.assertEqual(len(first), len(targets))


if __name__ == "__main__":
    unittest.main()