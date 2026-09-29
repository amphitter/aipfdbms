"""Phase 1: permissions, sessions, and record scope over real HTTP.

Skipped unless AIPF_TEST_POSTGRES or AIPF_DATABASE_URL is a PostgreSQL URL.
Set PHASE1_REQUIRE_POSTGRES=1 to fail instead of skip.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path("/tmp/phase1_evidence.json")


def _postgres_url() -> str:
    return (os.environ.get("AIPF_TEST_POSTGRES") or os.environ.get("AIPF_DATABASE_URL") or "").strip()


def _static_scans() -> list[str]:
    problems = []
    backend = ROOT / "backend" / "aipf"
    frontend = ROOT / "frontend" / "src"
    for path in list(backend.rglob("*.py")) + list(frontend.rglob("*.ts")) + list(frontend.rglob("*.tsx")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if 'roles.includes("admin")' in text or '"admin" in user.get("roles"' in text or '"admin" in (user.get("roles")' in text:
            problems.append(f"role-name authorization in {path.relative_to(ROOT)}")
    store = (frontend / "store.ts").read_text(encoding="utf-8")
    api = (frontend / "api.ts").read_text(encoding="utf-8")
    app = (frontend / "App.tsx").read_text(encoding="utf-8")
    if "permissions.includes" not in store:
        problems.append("frontend can() does not use permissions")
    if "aipf-unauthorized" not in api or "clearToken" not in api:
        problems.append("frontend does not clear the session on 401")
    if "function Guard" not in app or "aipf-forbidden" not in app:
        problems.append("frontend routes are not permission-guarded")
    return problems


def test_phase1_static_authorization():
    problems = _static_scans()
    assert problems == [], problems


def test_phase1_http_matrix():
    url = _postgres_url()
    if not url.startswith("postgres"):
        if os.environ.get("PHASE1_REQUIRE_POSTGRES") == "1":
            raise AssertionError("PostgreSQL URL is required for the Phase 1 HTTP matrix")
        print("skip phase1 http: PostgreSQL URL is not set")
        return
    failures = _run_matrix(url)
    assert failures == [], failures


def _run_matrix(admin_url: str) -> list[str]:
    import psycopg

    password = secrets.token_urlsafe(18)
    os.environ["AIPF_SEED_PASSWORD"] = password
    db_name = "aipf_phase1"
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {db_name}")
    admin.execute(f"CREATE DATABASE {db_name}")
    admin.close()
    target = admin_url.rsplit("/", 1)[0] + "/" + db_name
    previous = os.environ.get("AIPF_DATABASE_URL")
    os.environ["AIPF_DATABASE_URL"] = target
    port = 8794
    proc = None
    failures: list[str] = []
    evidence = {"checks": [], "catalog": [], "secrets_absent": True}
    try:
        from aipf.db import apply_migrations, connect
        from aipf.seed import seed
        from aipf import core

        conn = connect()
        assert conn.dialect == "postgres"
        version = apply_migrations(conn)
        assert version >= 5, version
        seed(conn)
        core.config_set(conn, "backup_enabled", "0")
        conn.close()

        env = os.environ.copy()
        env["AIPF_DATABASE_URL"] = target
        env["AIPF_PORT"] = str(port)
        env["AIPF_SEED_PASSWORD"] = password
        env["AIPF_ENV"] = "development"
        proc = subprocess.Popen(
            [sys.executable, "-m", "aipf.server"],
            cwd=str(ROOT / "backend"),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        ready = _wait_ready(proc, port)
        if not ready:
            tail = _drain(proc)
            failures.append("server did not start: " + tail[-800:])
            return failures
        base = f"http://127.0.0.1:{port}"

        def check(name: str, cond: bool, detail: str = ""):
            evidence["checks"].append({"name": name, "ok": bool(cond)})
            if not cond:
                failures.append(name + (": " + detail if detail else ""))

        def call(method, path, token=None, body=None):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(base + path, data=data, method=method)
            if body is not None:
                req.add_header("Content-Type", "application/json")
            if token:
                req.add_header("Authorization", "Bearer " + token)
            try:
                with urllib.request.urlopen(req, timeout=30) as res:
                    raw = res.read()
                    ctype = res.headers.get("content-type") or ""
                    if "json" in ctype:
                        return res.status, json.loads(raw.decode())
                    return res.status, {"raw": True, "length": len(raw)}
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                try:
                    payload = json.loads(raw.decode())
                except Exception:
                    payload = {"raw": True, "length": len(raw)}
                return exc.code, payload

        def login(username):
            status, payload = call("POST", "/api/auth/login", body={"username": username, "password": password})
            token = ((payload or {}).get("data") or {}).get("token")
            user = ((payload or {}).get("data") or {}).get("user") or {}
            return status, token, user, payload

        status, payload = call("GET", "/api/public/branding")
        check("public branding", status == 200, str(status))
        status, payload = call("GET", "/api/patients")
        check("unauthenticated patient list", status == 401, str(status))
        status, payload = call("GET", "/api/users")
        check("unauthenticated staff list", status == 401, str(status))

        bad_status, bad_payload = call("POST", "/api/auth/login", body={"username": "director", "password": "not-the-password"})
        bad_message = ((bad_payload or {}).get("error") or {}).get("message")
        check("bad password is 401", bad_status == 401, str(bad_status))

        accounts = {
            "admin": "director",
            "doctor": "dr.anita",
            "reception": "reception",
            "pharmacist": "pharmacy",
            "lab": "lab",
            "billing": "billing",
        }
        tokens = {}
        for role, username in accounts.items():
            status, token, user, payload = login(username)
            tokens[role] = token
            check(f"{role} login", status == 200 and bool(token), str(status))
            check(f"{role} login has no password hash", "password_hash" not in json.dumps(user))
            check(f"{role} me hides token", "token" not in user)
            if role == "admin":
                check("admin permissions include user.manage", "user.manage" in (user.get("permissions") or []))
            if role == "doctor":
                check("doctor has no patient.view_all", "patient.view_all" not in (user.get("permissions") or []))
                check("doctor has no document.view_all", "document.view_all" not in (user.get("permissions") or []))

        status, me = call("GET", "/api/auth/me", tokens["admin"])
        check("me returns permissions", status == 200 and "user.manage" in (me.get("data") or {}).get("permissions", []), str(status))
        check("me does not echo bearer", "token" not in (me.get("data") or {}))

        status, _ = call("GET", "/api/users", tokens["admin"])
        check("admin lists staff", status == 200, str(status))
        status, _ = call("GET", "/api/system/health", tokens["admin"])
        check("admin health", status == 200, str(status))
        for role in ("doctor", "reception", "pharmacist", "lab", "billing"):
            status, _ = call("GET", "/api/users", tokens[role])
            check(f"{role} cannot list staff", status == 403, str(status))
            status, _ = call("POST", "/api/pharmacy/dispense", tokens[role], {})
            if role == "pharmacist":
                check("pharmacist is not forbidden from dispense by permission", status != 403, str(status))
            else:
                check(f"{role} cannot dispense", status == 403, str(status))

        status, _ = call("GET", "/api/inventory/products", tokens["pharmacist"])
        check("pharmacist inventory", status == 200, str(status))
        status, _ = call("GET", "/api/inventory/products", tokens["billing"])
        check("billing cannot open inventory", status == 403, str(status))
        status, _ = call("GET", "/api/lab/orders", tokens["lab"])
        check("lab orders", status == 200, str(status))
        status, _ = call("GET", "/api/config", tokens["lab"])
        check("lab cannot open config", status == 403, str(status))
        status, _ = call("POST", "/api/invoices/INV-S1/finalize", tokens["pharmacist"], {})
        check("pharmacist cannot finalize", status == 403, str(status))
        status, _ = call("POST", "/api/invoices/INV-S1/refund", tokens["doctor"], {"amount_paise": 1, "reason": "no"})
        check("doctor cannot refund", status == 403, str(status))
        status, invoices = call("GET", "/api/invoices", tokens["billing"])
        check("billing lists invoices", status == 200 and any(item.get("patient_id") == "P-000001" for item in (invoices.get("data") or {}).get("items", [])), str(status))

        status, own = call("GET", "/api/patients/P-000004", tokens["doctor"])
        check("doctor reads assigned patient", status == 200 and (own.get("data") or {}).get("id") == "P-000004", str(status))
        status, hidden = call("GET", "/api/patients/P-000001", tokens["doctor"])
        check("doctor cannot read another patient", status == 404, str(status) + " " + str((hidden.get("error") or {}).get("message")))
        check("hidden patient message does not name the record", "Rajesh" not in json.dumps(hidden))
        status, _ = call("GET", "/api/patients/P-000001", tokens["reception"])
        check("reception reads any patient", status == 200, str(status))
        status, _ = call("GET", "/api/patients/P-000001", tokens["pharmacist"])
        check("pharmacist reads any patient", status == 200, str(status))
        status, _ = call("GET", "/api/patients/P-000001", tokens["lab"])
        check("lab reads any patient", status == 200, str(status))
        status, found = call("GET", "/api/patients?q=Fatima", tokens["doctor"])
        ids = [item.get("id") for item in (found.get("data") or {}).get("items", [])]
        check("doctor search keeps assigned patient", "P-000004" in ids, str(ids))
        status, other = call("GET", "/api/patients?q=Rajesh", tokens["doctor"])
        other_ids = [item.get("id") for item in (other.get("data") or {}).get("items", [])]
        check("doctor search hides other patient", "P-000001" not in other_ids, str(other_ids))
        status, _ = call("GET", "/api/queue?doctor_id=U-IMRAN", tokens["doctor"])
        check("doctor cannot open another queue", status == 403, str(status))
        status, queue = call("GET", "/api/queue", tokens["doctor"])
        doctors = {item.get("doctor_id") for item in (queue.get("data") or {}).get("items", [])}
        check("doctor queue is only their own", status == 200 and doctors <= {"U-ANITA"}, str(doctors))
        status, _ = call("POST", "/api/queue/Q-1/status", tokens["doctor"], {"status": "CALLED"})
        check("doctor cannot change another queue", status == 403, str(status))
        status, _ = call("GET", "/api/opd/OPD-2026-000001", tokens["doctor"])
        check("doctor cannot open another encounter", status == 404, str(status))
        status, _ = call("GET", "/api/opd/OPD-2026-000003", tokens["doctor"])
        check("doctor opens own encounter", status == 200, str(status))
        status, _ = call("POST", "/api/consultations", tokens["doctor"], {"encounter_id": "OPD-2026-000001", "diagnosis": "not mine"})
        check("doctor cannot write another consultation", status == 403, str(status))
        status, scoped_bills = call("GET", "/api/invoices", tokens["doctor"])
        bill_patients = {item.get("patient_id") for item in (scoped_bills.get("data") or {}).get("items", [])}
        check("doctor invoice list is scoped", "P-000001" not in bill_patients, str(bill_patients))

        tiny = "phase1 scope".encode()
        status, uploaded = call("POST", "/api/documents", tokens["reception"], {
            "patient_id": "P-000001",
            "document_type": "Other",
            "title": "Identity file",
            "filename": "scope.txt",
            "mime_type": "text/plain",
            "content_base64": __import__("base64").b64encode(tiny).decode(),
        })
        doc_id = (uploaded.get("data") or {}).get("id")
        check("reception uploads document", status == 200 and bool(doc_id), str(status))
        if doc_id:
            status, _ = call("GET", f"/api/documents/{doc_id}/file", tokens["reception"])
            check("reception opens any document", status == 200, str(status))
            status, hidden_doc = call("GET", f"/api/documents/{doc_id}/file", tokens["doctor"])
            check("doctor cannot open unlinked document", status == 404, str(status))
            status, _ = call("GET", f"/api/documents/{doc_id}/file", tokens["pharmacist"])
            check("pharmacist view_all does not open documents", status == 404, str(status))
            status, listed = call("GET", "/api/documents?patient_id=P-000001", tokens["doctor"])
            listed_ids = [item.get("id") for item in (listed.get("data") or {}).get("items", [])]
            check("doctor document list hides the file", doc_id not in listed_ids, str(listed_ids))

        created_password = secrets.token_urlsafe(18)
        status, created = call("POST", "/api/users", tokens["admin"], {
            "username": "phase1.temp",
            "full_name": "Phase One Temp",
            "password": created_password,
            "roles": ["billing"],
        })
        temp_id = (created.get("data") or {}).get("id")
        check("admin creates user", status == 200 and bool(temp_id), str(status) + " " + str((created.get("error") or {}).get("message")))
        check("create response has no password", created_password not in json.dumps(created))
        temp_status, temp_payload = call("POST", "/api/auth/login", body={"username": "phase1.temp", "password": created_password})
        temp_token = ((temp_payload or {}).get("data") or {}).get("token")
        check("new user can login", temp_status == 200 and bool(temp_token), str(temp_status))
        changed = created_password + "x"
        status, _ = call("POST", "/api/auth/password", temp_token, {"current": created_password, "password": changed})
        check("password change", status == 200, str(status))
        status, _ = call("POST", "/api/auth/login", body={"username": "phase1.temp", "password": created_password})
        check("old password rejected", status == 401, str(status))
        status, relog = call("POST", "/api/auth/login", body={"username": "phase1.temp", "password": changed})
        temp_token = ((relog or {}).get("data") or {}).get("token")
        check("new password accepted", status == 200, str(status))
        reset_password = secrets.token_urlsafe(18)
        status, reset_body = call("PATCH", f"/api/users/{temp_id}", tokens["admin"], {
            "username": "phase1.temp",
            "full_name": "Phase One Temp",
            "roles": ["billing"],
            "password": reset_password,
        })
        check("admin password reset", status == 200, str(status))
        check("reset response has no password", reset_password not in json.dumps(reset_body))
        changed = reset_password
        status, _ = call("PATCH", f"/api/users/{temp_id}", tokens["admin"], {
            "username": "phase1.temp",
            "full_name": "Phase One Temp",
            "roles": ["billing"],
            "active": False,
        })
        check("admin disables user", status == 200, str(status))
        status, disabled_login = call("POST", "/api/auth/login", body={"username": "phase1.temp", "password": changed})
        disabled_message = ((disabled_login or {}).get("error") or {}).get("message")
        check("disabled login denied", status == 401, str(status))
        check("disabled message matches bad password", disabled_message == bad_message, str(disabled_message))
        status, _ = call("GET", "/api/auth/me", temp_token)
        check("disabled session invalidated", status == 401, str(status))

        status, roles = call("GET", "/api/roles", tokens["admin"])
        role_items = (roles.get("data") or {}).get("items") or []
        doctor_perms = next(item["permissions"] for item in role_items if item["code"] == "doctor")
        admin_perms = next(item["permissions"] for item in role_items if item["code"] == "admin")
        status, _ = call("PUT", "/api/roles/doctor/permissions", tokens["admin"], {"permissions": [p for p in doctor_perms if p != "patient.view"]})
        check("role permission update", status == 200, str(status))
        status, _ = call("GET", "/api/patients/P-000004", tokens["doctor"])
        check("role change removes access immediately", status == 403, str(status))
        status, _ = call("PUT", "/api/roles/doctor/permissions", tokens["admin"], {"permissions": doctor_perms})
        check("role permission restored", status == 200, str(status))
        status, _ = call("GET", "/api/patients/P-000004", tokens["doctor"])
        check("restored permission works", status == 200, str(status))
        status, _ = call("PUT", "/api/roles/admin/permissions", tokens["admin"], {"permissions": [p for p in admin_perms if p != "user.manage"]})
        status, bypass = call("GET", "/api/users", tokens["admin"])
        check("admin role name is not an allow-all", status == 403, str(bypass.get("error") or status))
        call("PUT", "/api/roles/admin/permissions", tokens["admin"], {"permissions": admin_perms})

        status, _ = call("POST", "/api/auth/logout", tokens["billing"])
        check("logout", status == 200, str(status))
        status, _ = call("GET", "/api/auth/me", tokens["billing"])
        check("logged out token rejected", status == 401, str(status))

        digest = hashlib.sha256(tokens["doctor"].encode()).hexdigest()
        direct = psycopg.connect(target, autocommit=True)
        with direct.cursor() as cur:
            cur.execute("SELECT token FROM sessions WHERE user_id='U-ANITA' AND token=%s", (tokens["doctor"],))
            raw_stored = cur.fetchone()
            cur.execute("SELECT token, expires_at FROM sessions WHERE user_id='U-ANITA' AND token=%s", (digest,))
            hashed = cur.fetchone()
            cur.execute("SELECT last_login_at FROM users WHERE username='dr.anita'")
            last_login = cur.fetchone()
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name LIKE '%password%'")
            password_columns = [row[0] for row in cur.fetchall()]
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.table_constraints
                WHERE constraint_type='FOREIGN KEY'
                  AND table_name IN ('user_roles', 'role_permissions', 'sessions')
            """)
            fk_count = cur.fetchone()[0]
            cur.execute("SELECT conname FROM pg_constraint WHERE conname='users_active_check'")
            active_check = cur.fetchone()
            cur.execute("SELECT action, COALESCE(old_value,''), COALESCE(new_value,''), COALESCE(reason,''), COALESCE(entity_id,'') FROM audit_logs")
            audit_rows = cur.fetchall()
            actions = {row[0] for row in audit_rows}
            blob = "\n".join(" ".join(row[1:]) for row in audit_rows)
            cur.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token=%s", (digest,))
        direct.close()
        check("session stores hash not raw token", raw_stored is None and hashed is not None)
        check("last login recorded", bool(last_login and last_login[0]))
        check("password is stored only as a hash column", "password_hash" in password_columns and "password" not in password_columns, str(password_columns))
        check("identity foreign keys", fk_count >= 4, str(fk_count))
        check("active check constraint", active_check is not None)
        for action in ("login", "login_failed", "logout", "user_create", "user_disable", "password_reset", "password_change", "role_permissions", "authz_denied", "record_denied", "queue_denied"):
            check(f"audit {action}", action in actions, str(sorted(actions)))
        secret_hit = password in blob or created_password in blob or changed in blob or tokens["doctor"] in blob
        check("audit has no password or bearer", not secret_hit)
        evidence["secrets_absent"] = not secret_hit
        status, _ = call("GET", "/api/auth/me", tokens["doctor"])
        check("expired session rejected", status == 401, str(status))

        from aipf.server import CATALOG
        evidence["catalog"] = CATALOG
        anonymous = [item for item in CATALOG if not item["auth"]]
        check("anonymous routes are only public", {item["path"] for item in anonymous} <= {"/api/public/branding", "/api/public/accounts", "/api/auth/login", "/api/public/logo"})
        patient_routes = [item for item in CATALOG if "patient" in item["path"] and item["method"] == "GET"]
        check("patient reads require a permission", all(item["permission"] for item in patient_routes), str(patient_routes))
    except Exception as exc:
        failures.append(f"matrix crashed: {type(exc).__name__}: {exc}")
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            import psycopg
            admin = psycopg.connect(admin_url, autocommit=True)
            admin.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
            admin.close()
        except Exception as exc:
            failures.append(f"cleanup failed: {exc}")
        if previous is None:
            os.environ.pop("AIPF_DATABASE_URL", None)
        else:
            os.environ["AIPF_DATABASE_URL"] = previous
        EVIDENCE.write_text(json.dumps(evidence, indent=2))
        _cleanup_uploaded_files()
    return failures


def _cleanup_uploaded_files():
    folder = ROOT / "data" / "documents"
    if not folder.exists():
        return
    for path in folder.rglob("scope.txt"):
        path.unlink(missing_ok=True)
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix == ".txt" and path.stat().st_size < 64:
            try:
                if path.read_text(encoding="utf-8", errors="ignore") == "phase1 scope":
                    path.unlink()
            except OSError:
                pass


def _wait_ready(proc: subprocess.Popen, port: int) -> bool:
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/public/branding", timeout=2) as res:
                if res.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def _drain(proc: subprocess.Popen) -> str:
    try:
        out, _ = proc.communicate(timeout=3)
    except Exception:
        out = ""
    return out or ""
