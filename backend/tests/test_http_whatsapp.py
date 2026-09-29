"""HTTP disconnect handling and the OpenWA adapter. Does not start or call a real OpenWA."""

import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["AIPF_ENV"] = "development"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aipf import notify
from aipf.core import config_set
from aipf.db import Tx, apply_migrations, connect
from aipf.notify import OpenWAProvider, confirmed_message_id, openwa_api_root
from aipf.server import Handler, HospitalServer, client_disconnected, match
from aipf.util import now_iso

SESSION = "11111111-1111-1111-1111-111111111111"
API_KEY = "test-key-do-not-log"
PHONE = "9811122334"


class AbortSocket:
    def __init__(self, request: bytes, exc: BaseException):
        self.request = request
        self.exc = exc
        self.sends = 0

    def makefile(self, mode="rb", *args, **kwargs):
        return io.BytesIO(self.request)

    def sendall(self, data):
        self.sends += 1
        raise self.exc

    def close(self):
        return None

    def settimeout(self, timeout):
        return None

    def setsockopt(self, *args):
        return None


class FakeOpenWA(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        self.server.hits.append(self._hit(b""))
        self._serve()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.hits.append(self._hit(body))
        self._serve()

    def _hit(self, body: bytes) -> dict:
        return {
            "method": self.command,
            "path": self.path,
            "body": body,
            "api_key": self.headers.get("X-API-Key"),
            "authorization": self.headers.get("Authorization"),
            "session_header": self.headers.get("X-Session-Id"),
        }

    def _serve(self):
        mode = self.server.mode
        if mode == "timeout":
            time.sleep(self.server.hang)
            return
        if mode == "auth_fail":
            if self.path.endswith("/health"):
                self._send(200, {"status": "ok", "timestamp": "2026-09-28T00:00:00Z"})
                return
            self._send(401, {"message": f"bad key {self.headers.get('X-API-Key') or ''}"})
            return
        if mode == "ready":
            if self.path.endswith("/health"):
                self._send(200, {"status": "ok", "timestamp": "2026-09-28T00:00:00Z"})
                return
            self._send(200, {"id": SESSION, "name": "desk", "status": "ready", "phone": "919999999999"})
            return
        if mode == "401":
            self._send(401, {"message": f"bad key {self.headers.get('X-API-Key') or ''}"})
            return
        if mode == "404":
            self._send(404, {"message": "missing"})
            return
        if mode == "409":
            self._send(409, {"message": "Session is not ready"})
            return
        if mode == "success":
            self._send(201, {"messageId": "true_919811122334@c.us_ABC", "timestamp": 1706868000})
            return
        if mode == "decoy":
            self._send(200, {"success": True, "id": "not-a-confirmation", "key": "also-not"})
            return
        self._send(500, {"message": "unhandled test mode"})

    def _send(self, code: int, payload: dict):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class FakeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), FakeOpenWA)
        self.mode = "404"
        self.hits = []
        self.hang = 1.2


def _request_bytes(path="/api/public/branding") -> bytes:
    return f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode()


def _temp_db():
    folder = Path(tempfile.mkdtemp(prefix="aipf-wa-"))
    path = folder / "hospital.db"
    conn = connect(path)
    apply_migrations(conn)
    conn.path = path
    return conn


def _use_db(conn):
    previous = os.environ.get("AIPF_DATABASE_URL")
    os.environ["AIPF_DATABASE_URL"] = "sqlite:///" + str(conn.path)
    return previous


def _restore_db(previous):
    if previous is None:
        os.environ.pop("AIPF_DATABASE_URL", None)
    else:
        os.environ["AIPF_DATABASE_URL"] = previous


def _drive(conn, exc=None, branding=None):
    previous = _use_db(conn)
    old_branding = notify  # keep a local name so the patch target is explicit
    del old_branding
    import aipf.server as server_mod

    original = server_mod.core.public_branding
    if branding is not None:
        server_mod.core.public_branding = branding
    sock = AbortSocket(_request_bytes(), exc or ConnectionAbortedError(10053, "aborted"))
    handler = Handler.__new__(Handler)
    handler.request = sock
    handler.client_address = ("127.0.0.1", 9)
    handler.server = HospitalServer(("127.0.0.1", 0), Handler)
    captured = io.StringIO()
    old_err = sys.stderr
    sys.stderr = captured
    try:
        handler.setup()
        handler.handle_one_request()
    finally:
        sys.stderr = old_err
        server_mod.core.public_branding = original
        _restore_db(previous)
        handler.server.server_close()
    return sock, captured.getvalue()


def test_client_disconnect_errors_are_not_application_failures():
    assert client_disconnected(ConnectionAbortedError(10053, "aborted"))
    assert client_disconnected(ConnectionResetError(10054, "reset"))
    assert client_disconnected(BrokenPipeError())
    aborted = OSError("aborted")
    aborted.winerror = 10053
    reset = OSError("reset")
    reset.winerror = 10054
    pipe = OSError("pipe")
    pipe.errno = 32
    assert client_disconnected(aborted)
    assert client_disconnected(reset)
    assert client_disconnected(pipe)
    assert not client_disconnected(ConnectionRefusedError())
    assert not client_disconnected(TimeoutError())
    assert not client_disconnected(RuntimeError("disk full"))


def test_disconnect_during_response_has_no_secondary_traceback():
    conn = _temp_db()
    try:
        for exc in (ConnectionAbortedError(10053, "aborted"), BrokenPipeError(), ConnectionResetError()):
            sock, logged = _drive(conn, exc)
            assert sock.sends == 1
            assert "Traceback" not in logged
            assert "During handling" not in logged
        win = OSError("An established connection was aborted by the software in your host machine")
        win.winerror = 10053
        sock, logged = _drive(conn, win)
        assert sock.sends == 1
        assert "Traceback" not in logged
    finally:
        conn.close()


def test_application_exception_is_logged_before_the_response_and_survives_disconnect():
    conn = _temp_db()
    secret = "password=s3cret postgresql://user:pass@db/hospital api_key=sekret"

    def boom(_conn):
        raise RuntimeError(f"disk full {secret}")

    try:
        sock, logged = _drive(conn, ConnectionAbortedError(10053, "aborted"), boom)
    finally:
        conn.close()
    assert sock.sends == 1
    assert logged.count("Traceback") == 1
    assert "During handling" not in logged
    assert "RuntimeError" in logged
    assert "disk full" in logged
    assert "s3cret" not in logged
    assert "sekret" not in logged
    assert "postgresql://" not in logged
    assert "password=[redacted]" in logged


def test_server_stays_up_after_exception_and_client_abort():
    conn = _temp_db()
    previous = _use_db(conn)
    import aipf.server as server_mod

    original = server_mod.core.public_branding
    httpd = HospitalServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + "/api/public/branding", timeout=5) as res:
            body = json.loads(res.read().decode())
            assert res.status == 200
            assert body["ok"] is True

        def boom(_conn):
            raise RuntimeError("disk full on branding lookup password=s3cret")

        server_mod.core.public_branding = boom
        captured = io.StringIO()
        old_err = sys.stderr
        sys.stderr = captured
        try:
            urllib.request.urlopen(base + "/api/public/branding", timeout=5)
            raise AssertionError("application exception was not reported")
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode()
            assert exc.code == 500
            assert "s3cret" not in payload
            assert "disk full" not in payload
        finally:
            sys.stderr = old_err
            server_mod.core.public_branding = original
        logged = captured.getvalue()
        assert logged.count("Traceback") == 1
        assert "RuntimeError" in logged
        assert "disk full on branding lookup" in logged
        assert "s3cret" not in logged

        with urllib.request.urlopen(base + "/api/public/accounts", timeout=5) as res:
            assert res.status == 200
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        sock.sendall(_request_bytes("/api/public/accounts"))
        sock.close()
        time.sleep(0.2)
        with urllib.request.urlopen(base + "/api/public/branding", timeout=5) as res:
            assert res.status == 200
        assert thread.is_alive()
    finally:
        server_mod.core.public_branding = original
        httpd.shutdown()
        httpd.server_close()
        _restore_db(previous)
        conn.close()


def test_openwa_root_is_not_doubled():
    assert openwa_api_root("http://openwa-host:2785") == "http://openwa-host:2785/api"
    assert openwa_api_root("http://openwa-host:2785/") == "http://openwa-host:2785/api"
    assert openwa_api_root("http://openwa-host:2785/api") == "http://openwa-host:2785/api"
    assert openwa_api_root("http://openwa-host:2785/api/") == "http://openwa-host:2785/api"
    assert openwa_api_root("https://wa.example.com/api") == "https://wa.example.com/api"


def _provider(server: FakeServer, base_suffix="") -> OpenWAProvider:
    port = server.server_address[1]
    return OpenWAProvider(f"http://127.0.0.1:{port}{base_suffix}", API_KEY, SESSION)


def _posts(server: FakeServer) -> list[dict]:
    return [hit for hit in server.hits if hit["method"] == "POST"]


def test_provider_uses_documented_send_and_never_falls_back():
    server = FakeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = _provider(server, "/api")
        missing = OpenWAProvider(f"http://127.0.0.1:{server.server_address[1]}", API_KEY, "")
        skipped = missing.send_text(PHONE, "hello")
        assert skipped["ok"] is False
        assert server.hits == []

        server.mode = "404"
        failed = provider.send_text(PHONE, "hello")
        assert failed["ok"] is False
        assert failed["state"] == "not_found"
        assert failed["http_status"] == 404
        assert confirmed_message_id(failed) == ""
        posts = _posts(server)
        assert len(posts) == 1
        assert posts[0]["path"] == f"/api/sessions/{SESSION}/messages/send-text"
        assert "/api/api/" not in posts[0]["path"]
        assert "sendText" not in posts[0]["path"]
        assert "send-file" not in posts[0]["path"]
        body = json.loads(posts[0]["body"])
        assert set(body) == {"chatId", "text"}
        assert body["chatId"] == "919811122334@c.us"
        assert posts[0]["authorization"] is None
        assert posts[0]["session_header"] is None
        assert posts[0]["api_key"] == API_KEY
        assert API_KEY not in failed["detail"]

        server.hits.clear()
        server.mode = "401"
        denied = provider.send_text(PHONE, "hello")
        assert denied["ok"] is False
        assert denied["state"] == "unauthorized"
        assert denied["http_status"] == 401
        assert API_KEY not in denied["detail"]
        assert len(_posts(server)) == 1

        server.hits.clear()
        server.mode = "409"
        conflict = provider.send_text(PHONE, "hello")
        assert conflict["ok"] is False
        assert conflict["state"] == "conflict"
        assert conflict["http_status"] == 409
        assert len(_posts(server)) == 1

        server.hits.clear()
        server.mode = "decoy"
        decoy = provider.send_text(PHONE, "hello")
        assert decoy["ok"] is False
        assert decoy["state"] == "unconfirmed"
        assert confirmed_message_id(decoy) == ""

        server.hits.clear()
        server.mode = "success"
        accepted = provider.send_text(PHONE, "hello")
        assert accepted["ok"] is True
        assert confirmed_message_id(accepted) == "true_919811122334@c.us_ABC"
        assert "phone" not in accepted

        server.hits.clear()
        document = provider.send_document(PHONE, "bill.pdf", b"%PDF-1.4", "Bill")
        assert document["ok"] is True
        posted = _posts(server)[-1]
        assert posted["path"] == f"/api/sessions/{SESSION}/messages/send-document"
        doc_body = json.loads(posted["body"])
        assert set(doc_body) == {"chatId", "base64", "mimetype", "filename", "caption"}
        assert doc_body["mimetype"] == "application/pdf"
        assert doc_body["filename"] == "bill.pdf"
        assert "document" not in doc_body
        assert all("sendFile" not in hit["path"] and "send-file" not in hit["path"] for hit in server.hits)

        provider.text_timeout = 0.4
        server.mode = "timeout"
        timed = provider.send_text(PHONE, "hello")
        assert timed["ok"] is False
        assert timed["state"] == "timeout"
        assert confirmed_message_id(timed) == ""
    finally:
        server.shutdown()
        server.server_close()


def test_admin_probe_shape_has_no_secrets():
    server = FakeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = _temp_db()
    try:
        server.mode = "ready"
        base = f"http://127.0.0.1:{server.server_address[1]}/api"
        config_set(conn, "wa_base_url", base)
        config_set(conn, "wa_api_key", API_KEY)
        config_set(conn, "wa_session_id", SESSION)
        status = notify.connection_status(conn)
        assert status["configured"] is True
        assert status["reachable"] is True
        assert status["authenticated"] is True
        assert status["session_status"] == "ready"
        assert status["provider"] == "openwa"
        assert set(status) == {"configured", "reachable", "authenticated", "session_status", "provider"}
        encoded = json.dumps(status)
        assert API_KEY not in encoded
        assert "919999999999" not in encoded
        assert "api_key" not in status
        assert "base_url" not in status
        health = [hit for hit in server.hits if hit["path"].endswith("/health")]
        session_hits = [hit for hit in server.hits if hit["path"].endswith(f"/sessions/{SESSION}")]
        assert health and health[0]["api_key"] is None
        assert session_hits and session_hits[0]["api_key"] == API_KEY
        assert session_hits[0]["authorization"] is None

        server.hits.clear()
        server.mode = "auth_fail"
        denied = notify.connection_status(conn)
        assert denied["reachable"] is True
        assert denied["authenticated"] is False
        assert denied["session_status"] == "unauthorized"
        assert set(denied) == {"configured", "reachable", "authenticated", "session_status", "provider"}
        assert API_KEY not in json.dumps(denied)
    finally:
        server.shutdown()
        server.server_close()
        conn.close()


def test_whatsapp_routes_are_outside_the_billing_transaction():
    for path in ("/api/whatsapp/messages", "/api/whatsapp/documents", "/api/integrations/whatsapp/test", "/api/integrations/whatsapp/send-test"):
        _fn, _params, _perm, _auth, tx = match("POST", path)
        assert tx is False, path


def _finalized_bill(conn, note_id="NT-WA"):
    stamp = now_iso()
    conn.execute(
        "INSERT INTO patients(id, name, status, created_at) VALUES (?,?,?,?)",
        ("P-WA", "WhatsApp Regression", "ACTIVE", stamp),
    )
    conn.execute(
        """INSERT INTO invoices(id, number, patient_id, status, payment_status, gross_paise, net_paise, paid_paise, due_paise, created_at, finalized_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        ("INV-WA", "AIPF-BILL-WA", "P-WA", "FINALIZED", "PAID", 50000, 50000, 50000, 0, stamp, stamp),
    )
    conn.execute(
        """INSERT INTO notifications(id, channel, patient_id, phone, message_type, body, status, scheduled_at, provider, retry_count, max_retries, entity_type, entity_id, created_at, updated_at)
           VALUES (?,'WHATSAPP',?,?,?,?, 'QUEUED', ?, 'openwa', 0, 3, 'invoice', ?, ?, ?)""",
        (note_id, "P-WA", PHONE, "visit_complete", "PATIENT-SECRET-BODY", stamp, "INV-WA", stamp, stamp),
    )


def _bill(conn):
    row = conn.execute("SELECT status, paid_paise, net_paise, due_paise FROM invoices WHERE id='INV-WA'").fetchone()
    return (row["status"], row["paid_paise"], row["net_paise"], row["due_paise"])


def test_provider_failure_does_not_mark_sent_or_change_a_finalized_bill():
    server = FakeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = _temp_db()
    try:
        _finalized_bill(conn)
        before = _bill(conn)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        config_set(conn, "wa_base_url", base)
        config_set(conn, "wa_api_key", API_KEY)
        config_set(conn, "wa_session_id", SESSION)
        server.mode = "404"
        try:
            with Tx(conn):
                handled = notify.process_queue(conn, limit=5)
                assert handled == 1
                raise RuntimeError("later whatsapp failure must not own the bill")
        except RuntimeError:
            pass
        assert _bill(conn) == before
        note = conn.execute("SELECT status, failure_reason, provider_message_id FROM notifications WHERE id='NT-WA'").fetchone()
        assert note["status"] != "SENT"
        assert note["provider_message_id"] in (None, "")
        assert "PATIENT-SECRET-BODY" not in (note["failure_reason"] or "")
        assert API_KEY not in (note["failure_reason"] or "")

        conn.execute("UPDATE notifications SET status='QUEUED', retry_count=0, failure_reason=NULL, provider_message_id=NULL, scheduled_at=? WHERE id='NT-WA'", (now_iso(),))
        server.mode = "409"
        notify.process_queue(conn, limit=5)
        note = conn.execute("SELECT status, failure_reason FROM notifications WHERE id='NT-WA'").fetchone()
        assert note["status"] == "QUEUED"
        assert "409" in (note["failure_reason"] or "")
        assert _bill(conn) == before

        conn.execute("UPDATE notifications SET status='QUEUED', retry_count=0, failure_reason=NULL, scheduled_at=? WHERE id='NT-WA'", (now_iso(),))
        server.mode = "401"
        notify.process_queue(conn, limit=5)
        note = conn.execute("SELECT status, failure_reason FROM notifications WHERE id='NT-WA'").fetchone()
        assert note["status"] == "QUEUED"
        assert "401" in (note["failure_reason"] or "")
        assert API_KEY not in (note["failure_reason"] or "")
        assert _bill(conn) == before

        conn.execute("UPDATE notifications SET status='QUEUED', retry_count=0, failure_reason=NULL, scheduled_at=? WHERE id='NT-WA'", (now_iso(),))
        server.mode = "decoy"
        notify.process_queue(conn, limit=5)
        note = conn.execute("SELECT status, provider_message_id FROM notifications WHERE id='NT-WA'").fetchone()
        assert note["status"] != "SENT"
        assert note["provider_message_id"] in (None, "")
        assert _bill(conn) == before

        real_provider = notify.provider_from_config

        def fast_provider(db):
            provider = real_provider(db)
            provider.text_timeout = 0.4
            return provider

        notify.provider_from_config = fast_provider
        try:
            conn.execute("UPDATE notifications SET status='QUEUED', retry_count=0, failure_reason=NULL, scheduled_at=? WHERE id='NT-WA'", (now_iso(),))
            server.mode = "timeout"
            notify.process_queue(conn, limit=5)
        finally:
            notify.provider_from_config = real_provider
        note = conn.execute("SELECT status, failure_reason, provider_message_id FROM notifications WHERE id='NT-WA'").fetchone()
        assert note["status"] == "QUEUED"
        assert "timed out" in (note["failure_reason"] or "").lower()
        assert note["provider_message_id"] in (None, "")
        assert _bill(conn) == before

        conn.execute("UPDATE notifications SET status='QUEUED', retry_count=0, failure_reason=NULL, provider_message_id=NULL, scheduled_at=? WHERE id='NT-WA'", (now_iso(),))
        server.mode = "success"
        notify.process_queue(conn, limit=5)
        note = conn.execute("SELECT status, provider_message_id FROM notifications WHERE id='NT-WA'").fetchone()
        assert note["status"] == "SENT"
        assert note["provider_message_id"] == "true_919811122334@c.us_ABC"
        assert _bill(conn) == before
    finally:
        server.shutdown()
        server.server_close()
        conn.close()
