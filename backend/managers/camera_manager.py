"""
managers/camera_manager.py
==========================
Manages the Raspberry Pi camera module (or USB webcam) using OpenCV.

Responsibilities
----------------
1. Opens the camera and maintains a capture loop on a background thread
2. Exposes get_frame() for the AIManager to pull the latest frame
3. Saves detection snapshots as JPEG files with GPS coordinates embedded
   in the filename
4. Provides a simple MJPEG frame generator for optional local preview
   (useful during field calibration)

Camera setup on Raspberry Pi 5
-------------------------------
Option A — Camera Module v2 / v3 (recommended):
    sudo apt install python3-picamera2
    Use Picamera2 backend (set CAMERA_BACKEND=picamera2 in .env)

Option B — USB webcam or HDMI capture card:
    Uses standard OpenCV VideoCapture(index)
    Set CAMERA_INDEX=0 (or 1 for second device) in .env

This manager detects which backend to use at open() time.
"""

import io
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np   # type: ignore

from config.settings import settings
from utils.logger import get_logger

log = get_logger("camera_manager")

_BACKENDS = ("opencv", "picamera2")


class CameraManager:
    def __init__(self):
        self._backend     = os.environ.get("CAMERA_BACKEND", "opencv").lower()
        self._sim         = settings.SIMULATION_MODE
        self._width       = settings.CAMERA_WIDTH
        self._height      = settings.CAMERA_HEIGHT
        self._fps         = settings.CAMERA_FPS
        self._snapshots   = Path(settings.SNAPSHOTS_DIR)
        self._snapshots.mkdir(parents=True, exist_ok=True)

        self._lock        = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_count = 0
        self._running     = False
        self._thread: Optional[threading.Thread] = None
        self._cap         = None   # cv2.VideoCapture or Picamera2 instance

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._sim:
            log.info("[Camera] Simulation mode — synthetic frames will be generated")
            self._running = True
            self._thread = threading.Thread(
                target=self._sim_loop, name="CameraSimLoop", daemon=True
            )
            self._thread.start()
            return

        opened = False
        if self._backend == "picamera2":
            opened = self._open_picamera2()
        if not opened:
            opened = self._open_opencv()
        if not opened:
            log.error("[Camera] No camera available. Video detection disabled.")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, name="CameraLoop", daemon=True
        )
        self._thread.start()
        log.info(f"[Camera] Started ({self._width}×{self._height} @ {self._fps} fps)")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._release()
        log.info("[Camera] Stopped")

    # ── public API ────────────────────────────────────────────────────────────
    def get_frame(self) -> Optional[np.ndarray]:
        """Returns a copy of the latest captured frame (BGR, uint8)."""
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def save_snapshot(
        self,
        frame: np.ndarray,
        label: str,
        confidence: float,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
    ) -> str:
        """
        Save a JPEG snapshot to disk.
        Returns the absolute path of the saved file.
        """
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        geo = f"_{lat:.5f}_{lon:.5f}" if (lat and lon) else ""
        conf_str = f"{int(confidence * 100):02d}pct"
        filename = f"{ts}_{label}_{conf_str}{geo}.jpg"
        path = self._snapshots / filename

        try:
            import cv2  # type: ignore
            cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            log.info(f"[Camera] Snapshot saved: {filename}")
        except Exception as exc:
            log.error(f"[Camera] Failed to save snapshot: {exc}")

        return str(path)

    def status(self) -> dict:
        return {
            "running":      self._running,
            "simulation":   self._sim,
            "backend":      self._backend,
            "resolution":   f"{self._width}x{self._height}",
            "fps":          self._fps,
            "frames_total": self._frame_count,
            "has_frame":    self._latest_frame is not None,
        }

    # ── capture loops ─────────────────────────────────────────────────────────
    def _capture_loop(self) -> None:
        interval = 1.0 / self._fps
        while self._running:
            start = time.time()
            frame = self._grab_frame()
            if frame is not None:
                with self._lock:
                    self._latest_frame = frame
                    self._frame_count += 1
            elapsed = time.time() - start
            time.sleep(max(0.0, interval - elapsed))

    def _grab_frame(self) -> Optional[np.ndarray]:
        """Works for both OpenCV and Picamera2."""
        try:
            if self._backend == "picamera2" and self._cap is not None:
                return self._cap.capture_array()
            if self._cap is not None:
                ret, frame = self._cap.read()
                return frame if ret else None
        except Exception as exc:
            log.warning(f"[Camera] Grab error: {exc}")
        return None

    def _sim_loop(self) -> None:
        """Generates synthetic noise frames at the configured FPS."""
        interval = 1.0 / self._fps
        while self._running:
            # random green-ish frame simulating river surface
            frame = np.random.randint(
                low=[0, 80, 0], high=[80, 180, 80],
                size=(self._height, self._width, 3),
                dtype=np.uint8,
            )
            with self._lock:
                self._latest_frame = frame
                self._frame_count += 1
            time.sleep(interval)

    # ── backend openers ───────────────────────────────────────────────────────
    def _open_opencv(self) -> bool:
        try:
            import cv2  # type: ignore
            cap = cv2.VideoCapture(settings.CAMERA_INDEX)
            if not cap.isOpened():
                log.warning("[Camera] OpenCV could not open camera index %d", settings.CAMERA_INDEX)
                return False
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            cap.set(cv2.CAP_PROP_FPS,          self._fps)
            self._cap     = cap
            self._backend = "opencv"
            log.info("[Camera] OpenCV backend ready")
            return True
        except ImportError:
            log.warning("[Camera] cv2 not installed")
            return False

    def _open_picamera2(self) -> bool:
        try:
            from picamera2 import Picamera2  # type: ignore
            cam = Picamera2()
            config = cam.create_preview_configuration(
                main={"size": (self._width, self._height), "format": "BGR888"}
            )
            cam.configure(config)
            cam.start()
            self._cap     = cam
            self._backend = "picamera2"
            log.info("[Camera] Picamera2 backend ready")
            return True
        except Exception as exc:
            log.warning(f"[Camera] Picamera2 unavailable: {exc}")
            return False

    def _release(self) -> None:
        try:
            if self._cap:
                if self._backend == "picamera2":
                    self._cap.stop()
                else:
                    self._cap.release()
        except Exception as exc:
            log.warning(f"[Camera] Release error: {exc}")
        self._cap = None
