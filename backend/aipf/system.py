"""Health, backup, leads, reports, search, and the operational dashboard."""

from __future__ import annotations

from aipf.repo import audit as audit_sql
from aipf.repo import billing as billing_sql
from aipf.repo import documents as documents_sql
from aipf.repo import encounters as encounters_sql
from aipf.repo import inventory as inventory_sql
from aipf.repo import ipd as ipd_sql
from aipf.repo import lab as lab_sql
from aipf.repo import masters as masters_sql
from aipf.repo import notifications as notifications_sql
from aipf.repo import operations as operations_sql
from aipf.repo import ot as ot_sql
from aipf.repo import patients as patients_sql
from aipf.repo import payments as payments_sql
from aipf.repo import pharmacy as pharmacy_sql
from aipf.repo import users as users_sql
from aipf.repo import dashboard as dashboard_sql
from aipf.repo import wards as wards_sql

import csv
import io
import json
import os
import shutil
import socket
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from .core import audit, config_get, config_map, config_set, hospital, permit
from .db import BACKUPS, DATA, DB_PATH, DOCUMENTS, LOGS, one, rows
from .events import client_count, publish
from .notify import provider_from_config
from .pdf import PDF
from datetime import date, timedelta

from .util import ApiError, clean_text, is_masked, mask_secret, new_id, now, now_iso, require, sha256_file, today_str

_worker_heartbeat = {"at": None, "alive": False}
_lock = threading.Lock()


def mark_worker(alive: bool):
    with _lock:
        _worker_heartbeat["alive"] = alive
        _worker_heartbeat["at"] = now_iso()


def _check(name: str, status: str, detail: str = "", latency_ms: float | None = None, error: str = "", action: str = "") -> dict:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "latency_ms": None if latency_ms is None else round(latency_ms, 1),
        "last_check": now_iso(),
        "last_success": now_iso() if status in ("HEALTHY", "NOT_CONFIGURED") else None,
        "error": error,
        "recommended_action": action,
    }


def _dialect(conn) -> str:
    return getattr(conn, "dialect", "sqlite")


def _refuse_file_backup(conn, action: str) -> None:
    if _dialect(conn) == "sqlite":
        return
    raise ApiError(
        f"{action} is not implemented for PostgreSQL. The SQLite file copy was not used, and no database was replaced.",
        501,
        "not_implemented",
    )


def health_report(conn, deep: bool = True) -> dict:
    checks = []
    checks.append(_check("Application", "HEALTHY", "Application process is serving requests."))
    checks.append(_check("API", "HEALTHY", "Request reached the diagnostics service."))

    started = time.perf_counter()
    try:
        operations_sql.q_system_2010(conn)
        latency = (time.perf_counter() - started) * 1000
        status = "HEALTHY" if latency < 200 else "DEGRADED"
        engine = "PostgreSQL" if _dialect(conn) == "postgres" else "SQLite"
        checks.append(_check("Database", status, f"{engine} answered a connectivity probe. Client PCs do not connect to it.", latency, action="" if status == "HEALTHY" else "Check the database host and disk."))
        checks.append(_check("Database latency", status, f"{latency:.1f} ms", latency))
        checks.append(_check("Database pool", "NOT_CONFIGURED", "No connection pool is configured. Each request opens its own connection."))
    except Exception as exc:
        checks.append(_check("Database", "CRITICAL", error=str(exc), action="Restore the latest verified backup if the database file is damaged."))
        checks.append(_check("Database latency", "CRITICAL", error="Database did not answer."))
        checks.append(_check("Database pool", "CRITICAL", error="No connection."))

    storage = _storage_check()
    checks.append(storage)
    checks.append(_check("Document storage", storage["status"], storage["detail"], error=storage["error"], action=storage["recommended_action"]))
    writable = os.access(DOCUMENTS, os.W_OK)
    checks.append(_check("File permissions", "HEALTHY" if writable else "CRITICAL", "Document folder is writable." if writable else "Document folder is not writable.", action="" if writable else "Fix ownership of the data/documents directory."))

    usage = shutil.disk_usage(DATA)
    free_ratio = usage.free / usage.total if usage.total else 1
    disk_status = "HEALTHY" if free_ratio > 0.15 else ("DEGRADED" if free_ratio > 0.05 else "CRITICAL")
    checks.append(_check(
        "Disk capacity",
        disk_status,
        f"{usage.free // (1024**3)} GB free of {usage.total // (1024**3)} GB",
        action="" if disk_status == "HEALTHY" else "Free disk space before the next backup.",
    ))
    try:
        load = os.getloadavg()
        checks.append(_check("CPU", "HEALTHY" if load[0] < 4 else "DEGRADED", f"Load {load[0]:.2f}"))
    except (AttributeError, OSError):
        # Windows and some container/embedded hosts do not expose POSIX load average.
        # This is a missing optional metric, not a health failure.
        checks.append(_check("CPU", "HEALTHY", "Load average is not exposed on this host."))
    mem = _memory()
    checks.append(mem)

    realtime = client_count()
    checks.append(_check(
        "Realtime",
        "DEGRADED",
        f"In-process hub only. {realtime} subscriber(s). Subscriber count is not proof a client received an event, and a second process would not share this hub.",
        action="Do not treat this as a multi-user bus.",
    ))
    with _lock:
        beat = dict(_worker_heartbeat)
    worker_ok = beat.get("alive") and beat.get("at")
    checks.append(_check("Queue worker", "HEALTHY" if worker_ok else "DEGRADED", f"Last heartbeat {beat.get('at') or 'not yet'}", action="" if worker_ok else "Restart the hospital server so the notification worker starts."))

    pdf_status, pdf_detail, pdf_ms = _pdf_check() if deep else ("HEALTHY", "Skipped", 0)
    checks.append(_check("PDF engine", pdf_status, pdf_detail, pdf_ms, action="" if pdf_status == "HEALTHY" else "Retry PDF generation. Bills already stored are unchanged."))

    last_backup = operations_sql.q_system_5208(conn)
    if not last_backup:
        checks.append(_check("Backup scheduler", "DEGRADED", "No local backup has been recorded yet.", action="Create a local backup from Admin > Backups."))
        checks.append(_check("Local backup", "DEGRADED", "None yet.", action="Run a backup before the day ends."))
    else:
        age_h = _hours_since(last_backup["started_at"])
        bstatus = "HEALTHY" if age_h < 36 else "DEGRADED"
        checks.append(_check("Backup scheduler", bstatus, f"Last local backup {last_backup['started_at']}", action="" if bstatus == "HEALTHY" else "Backup is older than 36 hours."))
        checks.append(_check("Local backup", bstatus, f"{last_backup['status']} · {last_backup.get('checksum','')[:12]}"))

    cloud = config_get(conn, "cloud_endpoint", "")
    if not cloud:
        checks.append(_check("Cloud backup", "NOT_CONFIGURED", "Cloud backup is optional. Local backup does not depend on it.", action="Configure an S3-compatible bucket only if an off-site copy is required."))
    else:
        last_cloud = operations_sql.q_system_6364(conn)
        cstatus = (last_cloud or {}).get("cloud_status") or "UNKNOWN"
        checks.append(_check("Cloud backup", "HEALTHY" if cstatus == "VERIFIED" else "DEGRADED", f"Last cloud status: {cstatus}", error=(last_cloud or {}).get("cloud_error") or "", action="Retry cloud upload. Do not delete the local archive."))

    wa = provider_from_config(conn)
    wa_status = wa.check_connection()
    if wa_status.get("state") == "not_configured" or config_get(conn, "wa_enabled", "0") != "1":
        checks.append(_check("OpenWA", "NOT_CONFIGURED", "WhatsApp is isolated. Bills and pharmacy do not wait for it.", action="Configure OpenWA under Integrations when the hospital wants outbound messages."))
    else:
        checks.append(_check("OpenWA", "HEALTHY" if wa_status.get("ok") else "DEGRADED", wa_status.get("detail") or wa_status.get("state") or "", error="" if wa_status.get("ok") else (wa_status.get("detail") or "Unreachable"), action="" if wa_status.get("ok") else "Check the OpenWA host on the LAN. Queued messages will retry."))

    if config_get(conn, "leads_enabled", "0") != "1":
        checks.append(_check("Website leads", "NOT_CONFIGURED", "Lead sync is optional. Registration does not use the website.", action="Add the MongoDB URI only if the public website should feed the desk."))
    else:
        checks.append(_check("Website leads", "DEGRADED", "Enabled. Use Test connection on the integrations screen for a live probe.", action="Sync when the internet is up. The desk keeps working if it is not."))

    checks.append(_check("Scheduled jobs", "HEALTHY" if worker_ok else "DEGRADED", "Notification retry and backup clock run inside the server process."))
    checks.append(_check("Configured ports", "NOT_CONFIGURED", "No port scan was run. This request only proves the API process answered."))

    core_names = {"Application", "API", "Database", "Local file storage", "Document storage", "File permissions", "Disk capacity"}
    # storage check name
    statuses = [c["status"] for c in checks]
    if any(c["status"] == "CRITICAL" for c in checks):
        overall = "CRITICAL"
    elif any(c["status"] == "DEGRADED" for c in checks):
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"
    report = {"overall": overall, "checked_at": now_iso(), "checks": checks}
    try:
        operations_sql.q_system_8788(conn, now_iso(), overall, json.dumps(report))
    except Exception:
        pass
    return report


def _storage_check() -> dict:
    probe = DOCUMENTS / ".health-probe"
    started = time.perf_counter()
    try:
        DOCUMENTS.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        text = probe.read_text(encoding="utf-8")
        probe.unlink(missing_ok=True)
        if text != "ok":
            raise RuntimeError("Readback mismatch")
        return _check("Local file storage", "HEALTHY", "Write and read succeeded.", (time.perf_counter() - started) * 1000)
    except Exception as exc:
        return _check("Local file storage", "CRITICAL", error=str(exc), action="Restore write access to the data directory.")


def _memory() -> dict:
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.strip().split()[0])
        total = info.get("MemTotal", 1)
        avail = info.get("MemAvailable", 0)
        ratio = avail / total
        status = "HEALTHY" if ratio > 0.1 else "DEGRADED"
        return _check("RAM", status, f"{avail // 1024} MB available of {total // 1024} MB")
    except Exception:
        return _check("RAM", "HEALTHY", "Memory details are not exposed. Process is running.")


def _pdf_check():
    started = time.perf_counter()
    try:
        pdf = PDF(200, 120)
        pdf.new_page()
        pdf.text(10, 10, "AIPF", 10, "F2")
        data = pdf.finish()
        if not data.startswith(b"%PDF"):
            return "CRITICAL", "PDF header missing", (time.perf_counter() - started) * 1000
        return "HEALTHY", f"{len(data)} byte probe", (time.perf_counter() - started) * 1000
    except Exception as exc:
        return "CRITICAL", str(exc), None


def _hours_since(iso: str) -> float:
    from .util import parse_iso
    dt = parse_iso(iso)
    if not dt:
        return 999
    return (now() - dt).total_seconds() / 3600


def component_health(conn, name: str) -> dict:
    report = health_report(conn)
    aliases = {
        "database": "Database",
        "storage": "Local file storage",
        "whatsapp": "OpenWA",
        "backup": "Local backup",
        "realtime": "Realtime",
        "leads": "Website leads",
        "pdf": "PDF engine",
    }
    target = aliases.get(name, name)
    for check in report["checks"]:
        if check["name"].lower() == target.lower():
            return check
    raise ApiError("Unknown health check.", 404, "not_found")


def create_backup(conn, user, kind: str = "MANUAL") -> dict:
    _refuse_file_backup(conn, "File backup")
    if user:
        permit(user, "backup.create")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = now().strftime("%Y%m%d-%H%M%S")
    bid = new_id("BK")
    archive = BACKUPS / f"aipf-{stamp}.zip"
    started = now_iso()
    operations_sql.q_system_11775(conn)
    notes = []
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if DB_PATH.exists():
                zf.write(DB_PATH, "database/hospital.db")
            for file in DOCUMENTS.rglob("*"):
                if file.is_file() and file.name != ".health-probe":
                    zf.write(file, f"documents/{file.relative_to(DOCUMENTS)}")
            profile = hospital(conn)
            safe_config = {k: v for k, v in config_map(conn, include_secrets=False).items()}
            manifest = {
                "id": bid,
                "created_at": started,
                "hospital": profile.get("name"),
                "note": "Secret integration values are not copied into this manifest. The database file itself remains as sensitive as the live system. Keep the archive on the hospital server.",
                "config_redacted": safe_config,
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        checksum = sha256_file(archive)
        size = archive.stat().st_size
        cloud_status, cloud_error, cloud_key = _cloud_upload(conn, archive, checksum)
        status = "VERIFIED" if cloud_status == "VERIFIED" else ("PARTIAL" if cloud_status == "FAILED" else "LOCAL_OK")
        if cloud_status == "SKIPPED":
            status = "LOCAL_OK"
            notes.append("Cloud backup is not configured. Local archive saved.")
        if cloud_status == "FAILED":
            notes.append("Local archive kept. Cloud upload failed.")
        operations_sql.q_system_13363(conn, bid, kind, status, str(archive), size, checksum, cloud_status, cloud_error, cloud_key, started, now_iso(), (user or {}).get("id"), " ".join(notes), now_iso() if status == "VERIFIED" else None)
        _enforce_retention(conn)
        audit(conn, user, "backup_create", "backup", "backup", bid, new={"status": status, "checksum": checksum, "cloud": cloud_status})
        publish("backup.updated", {"id": bid, "status": status})
        return operations_sql.q_system_14129(conn, bid)
    except Exception as exc:
        if archive.exists():
            # Keep a partial file only if it was written; record the failure without deleting a good local copy.
            pass
        operations_sql.q_system_14379(conn, bid, kind, str(archive) if archive.exists() else None, str(exc), started, now_iso(), (user or {}).get("id"), "Backup failed")
        audit(conn, user, "backup_failed", "backup", "backup", bid, new={"error": str(exc)})
        raise ApiError(f"Backup failed: {exc}", 500, "backup_failed") from exc


def _cloud_upload(conn, archive: Path, checksum: str) -> tuple[str, str, str]:
    endpoint = config_get(conn, "cloud_endpoint", "")
    bucket = config_get(conn, "cloud_bucket", "")
    if not endpoint or not bucket:
        return "SKIPPED", "", ""
    key = f"{config_get(conn, 'cloud_prefix', 'aipf').strip('/')}/{archive.name}"
    try:
        _s3_put(conn, archive, key)
        verified = _s3_verify(conn, key, archive.stat().st_size, checksum)
        if verified.get("ok"):
            return "VERIFIED", "", key
        return "FAILED", verified.get("error") or "Uploaded but verification failed", key
    except Exception as exc:
        return "FAILED", str(exc), key


def _s3_put(conn, archive: Path, key: str):
    import hashlib
    import hmac
    from datetime import datetime, timezone
    from urllib.parse import quote

    endpoint = config_get(conn, "cloud_endpoint", "").rstrip("/")
    bucket = config_get(conn, "cloud_bucket", "")
    region = config_get(conn, "cloud_region", "auto") or "auto"
    access = config_get(conn, "cloud_access_key", "")
    secret = config_get(conn, "cloud_secret_key", "")
    require(access and secret, "Cloud access key is missing.")
    data = archive.read_bytes()
    payload_hash = hashlib.sha256(data).hexdigest()
    host = endpoint.split("://", 1)[-1]
    amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date = amz_date[:8]
    canonical_uri = "/" + "/".join(quote(part) for part in f"{bucket}/{key}".split("/"))
    canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical = f"PUT\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    scope = f"{date}/{region}/s3/aws4_request"
    string_to_sign = "AWS4-HMAC-SHA256\n" + amz_date + "\n" + scope + "\n" + hashlib.sha256(canonical.encode()).hexdigest()

    def sign(key_bytes, msg):
        return hmac.new(key_bytes, msg.encode(), hashlib.sha256).digest()

    k = sign(("AWS4" + secret).encode(), date)
    k = sign(k, region)
    k = sign(k, "s3")
    k = sign(k, "aws4_request")
    signature = hmac.new(k, string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = f"AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
    url = f"{endpoint}{canonical_uri}"
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Host", host)
    req.add_header("x-amz-date", amz_date)
    req.add_header("x-amz-content-sha256", payload_hash)
    req.add_header("Authorization", auth)
    req.add_header("Content-Type", "application/zip")
    with urllib.request.urlopen(req, timeout=60) as res:
        # A 200 alone is not verification.
        if res.status not in (200, 201):
            raise ApiError(f"Cloud upload returned HTTP {res.status}")


def _s3_verify(conn, key: str, size: int, checksum: str) -> dict:
    import hashlib
    import hmac
    from datetime import datetime, timezone
    from urllib.parse import quote

    endpoint = config_get(conn, "cloud_endpoint", "").rstrip("/")
    bucket = config_get(conn, "cloud_bucket", "")
    region = config_get(conn, "cloud_region", "auto") or "auto"
    access = config_get(conn, "cloud_access_key", "")
    secret = config_get(conn, "cloud_secret_key", "")
    host = endpoint.split("://", 1)[-1]
    amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date = amz_date[:8]
    canonical_uri = "/" + "/".join(quote(part) for part in f"{bucket}/{key}".split("/"))
    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical = f"GET\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    scope = f"{date}/{region}/s3/aws4_request"
    string_to_sign = "AWS4-HMAC-SHA256\n" + amz_date + "\n" + scope + "\n" + hashlib.sha256(canonical.encode()).hexdigest()

    def sign(key_bytes, msg):
        return hmac.new(key_bytes, msg.encode(), hashlib.sha256).digest()

    k = sign(("AWS4" + secret).encode(), date)
    k = sign(k, region)
    k = sign(k, "s3")
    k = sign(k, "aws4_request")
    signature = hmac.new(k, string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = f"AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
    req = urllib.request.Request(endpoint + canonical_uri, method="GET")
    req.add_header("Host", host)
    req.add_header("x-amz-date", amz_date)
    req.add_header("x-amz-content-sha256", payload_hash)
    req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read()
        if len(body) != size:
            return {"ok": False, "error": f"Size mismatch. Local {size}, remote {len(body)}."}
        remote_sum = hashlib.sha256(body).hexdigest()
        if remote_sum != checksum:
            return {"ok": False, "error": "Checksum mismatch after download."}
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def verify_backup(conn, user, backup_id: str) -> dict:
    permit(user, "backup.view")
    row = operations_sql.q_system_20264(conn, backup_id)
    require(row and row.get("local_path"), "Backup not found.", 404, "not_found")
    path = Path(row["local_path"])
    require(path.exists(), "Local archive is missing.", 404, "not_found")
    digest = sha256_file(path)
    require(digest == row["checksum"], "Checksum does not match. Do not restore this archive.")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        require(any(n.startswith("database/") for n in names), "Archive has no database.")
    operations_sql.q_system_20805(conn, now_iso(), "Local checksum and archive contents verified.", backup_id)
    audit(conn, user, "backup_verify", "backup", "backup", backup_id, new={"checksum": digest})
    return operations_sql.q_system_21054(conn, backup_id)


def list_backups(conn) -> dict:
    return {"items": operations_sql.q_system_21169(conn)}


def restore_backup(conn, user, backup_id: str, confirm: str) -> dict:
    _refuse_file_backup(conn, "File restore")
    permit(user, "backup.restore")
    require(confirm == "RESTORE AIPF", "Type RESTORE AIPF to confirm. Restore replaces the live database.")
    row = verify_backup(conn, user, backup_id)
    path = Path(row["local_path"])
    safety = BACKUPS / f"pre-restore-{now().strftime('%Y%m%d-%H%M%S')}.zip"
    # Safety copy of the current database before replacement.
    with zipfile.ZipFile(safety, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if DB_PATH.exists():
            zf.write(DB_PATH, "database/hospital.db")
    with zipfile.ZipFile(path) as zf:
        db_name = next(n for n in zf.namelist() if n.endswith("hospital.db"))
        data = zf.read(db_name)
        for name in zf.namelist():
            if name.startswith("documents/") and not name.endswith("/"):
                target = DOCUMENTS / name.split("/", 1)[1]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))
    # Replace database file. Caller must reopen connections after this returns.
    tmp = DB_PATH.with_suffix(".restore")
    tmp.write_bytes(data)
    # Checkpoint and swap. WAL sidecars from the old file must not be reused.
    for sidecar in (Path(str(DB_PATH) + "-wal"), Path(str(DB_PATH) + "-shm")):
        if sidecar.exists():
            sidecar.unlink()
    tmp.replace(DB_PATH)
    audit(conn, user, "backup_restore", "backup", "backup", backup_id, new={"safety": str(safety)})
    return {"restored": backup_id, "safety_copy": str(safety), "message": "Database replaced. Restart the hospital server before continuing."}


def delete_backup(conn, user, backup_id: str) -> dict:
    permit(user, "backup.restore")
    row = operations_sql.q_system_23158(conn, backup_id)
    require(row, "Backup not found.", 404, "not_found")
    if row.get("local_path"):
        path = Path(row["local_path"])
        if path.exists() and path.parent.resolve() == BACKUPS.resolve():
            path.unlink()
    operations_sql.q_system_23446(conn, backup_id)
    audit(conn, user, "backup_delete", "backup", "backup", backup_id)
    return {"deleted": backup_id}


def _enforce_retention(conn):
    days = int(config_get(conn, "backup_retention_days", "30") or 30)
    max_count = int(config_get(conn, "backup_max_count", "30") or 30)
    old = operations_sql.q_system_23793(conn)
    for index, row in enumerate(old):
        if index < max_count:
            continue
        if row.get("local_path") and Path(row["local_path"]).exists():
            try:
                Path(row["local_path"]).unlink()
            except OSError:
                pass
        operations_sql.q_system_24137(conn, row["id"])


def backup_settings(conn) -> dict:
    return {
        "backup_enabled": config_get(conn, "backup_enabled", "1"),
        "backup_time": config_get(conn, "backup_time", "02:00"),
        "backup_retention_days": config_get(conn, "backup_retention_days", "30"),
        "backup_max_count": config_get(conn, "backup_max_count", "30"),
        "backup_location": str(BACKUPS),
        "cloud_provider": config_get(conn, "cloud_provider", ""),
        "cloud_endpoint": config_get(conn, "cloud_endpoint", ""),
        "cloud_bucket": config_get(conn, "cloud_bucket", ""),
        "cloud_region": config_get(conn, "cloud_region", ""),
        "cloud_prefix": config_get(conn, "cloud_prefix", "aipf"),
        "cloud_access_key": mask_secret(config_get(conn, "cloud_access_key", "")),
        "cloud_secret_key": mask_secret(config_get(conn, "cloud_secret_key", "")),
        "cloud_access_key_set": bool(config_get(conn, "cloud_access_key", "")),
        "cloud_secret_key_set": bool(config_get(conn, "cloud_secret_key", "")),
    }


def save_backup_settings(conn, user, payload: dict) -> dict:
    permit(user, "config.manage")
    for key in ("backup_enabled", "backup_time", "backup_retention_days", "backup_max_count", "cloud_provider", "cloud_endpoint", "cloud_bucket", "cloud_region", "cloud_prefix"):
        if key in payload:
            config_set(conn, key, clean_text(payload.get(key), 200), user, secret=False)
    for key in ("cloud_access_key", "cloud_secret_key"):
        if key in payload and payload.get(key) and not is_masked(payload.get(key)):
            config_set(conn, key, payload[key], user, secret=True)
    audit(conn, user, "backup_settings", "backup", "config", "backup")
    return backup_settings(conn)


def maybe_scheduled_backup(conn):
    if config_get(conn, "backup_enabled", "1") != "1":
        return
    target = config_get(conn, "backup_time", "02:00")
    current = now().strftime("%H:%M")
    if current != target:
        return
    stamp = today_str() + " " + target
    if config_get(conn, "backup_last_slot", "") == stamp:
        return
    config_set(conn, "backup_last_slot", stamp)
    create_backup(conn, None, kind="SCHEDULED")


def integration_view(conn) -> dict:
    return {
        "whatsapp": {
            "provider": config_get(conn, "wa_provider", "openwa"),
            "base_url": config_get(conn, "wa_base_url", ""),
            "api_key": mask_secret(config_get(conn, "wa_api_key", "")),
            "api_key_set": bool(config_get(conn, "wa_api_key", "")),
            "session_id": config_get(conn, "wa_session_id", ""),
            "enabled": config_get(conn, "wa_enabled", "0") == "1",
            "delay_minutes": int(config_get(conn, "whatsapp_delay_minutes", "5") or 5),
        },
        "leads": {
            "enabled": config_get(conn, "leads_enabled", "0") == "1",
            "mongo_uri": mask_secret(config_get(conn, "leads_mongo_uri", "")),
            "mongo_uri_set": bool(config_get(conn, "leads_mongo_uri", "")),
            "database": config_get(conn, "leads_database", ""),
            "collection": config_get(conn, "leads_collection", "leads"),
        },
    }


def save_whatsapp(conn, user, payload: dict) -> dict:
    permit(user, "whatsapp.configure")
    if "base_url" in payload:
        config_set(conn, "wa_base_url", clean_text(payload.get("base_url"), 300), user)
    if "session_id" in payload:
        config_set(conn, "wa_session_id", clean_text(payload.get("session_id"), 80), user)
    if "provider" in payload:
        config_set(conn, "wa_provider", clean_text(payload.get("provider") or "openwa", 40), user)
    if "enabled" in payload:
        config_set(conn, "wa_enabled", "1" if payload.get("enabled") else "0", user)
    if "delay_minutes" in payload:
        config_set(conn, "whatsapp_delay_minutes", str(int(payload.get("delay_minutes") or 5)), user)
    if payload.get("api_key") and not is_masked(payload.get("api_key")):
        config_set(conn, "wa_api_key", payload["api_key"], user, secret=True)
    audit(conn, user, "whatsapp_config", "whatsapp", "integration", "openwa")
    return integration_view(conn)["whatsapp"]


def save_leads_config(conn, user, payload: dict) -> dict:
    permit(user, "leads.manage")
    if "enabled" in payload:
        config_set(conn, "leads_enabled", "1" if payload.get("enabled") else "0", user)
    if "database" in payload:
        config_set(conn, "leads_database", clean_text(payload.get("database"), 80), user)
    if "collection" in payload:
        config_set(conn, "leads_collection", clean_text(payload.get("collection") or "leads", 80), user)
    if payload.get("mongo_uri") and not is_masked(payload.get("mongo_uri")):
        config_set(conn, "leads_mongo_uri", payload["mongo_uri"], user, secret=True)
    audit(conn, user, "leads_config", "leads", "integration", "mongodb")
    return integration_view(conn)["leads"]


def test_leads(conn) -> dict:
    uri = config_get(conn, "leads_mongo_uri", "")
    if not uri:
        return {"ok": False, "detail": "MongoDB URI is not set. The hospital continues without website leads."}
    try:
        import importlib
        pymongo = importlib.import_module("pymongo")
    except Exception:
        return {"ok": False, "detail": "The MongoDB driver is not installed on this host. Registration, OPD, pharmacy, and billing are unaffected. Install pymongo on the server only if lead sync is required."}
    try:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=4000)
        client.admin.command("ping")
        client.close()
        return {"ok": True, "detail": "Website leads database answered."}
    except Exception as exc:
        return {"ok": False, "detail": f"Could not reach MongoDB. Hospital operations continue. {exc}"}


def sync_leads(conn, user) -> dict:
    permit(user, "leads.manage")
    probe = test_leads(conn)
    if not probe.get("ok"):
        log_sync = {"synced": 0, "error": probe.get("detail")}
        audit(conn, user, "leads_sync_failed", "leads", "lead", None, new=log_sync)
        return log_sync
    try:
        import importlib
        pymongo = importlib.import_module("pymongo")
        client = pymongo.MongoClient(config_get(conn, "leads_mongo_uri", ""), serverSelectionTimeoutMS=5000)
        db_name = config_get(conn, "leads_database", "")
        coll_name = config_get(conn, "leads_collection", "leads")
        db = client[db_name] if db_name else client.get_default_database()
        count = 0
        for doc in db[coll_name].find().limit(200):
            external = str(doc.get("_id"))
            if operations_sql.q_system_30786(conn, external):
                continue
            lid = new_id("LD")
            operations_sql.q_system_30922(conn, lid, external, clean_text(doc.get("name") or doc.get("fullName"), 160), clean_text(doc.get("phone") or doc.get("mobile"), 20), clean_text(doc.get("email"), 120), clean_text(doc.get("message") or doc.get("notes"), 1000), "website", json.dumps(doc, default=str)[:4000], str(doc.get("createdAt") or now_iso()), now_iso(), now_iso())
            count += 1
        client.close()
        audit(conn, user, "leads_sync", "leads", "lead", None, new={"synced": count})
        publish("leads.updated", {"synced": count})
        return {"synced": count}
    except Exception as exc:
        return {"synced": 0, "error": str(exc)}


def list_leads(conn, status: str = "") -> dict:
    if status:
        items = operations_sql.q_system_32017(conn, status)
    else:
        items = operations_sql.q_system_32224(conn)
    return {"items": items, "total": len(items)}


def create_lead(conn, user, payload: dict) -> dict:
    permit(user, "leads.manage")
    lid = new_id("LD")
    operations_sql.q_system_32552(conn, lid, clean_text(payload.get("name"), 160), clean_text(payload.get("phone"), 20), clean_text(payload.get("email"), 120), clean_text(payload.get("message"), 1000), clean_text(payload.get("source") or "desk", 40), now_iso(), now_iso())
    audit(conn, user, "lead_create", "leads", "lead", lid)
    return operations_sql.q_system_33037(conn, lid)


def archive_lead(conn, user, lead_id: str) -> dict:
    permit(user, "leads.manage")
    operations_sql.q_system_33180(conn, lead_id)
    audit(conn, user, "lead_archive", "leads", "lead", lead_id)
    return operations_sql.q_system_33329(conn, lead_id)


def global_search(conn, q: str, user=None) -> dict:
    q = (q or "").strip()
    if len(q) < 2:
        return {"patients": [], "invoices": [], "encounters": [], "admissions": [], "products": [], "documents": [], "prescriptions": []}
    like = f"%{q.lower()}%"
    upper = f"%{q.upper()}%"
    patients = patients_sql.q_system_33662(conn, like, upper)
    invoices = billing_sql.q_system_33833(conn, f"%{q}%", f"%{q}%")
    encounters = encounters_sql.q_system_34031(conn, upper)
    admissions = ipd_sql.q_system_34179(conn, upper)
    products = inventory_sql.q_system_34288(conn, like, f"%{q}%")
    documents = documents_sql.q_system_34436(conn, like, f"%{q.upper()}%")
    prescriptions = encounters_sql.prescriptions_matching(conn, f"%{q.upper()}%")
    if user is not None:
        from .access import can_view_patient, filter_by_patient, filter_documents
        patients = [item for item in patients if can_view_patient(conn, user, item.get("id"))]
        invoices = filter_by_patient(conn, user, invoices)
        encounters = filter_by_patient(conn, user, encounters)
        admissions = filter_by_patient(conn, user, admissions)
        documents = filter_documents(conn, user, documents)
        prescriptions = filter_by_patient(conn, user, prescriptions)
        if "inventory.view" not in (user.get("permissions") or []):
            products = []
    return {"patients": patients, "invoices": invoices, "encounters": encounters, "admissions": admissions, "products": products, "documents": documents, "prescriptions": prescriptions}


def dashboard(conn, user) -> dict:
    day = today_str()
    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    revenue = payments_sql.q_system_34858(conn, day)
    outstanding = billing_sql.q_system_35097(conn)
    from .pharmacy import alerts
    stock = alerts(conn)
    health = operations_sql.q_system_35460(conn)
    last_backup = operations_sql.q_system_35557(conn)
    permissions = set((user or {}).get("permissions") or [])
    financial = "billing.view" in permissions or "report.view" in permissions
    stock_visible = "inventory.view" in permissions or "report.view" in permissions
    queue_all = "queue.view_all" in permissions
    clinical = "patient.view" in permissions or "opd.view" in permissions
    overall = (health or {}).get("overall") or ""
    if overall in ("", "UNKNOWN"):
        # A live database is not a health grade. Do not invent HEALTHY.
        overall = "UNCHECKED" if operations_sql.q_system_2010(conn) else "OFFLINE"
    hospital = dashboard_sql.hospital_beds(conn) or {}
    sample_n = int((dashboard_sql.sample_beds(conn) or {}).get("n") or 0)
    configured = int(hospital.get("total") or 0) > 0
    from .core import config_get, hospital as hospital_profile
    profile = hospital_profile(conn)
    wa_on = config_get(conn, "wa_enabled", "0") == "1" and bool(config_get(conn, "wa_base_url", "").strip())
    low = stock["low_stock"] if stock_visible else []
    expiring = stock["expiring"] if stock_visible else []
    expired = stock["expired"] if stock_visible else []
    counts = {
        "patients_today": dashboard_sql.patients_on(conn, day)["n"],
        "patients_yesterday": dashboard_sql.patients_on(conn, yesterday)["n"],
        "opd_today": dashboard_sql.opd_on(conn, day)["n"],
        "opd_yesterday": dashboard_sql.opd_on(conn, yesterday)["n"],
        "queue_waiting": dashboard_sql.queue_status(conn, "WAITING")["n"],
        "queue_consulting": dashboard_sql.queue_status(conn, "IN_CONSULTATION")["n"],
        "queue_pharmacy": dashboard_sql.queue_status(conn, "WAITING_FOR_PHARMACY")["n"],
        "queue_billing": dashboard_sql.queue_status(conn, "WAITING_FOR_BILLING")["n"],
        "revenue_paise": int((revenue or {}).get("n") or 0) if financial else 0,
        "revenue_yesterday_paise": int((payments_sql.q_system_34858(conn, yesterday) or {}).get("n") or 0) if financial else 0,
        "pending_bills": billing_sql.q_system_36398(conn)["n"] if financial else 0,
        "bills_due": dashboard_sql.bills_due(conn)["n"] if financial else 0,
        "bills_partial": dashboard_sql.bills_partial(conn)["n"] if financial else 0,
        "bills_today": dashboard_sql.bills_on(conn, day)["n"] if financial else 0,
        "bills_paid_today": dashboard_sql.bills_paid_on(conn, day)["n"] if financial else 0,
        "refunds_paise": int((dashboard_sql.refunds_on(conn, day) or {}).get("n") or 0) if financial else 0,
        "outstanding_paise": int((outstanding or {}).get("n") or 0) if financial else 0,
        "admissions_active": dashboard_sql.admissions_active(conn)["n"],
        "admissions_today": dashboard_sql.admissions_on(conn, day)["n"],
        "discharges_today": dashboard_sql.discharges_on(conn, day)["n"],
        "beds_occupied": int(hospital.get("occupied") or 0),
        "beds_available": int(hospital.get("available") or 0),
        "beds_blocked": int(hospital.get("blocked") or 0),
        "beds_total": int(hospital.get("total") or 0),
        "beds_configured": configured,
        "sample_beds": sample_n,
        "ot_today": ot_sql.q_system_36789(conn, day)["n"] if "ot.view" in permissions else 0,
        "ot_open": dashboard_sql.ot_open(conn)["n"] if "ot.view" in permissions else 0,
        "pharmacy_queue": encounters_sql.q_system_36961(conn)["n"],
        "pharmacy_issues_today": dashboard_sql.movements_on(conn, day, ("DISPENSED", "BILLING_ISSUE"))["n"] if stock_visible else 0,
        "low_stock": len(low),
        "expiring": len(expiring),
        "expired": len(expired),
        "whatsapp_queued": notifications_sql.q_system_37213(conn)["n"],
        "whatsapp_sent_today": dashboard_sql.whatsapp_on(conn, day, ("SENT",))["n"],
        "whatsapp_failed_today": dashboard_sql.whatsapp_on(conn, day, ("FAILED", "ERROR"))["n"],
        "leads_new": operations_sql.q_system_37369(conn)["n"],
        "pending_reports": lab_sql.q_system_37470(conn)["n"],
        "prescriptions_today": dashboard_sql.prescriptions_on(conn, day)["n"],
        "documents_today": dashboard_sql.documents_on(conn, day)["n"],
    }
    if "lab.view" not in permissions:
        counts["pending_reports"] = 0
    if "admission.view" not in permissions and "ipd.admission.view" not in permissions:
        counts["admissions_active"] = counts["admissions_today"] = counts["discharges_today"] = 0
    if "bed.view" not in permissions and "ipd.bed.view" not in permissions:
        counts["beds_occupied"] = counts["beds_available"] = counts["beds_blocked"] = counts["beds_total"] = counts["sample_beds"] = 0
        counts["beds_configured"] = False
    if "leads.view" not in permissions:
        counts["leads_new"] = 0
    if "whatsapp.configure" not in permissions and "whatsapp.send" not in permissions:
        counts["whatsapp_queued"] = counts["whatsapp_sent_today"] = counts["whatsapp_failed_today"] = 0
    if "document.view" not in permissions:
        counts["documents_today"] = 0
    if "pharmacy.view" not in permissions:
        counts["pharmacy_queue"] = 0
        if "queue.view" not in permissions:
            counts["queue_pharmacy"] = 0
    today_patients = []
    if clinical:
        scope_id = None if "patient.view_all" in permissions else user["id"]
        today_patients = [
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "encounter_id": row.get("encounter_id"),
                "care_code": row.get("care_code") or "ACTIVE",
                "care_label": patients_sql.CARE_LABELS.get(row.get("care_code") or "ACTIVE", "Active"),
            }
            for row in patients_sql.today_registry(conn, day, 6, scope_id)
        ]
        if "admission.view" in permissions or "ipd.admission.view" in permissions:
            counts["emergency_active"] = patients_sql.registry_summary(conn, day, scope_id)["emergency"]
    return {
        "today": day,
        "counts": counts,
        "health_overall": overall,
        "health_at": (health or {}).get("at"),
        "backup": last_backup if "backup.view" in permissions else None,
        "queue": dashboard_sql.live_queue(conn) if queue_all else [],
        "my_queue": patients_sql.q_system_37908(conn, user["id"]),
        "doctors": dashboard_sql.doctor_activity(conn) if queue_all or "opd.view" in permissions else [],
        "wards": dashboard_sql.ward_summary(conn) if configured and "admission.view" in permissions else [],
        "ot": dashboard_sql.ot_today(conn, day) if "ot.view" in permissions else [],
        "lab": dashboard_sql.lab_pending(conn) if "lab.view" in permissions else [],
        "bills": dashboard_sql.recent_bills(conn) if financial else [],
        "drafts": dashboard_sql.draft_bills(conn) if financial else [],
        "patients": dashboard_sql.recent_patients(conn) if clinical else [],
        "today_patients": today_patients,
        "documents": dashboard_sql.recent_documents(conn) if "document.view" in permissions else [],
        "activity": dashboard_sql.recent_activity(conn) if "audit.view" in permissions else [],
        "stock": {
            "low": [{"name": r.get("name"), "qty": r.get("stock")} for r in low[:4]],
            "expiring": [{"name": r.get("product_name") or r.get("name"), "expiry": r.get("expiry_date")} for r in expiring[:4]],
            "expired": [{"name": r.get("product_name") or r.get("name"), "expiry": r.get("expiry_date")} for r in expired[:4]],
        } if stock_visible else {"low": [], "expiring": [], "expired": []},
        "hospital": {"name": profile.get("name") or "", "city": profile.get("city") or ""},
        "whatsapp": {"state": "configured" if wa_on else "not_configured"},
        "scope": {
            "financial": financial,
            "stock": stock_visible,
            "queue_all": queue_all,
            "clinical": clinical,
            "backup": "backup.view" in permissions,
            "health": "health.view" in permissions,
            "whatsapp": "whatsapp.configure" in permissions or "whatsapp.send" in permissions,
            "audit": "audit.view" in permissions,
            "ot": "ot.view" in permissions,
            "lab": "lab.view" in permissions,
            "admissions": "admission.view" in permissions,
            "beds": "bed.view" in permissions,
            "documents": "document.view" in permissions,
            "pharmacy": "pharmacy.view" in permissions,
        },
    }


def daily_report(conn, day: str | None = None) -> dict:
    day = day or today_str()
    payments = payments_sql.q_system_38291(conn, day)
    return {
        "date": day,
        "patients": patients_sql.q_system_38548(conn, day)["n"],
        "opd": encounters_sql.q_system_38657(conn, day)["n"],
        "admissions": ipd_sql.q_system_38775(conn, day)["n"],
        "discharges": ipd_sql.q_system_38916(conn, day)["n"],
        "payments": payments,
        "outstanding_paise": billing_sql.q_system_39074(conn)["n"],
        "dispensed": pharmacy_sql.q_system_39192(conn, day)["n"],
        "movements": inventory_sql.q_system_39315(conn, day)["n"],
    }


def report_csv(conn, kind: str, day: str | None = None) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    if kind == "daily":
        data = daily_report(conn, day)
        writer.writerow(["metric", "value"])
        for key, value in data.items():
            if key == "payments":
                continue
            writer.writerow([key, value])
        writer.writerow([])
        writer.writerow(["mode", "kind", "amount_paise", "count"])
        for row in data["payments"]:
            writer.writerow([row["mode"], row["kind"], row["amount_paise"], row["n"]])
    elif kind == "pharmacy":
        writer.writerow(["product", "batch", "expiry", "qty", "unit"])
        for row in inventory_sql.q_system_40120(conn):
            writer.writerow([row["name"], row["batch_no"], row["expiry_date"], row["qty_on_hand"], row["unit"]])
    elif kind == "outstanding":
        writer.writerow(["invoice", "patient_id", "status", "net_paise", "paid_paise", "due_paise"])
        for row in billing_sql.q_system_40532(conn):
            writer.writerow([row["number"], row["patient_id"], row["payment_status"], row["net_paise"], row["paid_paise"], row["due_paise"]])
    elif kind == "occupancy":
        writer.writerow(["ward", "bed", "status", "patient"])
        for row in patients_sql.q_system_40931(conn):
            writer.writerow([row["ward"], row["bed"], row["status"], row["patient"] or ""])
    else:
        raise ApiError("Unknown export.")
    return buf.getvalue()


def audit_query(conn, module: str = "", user_id: str = "", action: str = "", entity: str = "", day: str = "", limit: int = 200) -> dict:
    return {"items": audit_sql.query_audit(conn, module, user_id, action, entity, day, limit)}


def logs_query(conn, module: str = "", level: str = "", limit: int = 200) -> dict:
    return {"items": audit_sql.query_logs(conn, module, level, limit)}


def onboarding(conn) -> dict:
    steps = [
        {"id": "hospital", "title": "Hospital setup", "why": "Bills, prescriptions, and the sign-in screen use this identity.", "example": "AIPF Mission Hospital, Shahpurpur, Fatehpur Beri, New Delhi 110074", "done": bool(hospital(conn).get("name") and hospital(conn).get("address_line1"))},
        {"id": "contact", "title": "Contact on the bill", "why": "Patients need a phone number on the printed bill.", "example": "The desk number patients already call.", "done": bool(hospital(conn).get("phone"))},
        {"id": "departments", "title": "Departments", "why": "OPD, doctors, and reports are grouped by department.", "example": "General Medicine, Gynecology, Orthopedics.", "done": masters_sql.q_system_43300(conn)["n"] > 0},
        {"id": "staff", "title": "Doctors and staff", "why": "Queues are assigned to a named doctor, and every action is audited to a user.", "example": "Dr Anita Rao, gynecology.", "done": users_sql.q_system_43595(conn)["n"] > 1},
        {"id": "opd", "title": "OPD configuration", "why": "Fees and validity (for example a 5-day card) come from here, not from code.", "example": "5-day OPD card, Rs 500, valid 5 days.", "done": masters_sql.q_system_43864(conn)["n"] > 0},
        {"id": "billing", "title": "Billing", "why": "Payment modes and services must be switchable without a software change.", "example": "Cash, UPI, card.", "done": masters_sql.q_system_44107(conn)["n"] > 0},
        {"id": "pharmacy", "title": "Pharmacy", "why": "Dispensing picks a real batch and writes a stock movement.", "example": "Paracetamol 500 mg, batch with expiry.", "done": inventory_sql.q_system_44392(conn)["n"] > 0},
        {"id": "inventory", "title": "Inventory", "why": "Opening stock is a ledger entry, not a typed quantity with no history.", "example": "Opening 500, dispensed 20, remaining 480.", "done": inventory_sql.q_system_44661(conn)["n"] > 0},
        {"id": "documents", "title": "Documents", "why": "Aadhaar, reports, and discharge summaries stay on this server.", "example": "Lab report PDF linked to the patient.", "done": masters_sql.q_system_44910(conn)["n"] > 0},
        {"id": "backup", "title": "Backup", "why": "A day of bills and stock must be recoverable if the disk fails.", "example": "Daily 02:00, 30-day retention, local first.", "done": operations_sql.q_system_45189(conn)["n"] > 0 or os.access(BACKUPS, os.W_OK)},
        {"id": "health", "title": "System health", "why": "The desk should see a failing disk or database before patients pile up.", "example": "Overall HEALTHY, database latency under 50 ms.", "done": True},
    ]
    done = sum(1 for step in steps if step["done"])
    return {"steps": steps, "done": done, "total": len(steps), "complete": done == len(steps)}


def update_hospital(conn, user, payload: dict) -> dict:
    permit(user, "config.manage")
    current = hospital(conn)
    fields = {
        "name": clean_text(payload.get("name") or current.get("name"), 160),
        "legal_name": clean_text(payload.get("legal_name", current.get("legal_name")), 200),
        "tagline": clean_text(payload.get("tagline", current.get("tagline")), 200),
        "address_line1": clean_text(payload.get("address_line1", current.get("address_line1")), 200),
        "address_line2": clean_text(payload.get("address_line2", current.get("address_line2")), 200),
        "city": clean_text(payload.get("city", current.get("city")), 80),
        "state": clean_text(payload.get("state", current.get("state")), 80),
        "pin": clean_text(payload.get("pin", current.get("pin")), 12),
        "phone": clean_text(payload.get("phone", current.get("phone")), 40),
        "email": clean_text(payload.get("email", current.get("email")), 120),
        "website": clean_text(payload.get("website", current.get("website")), 160),
        "registration_no": clean_text(payload.get("registration_no", current.get("registration_no")), 80),
        "updated_at": now_iso(),
    }
    masters_sql.q_system_46868(conn, fields)
    if "bill_prefix" in payload and payload["bill_prefix"]:
        config_set(conn, "bill_prefix", clean_text(payload["bill_prefix"], 30), user)
    audit(conn, user, "hospital_update", "admin", "hospital", "1", new=fields)
    return hospital(conn)


def save_logo(conn, user, data: bytes, kind: str = "primary") -> dict:
    permit(user, "config.manage")
    require(data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n", "Upload a PNG or JPEG logo.")
    require(len(data) <= 1_500_000, "Logo must be under 1.5 MB.")
    from .db import BRANDING
    ext = ".jpg" if data[:3] == b"\xff\xd8\xff" else ".png"
    name = "logo" if kind == "primary" else "logo-mono"
    path = BRANDING / f"{name}{ext}"
    path.write_bytes(data)
    column = "logo_path" if kind == "primary" else "logo_mono_path"
    masters_sql.set_logo_path(conn, column, str(path), now_iso())
    audit(conn, user, "logo_update", "admin", "hospital", "1", new={"kind": kind, "bytes": len(data)})
    return {"stored": str(path), "bytes": len(data)}


def load_demo(conn, user) -> dict:
    """Insert clearly marked sample patients. Never updates a real registration."""
    permit(user, "config.manage")
    from .clinical import save_patient

    existing = {row["name"] for row in patients_sql.sample_names(conn)}
    created = []
    skipped = []
    for spec in _DEMO_PATIENTS:
        if spec["name"] in existing:
            skipped.append(spec["name"])
            continue
        patient = save_patient(conn, user, spec, sample=1)
        if int(patient.get("is_sample") or 0) != 1:
            raise ApiError("Demo loader refused to create a record that is not marked sample.")
        created.append(patient["id"])
    audit(conn, user, "demo_load", "admin", "patient", None, new={"created": created, "skipped": skipped})
    return {
        "created": created,
        "skipped": skipped,
        "note": "These records are marked sample. Reset removes sample records only, never a real registration.",
    }


_DEMO_PATIENTS = [
    {
        "name": "DEMO Patient — not real",
        "primary_phone": "0000000101",
        "gender": "M",
        "age_at_registration": 34,
        "address": "AIPF training record only",
        "notes": "AIPF DEMO — not a real patient.",
        "guardian_name": "DEMO Guardian",
        "confirm_new": True,
    },
    {
        "name": "DEMO Patient Two — not real",
        "primary_phone": "0000000102",
        "gender": "F",
        "age_at_registration": 28,
        "address": "AIPF training record only",
        "notes": "AIPF DEMO — not a real patient.",
        "guardian_name": "DEMO Guardian",
        "confirm_new": True,
    },
]


def clear_sample(conn, user) -> dict:
    permit(user, "config.manage")
    ids = [r["id"] for r in patients_sql.q_system_48408(conn)]
    if not ids:
        return {"removed_patients": 0}
    from .storage import get_storage

    stored = operations_sql.purge_sample_patients(conn, ids)
    storage = get_storage()
    for key in stored:
        if key and storage.exists(key):
            storage.delete(key)
    audit(conn, user, "sample_clear", "admin", "patient", None, new={"removed": ids})
    return {"removed_patients": len(ids)}


def listening_port() -> int | None:
    # Informational only.
    return None
