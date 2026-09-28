import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from stock_watch_worker.manual.server import handler


class ServiceAuthorizationTests(unittest.TestCase):
    def response(self, token, body):
        with tempfile.TemporaryDirectory() as directory:
            cls = handler(Path(directory) / "manual.db")
            request = cls.__new__(cls)
            data = json.dumps(body).encode()
            request.headers = {
                "Authorization": "Bearer " + token,
                "Content-Length": str(len(data)),
            }
            request.path = "/preview"
            request.rfile = io.BytesIO(data)
            request.wfile = io.BytesIO()
            statuses = []
            request.send_response = statuses.append
            request.send_header = lambda *args: None
            request.end_headers = lambda: None
            manual = Mock()
            manual.preview.return_value = {"id": "draft"}
            with (
                patch.dict(
                    "os.environ",
                    {
                        "STOCK_WATCH_AUTOBOT_TOKEN": "a" * 32,
                        "STOCK_WATCH_BROWSER_SERVICE_TOKEN": "b" * 32,
                        "STOCK_WATCH_TELEGRAM_USER_ID": "user",
                        "STOCK_WATCH_TELEGRAM_CHAT_ID": "chat",
                    },
                ),
                patch("stock_watch_worker.manual.server.instance", return_value=manual),
            ):
                request.respond(True)
            return statuses[-1], manual

    def test_both_telegram_principals_and_scoped_token_required(self):
        body = {"user": "user", "chat": "chat", "command": {}, "request_id": "request"}
        for token, change, expected in [
            ("wrong", {}, 403),
            ("a" * 32, {"user": "other"}, 400),
            ("a" * 32, {"chat": "other"}, 400),
        ]:
            status, manual = self.response(token, {**body, **change})
            self.assertEqual(status, expected)
            manual.preview.assert_not_called()
        status, manual = self.response("a" * 32, body)
        self.assertEqual(status, 200)
        manual.preview.assert_called_once()

    def test_browser_principal_requires_distinct_browser_credential(self):
        body = {
            "user": "browser-operator",
            "chat": "browser",
            "command": {},
            "request_id": "request",
        }
        status, manual = self.response("a" * 32, body)
        self.assertEqual(status, 400)
        manual.preview.assert_not_called()
        status, manual = self.response("b" * 32, body)
        self.assertEqual(status, 200)
        manual.preview.assert_called_once()
