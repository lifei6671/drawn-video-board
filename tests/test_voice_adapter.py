from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import tempfile
import threading
import unittest
import wave

from cs_board_video.adapters.voicestudio import synthesize, discover
from cs_board_video.cli import main
from cs_board_video.project import WorkflowError
from cs_board_video import workflow as w
from helpers import fixture, prepare_images


class VoiceAdapterTests(unittest.TestCase):
    def test_live_loopback_protocol_and_generated_voice_gate(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(48000)
            out.writeframes(b"\0\0" * 96000)
        wav = buffer.getvalue()
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                data = ({"paths": {"/speech": {"post": {}}, "/v1/models": {"get": {}}}}
                        if self.path == "/openapi.json" else {"data": [{"id": "test-local-model"}]})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            def do_POST(self):
                calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.end_headers()
                self.wfile.write(wav)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                p = prepare_images(fixture(temporary))
                p.save("audio/voice-config.json", {"base_url": f"http://127.0.0.1:{server.server_port}",
                    "endpoint": "/speech", "text_field": "text", "payload": {"model": "test-local-model"}})
                self.assertEqual(main(["audio", "synthesize", "--project", str(p.root)]), 0)
                from cs_board_video.project import Project
                p = Project(p.root)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["text"], p.path("narration/original.txt").read_text(encoding="utf-8"))
                self.assertEqual(w.status(p)["state"], "audio_review")
                with self.assertRaises(WorkflowError):
                    w.approval_target(p, "audio")
                self.assertFalse(p.approvals.get("audio"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_external_service_rejected(self):
        with self.assertRaises(WorkflowError):
            discover("https://example.com")
