import time
import signal
import logging
from datetime import datetime
from libcamera import Rectangle
from typing import Optional, List

import sdnotify

from ai_cam.data_loggers import DataLogger
from ai_cam.imx500_detector import FULL_SENSOR, IMX500Yolo
from ai_cam.csi_camera import CameraCSI
from ai_cam.utils import BoundingBox, DetectionResultYOLO, apply_nms, name_part

_logger = logging.getLogger(__name__)


class DetectorLogger:
    def __init__(self, config):
        _logger.info("Capture Box Awake!")
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
            fps=self.detector.network_ips,
            camera_num=self.detector.yolo_model.camera_num,
            draw_bbox=self.config.draw_bbox,
        )

        # EMA state
        self.ema_per_class: dict[str, float] = {}
        self.ema_alpha = self.config.ema_alpha
        self.event_activate = self.config.event_activate
        self.event_deactivate = self.config.event_deactivate

        # Event state
        self.in_event = False
        self.peak_per_class: dict[str, dict] = {}

    def _handle_shutdown(self, signum, frame):
        _logger.info("Shutdown signal received (%s), cleaning up...", signum)
        self._running = False

    def _update_ema(self, detections: Optional[List[DetectionResultYOLO]]) -> None:
        """Update per-class EMA. Classes with no detection this frame decay toward 0."""
        scores_this_frame: dict[str, float] = {}
        if detections:
            for d in detections:
                if d.class_name not in scores_this_frame or d.score > scores_this_frame[d.class_name]:
                    scores_this_frame[d.class_name] = d.score

        all_classes = set(self.ema_per_class) | set(scores_this_frame)
        for cls_name in all_classes:
            current_score = scores_this_frame.get(cls_name, 0.0)
            prev_ema = self.ema_per_class.get(cls_name, 0.0)

            self.ema_per_class[cls_name] = (
                self.ema_alpha * current_score
                + (1 - self.ema_alpha) * prev_ema
            )

    def _classes_above_threshold(self) -> list[str]:
        return [
            cls_name for cls_name, ema in self.ema_per_class.items()
            if ema >= self.event_activate
        ]

    def _all_classes_deactive(self) -> bool:
        deactive = True
        for cls_name, ema in self.ema_per_class.items():
            if ema >= self.event_deactivate:
                deactive = False
                
        return deactive

    def _on_event_start(self, detections, frame, timestamp, active_classes):
        _logger.info("Event started, active classes: %s", active_classes)
        self.in_event = True

        # Initialise peak tracking for each active class
        for cls_name in active_classes:
            self.peak_per_class[cls_name] = {
                "ema": self.ema_per_class[cls_name],
                "frame": frame.copy(),
                "timestamp": timestamp,
                "detections": detections
            }

        all_classes = name_part(active_classes)
        self.data_logger.log_results(detections, frame, timestamp, frame_type=f"event_start_{all_classes}")

        if self.config.save_video:
            self.camera.start_video_recording(all_classes)

    def _on_event_update(self, detections, frame, timestamp):
        for cls_name, ema in self.ema_per_class.items():
            if ema < self.event_deactivate:
                continue
            if cls_name not in self.peak_per_class or ema > self.peak_per_class[cls_name]["ema"]:
                self.peak_per_class[cls_name] = {
                    "ema": ema,
                    "frame": frame.copy(),
                    "timestamp": timestamp,
                    "detections": detections
                }

    def _on_event_end(self, detections, frame, timestamp):
        _logger.info("Event ended, saving peaks for: %s", list(self.peak_per_class.keys()))

        # Save best frame per species
        for cls_name, peak in self.peak_per_class.items():
            self.data_logger.log_results(
                peak["detections"], peak["frame"],
                peak["timestamp"], frame_type=f"event_peak_{name_part([cls_name])}"
            )

        if self.config.save_video:
            self.camera.stop_video_recording()

        # Reset event state
        self.in_event = False
        self.peak_per_class = {}

    def _wait_for_roi(self):
        """The first usable frame inferred with the ROI just set, or (None, None) after
        zoom_timeout_secs. Frames reach us some time after they're exposed, so the ones already on
        their way still have the old ROI: skip those, then one more inference as a margin (the
        sensor sometimes takes one more frame to apply it)."""
        started = time.monotonic()
        skipped = inferences = 0
        while time.monotonic() - started < self.config.zoom_timeout_secs:
            frame, metadata = self.camera.get_frames()
            if self.detector.roi_in_effect(metadata):
                inferences += 1
                if inferences >= 2:
                    _logger.debug("ROI in effect after %.0f ms, %s frames skipped",
                                  (time.monotonic() - started) * 1000, skipped)
                    return frame, metadata
            skipped += 1
        _logger.debug("ROI not in effect after %s s", self.config.zoom_timeout_secs)
        return None, None

    def _zoom_roi(self, bbox: BoundingBox, scaler_crop: Rectangle, zoom_margin: float = 1.4) -> Rectangle:
        """A sensor ROI around a box (normalized to the video frame), padded by `zoom_margin` and
        widened to the model's aspect ratio so the zoomed image isn't squashed."""
        x0 = scaler_crop.x + bbox.xmin * scaler_crop.width
        y0 = scaler_crop.y + bbox.ymin * scaler_crop.height
        w = max((bbox.xmax - bbox.xmin) * scaler_crop.width, 1) * zoom_margin
        h = max((bbox.ymax - bbox.ymin) * scaler_crop.height, 1) * zoom_margin
        model_w, model_h = self.detector.model_wh
        if w / h > model_w / model_h:
            h = w * model_h / model_w
        else:
            w = h * model_w / model_h
        cx = x0 + (bbox.xmax - bbox.xmin) * scaler_crop.width / 2
        cy = y0 + (bbox.ymax - bbox.ymin) * scaler_crop.height / 2
        return Rectangle(int(cx - w / 2), int(cy - h / 2), int(w), int(h)).bounded_to(FULL_SENSOR)

    def _save_zoom(self, detections, frame, metadata, roi, timestamp, class_name):
        """Save the zoomed part of the frame, with the detections relative to it."""
        crop = self.detector.to_frame_box((0, 0, *self.detector.model_wh), roi, Rectangle(*metadata["ScalerCrop"]))
        if crop is None:
            return
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = int(crop.xmin * w), int(crop.ymin * h), int(crop.xmax * w), int(crop.ymax * h)
        if x1 <= x0 or y1 <= y0:
            return
        cw, ch = crop.xmax - crop.xmin, crop.ymax - crop.ymin
        relative = [
            DetectionResultYOLO(score=d.score, class_name=d.class_name, bbox=BoundingBox(
                xmin=(d.bbox.xmin - crop.xmin) / cw, ymin=(d.bbox.ymin - crop.ymin) / ch,
                xmax=(d.bbox.xmax - crop.xmin) / cw, ymax=(d.bbox.ymax - crop.ymin) / ch))
            for d in detections
        ]
        self.data_logger.log_results(relative, frame[y0:y1, x0:x1].copy(), timestamp,
                                     frame_type=f"zoom_{name_part([class_name])}")

    def check_with_zoom(self, detections: list[DetectionResultYOLO], metadata: dict, timestamp) -> list[DetectionResultYOLO]:
        """Re-check each detection under zoom_below with the camera's inference zoomed in on it.

        A zoomed view that finds something replaces the detection with what it found; one that
        finds nothing drops it; one that gets no answer in time keeps it. The full view is restored
        afterwards, once, however many detections were checked.
        """
        uncertain = [d for d in detections if d.score < self.config.zoom_below]
        if not uncertain:
            return detections

        scaler_crop = Rectangle(*metadata["ScalerCrop"])
        checked = [d for d in detections if d.score >= self.config.zoom_below]
        try:
            for detection in uncertain:
                roi = self._zoom_roi(detection.bbox, scaler_crop)
                _logger.debug("Zooming in on %s (%.2f): ROI %s", detection.class_name, detection.score, roi)
                self.detector.set_roi(roi)
                zoom_frame, zoom_metadata = self._wait_for_roi()
                zoomed = self.detector.get_detections(zoom_metadata, roi) if zoom_metadata is not None else None
                if zoomed is None:
                    checked.append(detection)
                    continue
                checked += zoomed
                if zoomed and self.config.save_zoom_images:
                    self._save_zoom(zoomed, zoom_frame, zoom_metadata, roi, timestamp, detection.class_name)
        finally:
            self.detector.set_roi(FULL_SENSOR)
            self._wait_for_roi()

        return apply_nms(checked, nms_threshold=self.detector.iou_threshold)

    def run(self):
        self._running = True

        seconds_per_frame = 1 / self.config.ips
        last_frame_time = time.time()
        last_heartbeat_time = time.time()

        _logger.info("Waiting for startup...")
        time.sleep(2)
        _logger.info("Starting!")
        self.n.notify("READY=1")

        encoding = False

        try:
            while self._running:
                timestamp = datetime.now().astimezone()

                frame, metadata = self.camera.get_frames()
                if frame is None:
                    continue

                detection_results = self.detector.get_detections(metadata)

                # if detection_results is none, then NO inference results is provided
                # "no detections" will result in an empty list
                if detection_results is not None:
                    if self.config.zoom_to_roi and detection_results:
                        detection_results = self.check_with_zoom(detection_results, metadata, timestamp)

                    if self.config.draw_bbox:
                        self.camera.update_detections(detection_results)

                    self._update_ema(detection_results)
                    _logger.debug("EMA per class: %s", {c: round(v, 3) for c, v in self.ema_per_class.items()})

                    # Event state machine
                    if not self.in_event:
                        active_classes = self._classes_above_threshold()
                        if active_classes:
                            self._on_event_start(detection_results, frame, timestamp, active_classes)
                            encoding = True
                    else:
                        if self._all_classes_deactive():
                            self._on_event_end(detection_results, frame, timestamp)
                            encoding = False
                        else:
                            self._on_event_update(detection_results, frame, timestamp)

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
            _logger.info("Shutting down...")
            if self.config.save_video and encoding:
                self.camera.stop_video_recording()
            self.camera.stop_camera()
            _logger.info("Camera closed cleanly.")