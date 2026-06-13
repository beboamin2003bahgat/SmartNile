"""
managers/firebase_manager.py
============================
Handles all communication with Google Firebase:
  - Firestore document writes (sensors, GPS, alerts, detections, missions)
  - Firebase Storage uploads (detection snapshots)
  - Offline buffer flush: queued SQLite rows are pushed when connection resumes
  - Real-time heartbeat document so the dashboard knows the boat is alive

Firestore collection layout
----------------------------
smartnile/
├── missions/{mission_id}
│     └── (meta: start time, status, boat name)
├── sensors/{auto_id}
│     └── SensorReading fields + mission_id
├── gps/{auto_id}
│     └── GPSFix fields + mission_id
├── alerts/{auto_id}
│     └── AlertEvent fields + mission_id
├── detections/{auto_id}
│     └── DetectionResult fields + storage_url + mission_id
└── heartbeat/boat
      └── {timestamp, status, mission_id}

Firebase Storage layout
-----------------------
snapshots/{mission_id}/{detection_id}.jpg

Thread safety
-------------
All public push_*() methods are called from different manager threads.
They enqueue work into a thread-safe queue; a single writer thread
drains it to avoid Firestore rate-limit collisions.
"""

import json
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import settings
from utils.buffer import OfflineBuffer
from utils.logger import get_logger
from utils.validators import AlertEvent, DetectionResult, GPSFix, SensorReading, now

log = get_logger("firebase_manager")

_HEARTBEAT_INTERVAL = 15.0   # seconds between alive pings
_FLUSH_INTERVAL     = settings.FIREBASE_FLUSH_INTERVAL
_BATCH_SIZE         = settings.FIREBASE_BATCH_SIZE


class _WriteJob:
    """Internal queue item."""
    __slots__ = ("collection", "data", "doc_id", "is_storage", "local_path", "storage_path")

    def __init__(
        self,
        collection: str,
        data: Dict[str, Any],
        doc_id: Optional[str] = None,
        is_storage: bool = False,
        local_path: Optional[str] = None,
        storage_path: Optional[str] = None,
    ):
        self.collection   = collection
        self.data         = data
        self.doc_id       = doc_id
        self.is_storage   = is_storage
        self.local_path   = local_path
        self.storage_path = storage_path


class FirebaseManager:
    def __init__(self):
        self._sim        = settings.SIMULATION_MODE
        self._mission_id = settings.MISSION_ID
        self._project_id = settings.FIREBASE_PROJECT_ID
        self._creds_path = settings.FIREBASE_CREDENTIALS_PATH
        self._bucket     = settings.FIREBASE_STORAGE_BUCKET

        self._db      = None   # firestore.Client
        self._storage = None   # storage.Bucket
        self._connected = False

        self._write_q: queue.Queue[_WriteJob] = queue.Queue(maxsize=2000)
        self._buffer  = OfflineBuffer(settings.SQLITE_PATH)

        self._running = False
        self._writer_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

        # stats
        self._total_writes  = 0
        self._failed_writes = 0
        self._queued        = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self._sim:
            self._connect()
        self._running = True

        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="FirebaseWriter",
            daemon=True,
        )
        self._writer_thread.start()

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="FirebaseHeartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

        self._register_mission()
        log.info(
            "[Firebase] Started (connected=%s, simulation=%s)",
            self._connected, self._sim,
        )

    def stop(self) -> None:
        log.info("[Firebase] Stopping — draining write queue...")
        self._running = False

        # drain what we can
        timeout = time.time() + 10
        while not self._write_q.empty() and time.time() < timeout:
            time.sleep(0.1)

        if self._writer_thread:
            self._writer_thread.join(timeout=5)
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=3)

        self._buffer.close()
        pending = self._buffer.pending_count() if hasattr(self._buffer, 'pending_count') else 0
        log.info(f"[Firebase] Stopped. {pending} rows remain in offline buffer.")

    # ── public push API (called from manager callbacks) ────────────────────────
    def push_sensor(self, reading: SensorReading) -> None:
        self._enqueue(_WriteJob(collection="sensors", data=reading.to_dict()))

    def push_gps(self, fix: GPSFix) -> None:
        self._enqueue(_WriteJob(collection="gps", data=fix.to_dict()))

    def push_alert(self, alert: AlertEvent) -> None:
        self._enqueue(_WriteJob(collection="alerts", data=alert.to_dict()))

    def push_detection(self, det: DetectionResult) -> None:
        data = det.to_dict()
        job  = _WriteJob(collection="detections", data=data)

        # if there's a local snapshot, also schedule a Storage upload
        if det.frame_path and Path(det.frame_path).exists():
            storage_path = f"snapshots/{self._mission_id}/{Path(det.frame_path).name}"
            upload_job = _WriteJob(
                collection   = "detections",
                data         = data,
                is_storage   = True,
                local_path   = det.frame_path,
                storage_path = storage_path,
            )
            self._enqueue(upload_job)
        else:
            self._enqueue(job)

    def push_heartbeat(self, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "timestamp":  now(),
            "mission_id": self._mission_id,
            "status":     "online",
            "utc":        datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            payload.update(extra)
        # heartbeat is a set (not add) — overwrites the single doc
        job = _WriteJob(
            collection="heartbeat",
            data=payload,
            doc_id="boat",
        )
        self._enqueue(job)

    def status(self) -> dict:
        return {
            "connected":     self._connected,
            "simulation":    self._sim,
            "queue_size":    self._write_q.qsize(),
            "total_writes":  self._total_writes,
            "failed_writes": self._failed_writes,
            "offline_buffer_rows": self._buffer.pending_count(),
        }

    # ── writer loop ───────────────────────────────────────────────────────────
    def _writer_loop(self) -> None:
        last_flush = time.time()

        while self._running or not self._write_q.empty():
            # flush offline buffer periodically when connected
            if self._connected and (time.time() - last_flush) >= _FLUSH_INTERVAL:
                ok, fail = self._buffer.flush(self._sync_write)
                last_flush = time.time()

            # drain up to BATCH_SIZE items from the live queue
            batch_count = 0
            while batch_count < _BATCH_SIZE:
                try:
                    job = self._write_q.get(timeout=0.5)
                except queue.Empty:
                    break

                success = self._execute_job(job)
                self._write_q.task_done()
                batch_count += 1

                if success:
                    self._total_writes += 1
                else:
                    self._failed_writes += 1
                    # send to offline buffer for retry
                    self._buffer.enqueue(job.collection, job.data)

    def _execute_job(self, job: _WriteJob) -> bool:
        if self._sim:
            # simulation: just log, pretend success
            log.debug(f"[Firebase][SIM] {job.collection}: {list(job.data.keys())}")
            return True

        if not self._connected:
            return False   # goes to offline buffer

        try:
            if job.is_storage:
                return self._upload_file(job)
            else:
                return self._sync_write(job.collection, job.data, job.doc_id)
        except Exception as exc:
            log.error(f"[Firebase] Execute error ({job.collection}): {exc}")
            return False

    # ── Firestore write ───────────────────────────────────────────────────────
    def _sync_write(
        self,
        collection: str,
        data: Dict[str, Any],
        doc_id: Optional[str] = None,
    ) -> bool:
        """
        Write one document to Firestore.
        If doc_id is given → set() (upsert).
        Otherwise → add() (auto-ID).
        Returns True on success.
        """
        try:
            col_ref = self._db.collection(collection)
            if doc_id:
                col_ref.document(doc_id).set(data)
            else:
                col_ref.add(data)
            return True
        except Exception as exc:
            log.error(f"[Firebase] Firestore write failed ({collection}): {exc}")
            return False

    # ── Storage upload ────────────────────────────────────────────────────────
    def _upload_file(self, job: _WriteJob) -> bool:
        try:
            blob = self._storage.blob(job.storage_path)
            blob.upload_from_filename(job.local_path, content_type="image/jpeg")
            url = blob.public_url

            # update the detection document with the storage URL
            job.data["storage_url"] = url
            job.is_storage = False
            return self._sync_write("detections", job.data)
        except Exception as exc:
            log.error(f"[Firebase] Storage upload failed: {exc}")
            return False

    # ── heartbeat loop ────────────────────────────────────────────────────────
    def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                self.push_heartbeat()
            except Exception as exc:
                log.debug(f"[Firebase] Heartbeat error: {exc}")
            time.sleep(_HEARTBEAT_INTERVAL)

    # ── mission registration ──────────────────────────────────────────────────
    def _register_mission(self) -> None:
        mission_doc = {
            "mission_id":  self._mission_id,
            "start_time":  now(),
            "start_utc":   datetime.now(timezone.utc).isoformat(),
            "status":      "active",
            "boat":        "SmartNile-01",
            "location":    "Nile River, Egypt",
        }
        job = _WriteJob(
            collection="missions",
            data=mission_doc,
            doc_id=self._mission_id,
        )
        self._enqueue(job)

    # ── Firebase SDK init ─────────────────────────────────────────────────────
    def _connect(self) -> None:
        try:
            import firebase_admin  # type: ignore
            from firebase_admin import credentials, firestore, storage  # type: ignore

            creds_path = self._creds_path
            if not Path(creds_path).exists():
                log.error(
                    f"[Firebase] Credentials file not found: {creds_path}\n"
                    "  → Download from Firebase Console → Project Settings → Service Accounts"
                )
                return

            if not firebase_admin._apps:
                cred = credentials.Certificate(creds_path)
                firebase_admin.initialize_app(cred, {
                    "storageBucket": self._bucket,
                    "databaseURL":   settings.FIREBASE_DATABASE_URL,
                })

            self._db      = firestore.client()
            self._storage = storage.bucket()
            self._connected = True
            log.info(f"[Firebase] Connected to project: {self._project_id}")

        except ImportError:
            log.error(
                "[Firebase] firebase-admin not installed.\n"
                "  → pip install firebase-admin --break-system-packages"
            )
        except Exception as exc:
            log.error(f"[Firebase] Connection failed: {exc}")
            self._connected = False

    # ── helpers ───────────────────────────────────────────────────────────────
    def _enqueue(self, job: _WriteJob) -> None:
        try:
            self._write_q.put_nowait(job)
        except queue.Full:
            # queue full — send directly to offline buffer
            log.warning("[Firebase] Write queue full — routing to offline buffer")
            self._buffer.enqueue(job.collection, job.data)
