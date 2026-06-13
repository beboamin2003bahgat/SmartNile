"""
managers/ai_manager.py
======================
Runs the plant-detection AI pipeline on frames from CameraManager.

Supported inference backends (auto-detected at start())
--------------------------------------------------------
1. TFLite (preferred on RPi 5)
   - Model: models/plant_detect.tflite
   - Uses the tflite-runtime package (lightweight, no full TF needed)
   - Input: 320×320 or 640×640 RGB float32 normalised 0–1
   - Output: boxes [1, N, 4], classes [1, N], scores [1, N]

2. Ultralytics YOLOv8 (if installed and YOLO_BACKEND=yolo in .env)
   - Model: models/plant_detect.pt  or  plant_detect.onnx
   - Higher accuracy, higher CPU load (~3 fps on RPi 5 at 640×480)
   - Recommended to use YOLOv8n (nano) for edge deployment

3. Simulation (SIMULATION_MODE=True)
   - Returns synthetic detections with realistic confidence and positions
   - Useful for testing the full pipeline without a camera or model file

Detection classes (must match model label order)
-------------------------------------------------
0 — Water Hyacinth (Eichhornia crassipes)
1 — Water Lettuce  (Pistia stratiotes)
2 — Algae Bloom
3 — Unknown Plant

Debouncing
----------
The same species is not reported more than once every DETECTION_DEBOUNCE
seconds to avoid flooding Firebase with frames of the same plant patch.
"""

import random
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np  # type: ignore

from config.settings import settings
from managers.camera_manager import CameraManager
from managers.gps_manager import GPSManager
from utils.logger import get_logger
from utils.validators import DetectionResult, now

log = get_logger("ai_manager")

# maps model output class index → DetectionResult.SPECIES key
_CLASS_NAMES = {
    0: "water_hyacinth",
    1: "water_lettuce",
    2: "algae_bloom",
    3: "unknown_plant",
}
_NILE_INVASIVE = {0, 1}   # classes that trigger a critical-level alert


class AIManager:
    def __init__(
        self,
        camera:   CameraManager,
        gps:      GPSManager,
        on_detection: Optional[Callable[[DetectionResult], None]] = None,
    ):
        self._camera      = camera
        self._gps         = gps
        self._on_detect   = on_detection
        self._sim         = settings.SIMULATION_MODE
        self._conf_thresh = settings.MODEL_CONFIDENCE
        self._debounce    = settings.DETECTION_DEBOUNCE
        self._model_path  = settings.MODEL_PATH
        self._mission_id  = settings.MISSION_ID

        self._lock        = threading.Lock()
        self._running     = False
        self._thread: Optional[threading.Thread] = None

        # debounce: last detection time per class
        self._last_detect: Dict[int, float] = {}

        # stats
        self._total_frames    = 0
        self._total_detections = 0

        # model handles
        self._tflite_interpreter = None
        self._yolo_model          = None
        self._backend             = "none"

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self._sim:
            self._load_model()
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, name="AILoop", daemon=True
        )
        self._thread.start()
        log.info(f"[AIManager] Started (backend={self._backend}, sim={self._sim})")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        log.info("[AIManager] Stopped")

    # ── public API ────────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {
            "running":           self._running,
            "simulation":        self._sim,
            "backend":           self._backend,
            "model_path":        self._model_path,
            "confidence_thresh": self._conf_thresh,
            "total_frames":      self._total_frames,
            "total_detections":  self._total_detections,
        }

    # ── inference loop ────────────────────────────────────────────────────────
    def _loop(self) -> None:
        interval = 1.0 / max(1, settings.CAMERA_FPS)
        while self._running:
            start = time.time()
            try:
                if self._sim:
                    self._maybe_sim_detect()
                else:
                    frame = self._camera.get_frame()
                    if frame is not None:
                        self._total_frames += 1
                        detections = self._run_inference(frame)
                        for det in detections:
                            self._handle_detection(det, frame)
            except Exception as exc:
                log.error(f"[AIManager] Loop error: {exc}", exc_info=True)

            elapsed = time.time() - start
            time.sleep(max(0.0, interval - elapsed))

    # ── model loading ─────────────────────────────────────────────────────────
    def _load_model(self) -> None:
        path = Path(self._model_path)
        if not path.exists():
            log.warning(f"[AIManager] Model not found at {path}. Detection disabled.")
            return

        backend_env = __import__("os").environ.get("YOLO_BACKEND", "tflite").lower()

        if backend_env == "yolo":
            self._load_yolo(path)
        else:
            self._load_tflite(path)

    def _load_tflite(self, path: Path) -> None:
        try:
            try:
                from tflite_runtime.interpreter import Interpreter  # type: ignore
            except ImportError:
                import tensorflow as tf  # type: ignore
                Interpreter = tf.lite.Interpreter

            interp = Interpreter(model_path=str(path))
            interp.allocate_tensors()
            self._tflite_interpreter = interp
            self._backend = "tflite"
            log.info(f"[AIManager] TFLite model loaded: {path.name}")
        except Exception as exc:
            log.error(f"[AIManager] TFLite load failed: {exc}")

    def _load_yolo(self, path: Path) -> None:
        try:
            from ultralytics import YOLO  # type: ignore
            self._yolo_model = YOLO(str(path))
            self._backend    = "yolo"
            log.info(f"[AIManager] YOLO model loaded: {path.name}")
        except Exception as exc:
            log.error(f"[AIManager] YOLO load failed: {exc}")

    # ── inference ─────────────────────────────────────────────────────────────
    def _run_inference(self, frame: np.ndarray) -> List[DetectionResult]:
        if self._backend == "tflite":
            return self._infer_tflite(frame)
        if self._backend == "yolo":
            return self._infer_yolo(frame)
        return []

    def _infer_tflite(self, frame: np.ndarray) -> List[DetectionResult]:
        results = []
        try:
            import cv2  # type: ignore
            interp = self._tflite_interpreter
            in_details  = interp.get_input_details()
            out_details = interp.get_output_details()

            # pre-process
            h = in_details[0]["shape"][1]
            w = in_details[0]["shape"][2]
            resized = cv2.resize(frame, (w, h))
            rgb     = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            tensor  = np.expand_dims(rgb.astype(np.float32) / 255.0, axis=0)

            interp.set_tensor(in_details[0]["index"], tensor)
            interp.invoke()

            boxes   = interp.get_tensor(out_details[0]["index"])[0]
            classes = interp.get_tensor(out_details[1]["index"])[0]
            scores  = interp.get_tensor(out_details[2]["index"])[0]

            fix = self._gps.get_latest()
            for i, score in enumerate(scores):
                if score < self._conf_thresh:
                    continue
                cls_id = int(classes[i])
                ymin, xmin, ymax, xmax = boxes[i]
                results.append(DetectionResult(
                    timestamp   = now(),
                    species_id  = cls_id,
                    confidence  = round(float(score), 4),
                    bounding_box= {
                        "x": int(xmin * frame.shape[1]),
                        "y": int(ymin * frame.shape[0]),
                        "w": int((xmax - xmin) * frame.shape[1]),
                        "h": int((ymax - ymin) * frame.shape[0]),
                    },
                    latitude    = fix.latitude  if fix else None,
                    longitude   = fix.longitude if fix else None,
                    mission_id  = self._mission_id,
                ))
        except Exception as exc:
            log.error(f"[AIManager] TFLite inference error: {exc}")
        return results

    def _infer_yolo(self, frame: np.ndarray) -> List[DetectionResult]:
        results = []
        try:
            import cv2  # type: ignore
            preds = self._yolo_model.predict(
                frame,
                conf=self._conf_thresh,
                verbose=False,
            )
            fix = self._gps.get_latest()
            for pred in preds:
                for box in pred.boxes:
                    cls_id = int(box.cls[0])
                    conf   = float(box.conf[0])
                    x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                    results.append(DetectionResult(
                        timestamp   = now(),
                        species_id  = cls_id,
                        confidence  = round(conf, 4),
                        bounding_box= {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
                        latitude    = fix.latitude  if fix else None,
                        longitude   = fix.longitude if fix else None,
                        mission_id  = self._mission_id,
                    ))
        except Exception as exc:
            log.error(f"[AIManager] YOLO inference error: {exc}")
        return results

    # ── detection handling ────────────────────────────────────────────────────
    def _handle_detection(self, det: DetectionResult, frame: np.ndarray) -> None:
        # debounce per species
        last = self._last_detect.get(det.species_id, 0)
        if (now() - last) < self._debounce:
            return

        self._last_detect[det.species_id] = now()
        self._total_detections += 1

        # save snapshot
        path = self._camera.save_snapshot(
            frame, det.species_name, det.confidence,
            det.latitude, det.longitude,
        )
        det.frame_path = path

        log.info(
            f"[AIManager] Detection: {det.species_name} @ {det.confidence:.0%}  "
            f"lat={det.latitude} lon={det.longitude}"
        )

        if self._on_detect:
            self._on_detect(det)

    # ── simulation ────────────────────────────────────────────────────────────
    def _maybe_sim_detect(self) -> None:
        """Randomly generate a plant detection every ~30 seconds."""
        if random.random() > (1.0 / (30.0 / max(0.1, 1.0 / settings.CAMERA_FPS))):
            return
        fix     = self._gps.get_latest()
        cls_id  = random.choice([0, 1, 0, 0, 1])  # weighted toward hyacinth
        conf    = round(random.uniform(0.62, 0.97), 4)
        det = DetectionResult(
            timestamp   = now(),
            species_id  = cls_id,
            confidence  = conf,
            bounding_box= {"x": 120, "y": 80, "w": 200, "h": 150},
            frame_path  = None,
            latitude    = fix.latitude  if fix else 30.05,
            longitude   = fix.longitude if fix else 31.23,
            mission_id  = self._mission_id,
        )

        last = self._last_detect.get(cls_id, 0)
        if (now() - last) < self._debounce:
            return
        self._last_detect[cls_id] = now()
        self._total_detections += 1
        log.info(f"[AIManager] Simulated detection: {det.species_name} @ {conf:.0%}")
        if self._on_detect:
            self._on_detect(det)
