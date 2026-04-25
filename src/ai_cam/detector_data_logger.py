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
            buffer_secs=self.config.buffer_secs
        )

        # EMA state
        self.ema_confidence = 0.0
        self.ema_alpha = self.config.ema_alpha          # e.g. 0.2
        self.event_threshold = self.config.event_threshold  # e.g. 0.4

        # Event state
        self.in_event = False
        self.peak_confidence = 0.0
        self.peak_frame = None
        self.peak_timestamp = None
        self.peak_detections = None

    def _handle_shutdown(self, signum, frame):
        logging.info(f"Shutdown signal received ({signum}), cleaning up...")
        self._running = False

    def _update_ema(self, detections) -> float:
        """Update EMA with the best confidence score from this frame, or 0 if no detections."""
        if detections:
            best_score = max(d.score for d in detections)
        else:
            best_score = 0.0
        self.ema_confidence = (
            self.ema_alpha * best_score
            + (1 - self.ema_alpha) * self.ema_confidence
        )
        return self.ema_confidence

    def _on_event_start(self, detections, frame, timestamp):
        logging.info(f"Event started — EMA confidence: {self.ema_confidence:.2f}")
        self.in_event = True
        self.peak_confidence = self.ema_confidence
        self.peak_frame = frame.copy()
        self.peak_timestamp = timestamp
        self.peak_detections = detections

        # Save the trigger frame
        self.data_logger.log_results(detections, frame, timestamp, frame_type="event_start")

        if self.config.save_video:
            self.camera.start_video_recording()

    def _on_event_update(self, detections, frame, timestamp):
        """Track the peak confidence frame during an event."""
        if self.ema_confidence > self.peak_confidence:
            self.peak_confidence = self.ema_confidence
            self.peak_frame = frame.copy()
            self.peak_timestamp = timestamp
            self.peak_detections = detections

    def _on_event_end(self, detections, frame, timestamp):
        logging.info(f"Event ended — peak EMA confidence was: {self.peak_confidence:.2f}")

        # Save peak frame
        if self.peak_frame is not None:
            self.data_logger.log_results(
                self.peak_detections, self.peak_frame,
                self.peak_timestamp, frame_type="event_peak"
            )

        # Save the final frame
        self.data_logger.log_results(detections or self.peak_detections, frame, timestamp, frame_type="event_end")

        if self.config.save_video:
            self.camera.stop_video_recording()

        # Reset
        self.in_event = False
        self.peak_confidence = 0.0
        self.peak_frame = None
        self.peak_timestamp = None
        self.peak_detections = None

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

                ema = self._update_ema(detections)
                logging.debug(f"EMA confidence: {ema:.3f}")

                # Event state machine
                if not self.in_event and ema >= self.event_threshold:
                    self._on_event_start(detections, frame, timestamp)
                    encoding = True
                elif self.in_event and ema >= self.event_threshold:
                    self._on_event_update(detections, frame, timestamp)
                elif self.in_event and ema < self.event_threshold:
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