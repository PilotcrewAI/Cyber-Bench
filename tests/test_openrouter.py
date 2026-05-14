import unittest
import urllib.request

from cyberbench.openrouter import OpenRouterClient


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class OpenRouterTests(unittest.TestCase):
    def test_non_json_response_raises_with_body_snippet(self) -> None:
        original_urlopen = urllib.request.urlopen

        def fake_urlopen(*args: object, **kwargs: object) -> _FakeResponse:
            return _FakeResponse(b"<html>not json</html>")

        urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
        try:
            client = OpenRouterClient("test-key")
            with self.assertRaisesRegex(RuntimeError, "non-JSON response"):
                client.chat_completion(model="test-model", messages=[])
        finally:
            urllib.request.urlopen = original_urlopen  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
