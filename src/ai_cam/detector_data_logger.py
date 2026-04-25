import time
import signal
import logging
import sys
from datetime import datetime

import sdnotify

from ai_cam.data_loggers import DataLogger
from ai_cam.config import CamConfig
from ai_cam.imx500_detector import IMX500Yolo
from ai_cam.csi_camera import CameraCSI


class DetectorLogger:
    def __init__(self, config):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            stream=sys.stdout
        )
        logging.info("Capture Box Awake!")
        self.n = sdnotify.SystemdNotifier()
        self._running = False

        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        self.config = config

        self.detector = IMX500Yolo(
            model_path=self.config.model,
            labels_path=self.config.labels,
            valid_classes_path=self.config.valid_classes,
            confidence=self.config.confidence,
            iou_threshold=self.config.iou_threshold
        )

        self.data_logger = DataLogger(
            device_name=self.config.device_name,
            output_dir=self.config.output_dir,
            save_data=self.config.save_data,
            save_images=self.config.save_images,
            draw_bbox=self.config.draw_bbox,
            auto_select_media=self.config.auto_select_media
        )

        if isinstance(self.config.video_size, str):
            self.video_w, self.video_h = map(int, self.config.video_size.split(','))
        else:
            self.video_w, self.video_h = self.config.video_size

        self.camera = CameraCSI(
            device_name=self.config.device_name,
            video_wh=(self.video_w, self.video_h),
            save_video=self.config.save_video,
            data_output=self.data_logger.data_output,
            buffer_secs=self.config.buffer_secs,
            fps=self.data_logger.network_ips
        )

        # EMA state
        self.ema_per_class: dict[str, float] = {}
        self.ema_alpha = self.config.ema_alpha
        self.event_threshold = self.config.event_threshold

        # Event state
        self.in_event = False
        self.peak_per_class: dict[str, dict] = {}

    def _handle_shutdown(self, signum, frame):
        logging.info(f"Shutdown signal received ({signum}), cleaning up...")
        self._running = False

    def _update_ema(self, detections) -> dict[str, float]:
        """Update per-class EMA. Classes with no detection this frame decay toward 0."""
        scores_this_frame: dict[str, float] = {}
        if detections:
            for d in detections:
                if d.class_name not in scores_this_frame or d.score > scores_this_frame[d.class_name]:
                    scores_this_frame[d.class_name] = d.score

        all_classes = set(self.ema_per_class) | set(scores_this_frame)
        for cls in all_classes:
            current_score = scores_this_frame.get(cls, 0.0)
            prev_ema = self.ema_per_class.get(cls, 0.0)

            self.ema_per_class[cls] = (
                self.ema_alpha * current_score
                + (1 - self.ema_alpha) * prev_ema
            )

        return self.ema_per_class

    def _classes_above_threshold(self) -> list[str]:
        return [
            cls for cls, ema in self.ema_per_class.items()
            if ema >= self.event_threshold
        ]

    def _on_event_start(self, detections, frame, timestamp, active_classes):
        logging.info(f"Event started — active classes: {active_classes}")
        self.in_event = True

        # Initialise peak tracking for each active class
        for cls in active_classes:
            self.peak_per_class[cls] = {
                "ema": self.ema_per_class[cls],
                "frame": frame.copy(),
                "timestamp": timestamp,
                "detections": detections
            }

        self.data_logger.log_results(detections, frame, timestamp, frame_type="event_start")

        if self.config.save_video:
            self.camera.start_video_recording()

    def _on_event_update(self, detections, frame, timestamp):
        for cls, ema in self.ema_per_class.items():
            if ema < self.event_threshold:
                continue
            if cls not in self.peak_per_class or ema > self.peak_per_class[cls]["ema"]:
                self.peak_per_class[cls] = {
                    "ema": ema,
                    "frame": frame.copy(),
                    "timestamp": timestamp,
                    "detections": detections
                }

    def _on_event_end(self, detections, frame, timestamp):
        logging.info(f"Event ended — saving peaks for: {list(self.peak_per_class.keys())}")

        # Save best frame per species
        for cls, peak in self.peak_per_class.items():
            self.data_logger.log_results(
                peak["detections"], peak["frame"],
                peak["timestamp"], frame_type=f"event_peak_{cls}"
            )

        if self.config.save_video:
            self.camera.stop_video_recording()

        # Reset event state
        self.in_event = False
        self.peak_per_class = {}

    def run(self):
        self._running = True

        seconds_per_frame = 1 / self.config.ips
        last_frame_time = time.time()
        last_heartbeat_time = time.time()

        logging.info("Waiting for startup...")
        time.sleep(2)
        logging.info("Starting!")
        self.n.notify("READY=1")

        encoding = False

        try:
            while self._running:
                timestamp = datetime.now().astimezone()

                frame, metadata = self.camera.get_frames()
                if frame is None:
                    continue

                detections = self.detector.get_detections(metadata)

                # Always save raw detection data every frame
                if detections and self.config.save_data:
                    self.data_logger.log_data(detections, timestamp, log_type="raw")

                ema_per_class = self._update_ema(detections)
                active_classes = self._classes_above_threshold()

                logging.info(f"EMA per class: { {c: f'{v:.3f}' for c, v in ema_per_class.items()} }")

                # Event state machine
                if not self.in_event and active_classes:
                    self._on_event_start(detections, frame, timestamp, active_classes)
                    encoding = True
                elif self.in_event and active_classes:
                    self._on_event_update(detections, frame, timestamp)
                elif self.in_event and not active_classes:
                    self._on_event_end(detections, frame, timestamp)
                    encoding = False

                # Frame timing
                time_diff = time.time() - last_frame_time
                wait_time = max(0, seconds_per_frame - time_diff)
                time.sleep(wait_time)
                last_frame_time = time.time()

                # Systemd watchdog
                if time.time() - last_heartbeat_time >= 10:
                    last_heartbeat_time = time.time()
                    self.n.notify("WATCHDOG=1")

        finally:
            logging.info("Shutting down...")
            if self.config.save_video and encoding:
                self.camera.stop_video_recording()
            self.camera.stop_camera()
            logging.info("Camera closed cleanly.")