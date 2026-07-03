import time
import signal
import logging
import sys
from datetime import datetime
from libcamera import Rectangle
from typing import Optional, List, Tuple

import sdnotify

from ai_cam.data_loggers import DataLogger
from ai_cam.config import CamConfig
from ai_cam.imx500_detector import IMX500Yolo
from ai_cam.csi_camera import CameraCSI
from ai_cam.utils import DetectionResultYOLO, BoundingBox


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
        logging.info(f"Shutdown signal received ({signum}), cleaning up...")
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
            # logging.info(f"DET: {cls_name}: {scores_this_frame.get(cls_name, 0.0):.2f}")
            # logging.info(f"EMA: {cls_name}: {self.ema_per_class[cls_name]}")

    def _classes_above_threshold(self) -> list[str]:
        return [
            cls_name for cls_name, ema in self.ema_per_class.items()
            if ema >= self.event_activate
        ]

    def _all_classes_deactive(self) -> list[str]:
        deactive = True
        for cls_name, ema in self.ema_per_class.items():
            if ema >= self.event_deactivate:
                deactive = False
                
        return deactive

    def _on_event_start(self, detections, frame, timestamp, active_classes):
        logging.info(f"Event started — active classes: {active_classes}")
        self.in_event = True

        # Initialise peak tracking for each active class
        all_classes = []
        for cls_name in active_classes:
            self.peak_per_class[cls_name] = {
                "ema": self.ema_per_class[cls_name],
                "frame": frame.copy(),
                "timestamp": timestamp,
                "detections": detections
            }
            all_classes.append(cls_name)

        all_classes = "_".join(set(all_classes))
        self.data_logger.log_results(detections, frame, timestamp, frame_type=f"event_start{all_classes}")

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
        logging.info(f"Event ended — saving peaks for: {list(self.peak_per_class.keys())}")

        # Save best frame per species
        for cls_name, peak in self.peak_per_class.items():
            self.data_logger.log_results(
                peak["detections"], peak["frame"],
                peak["timestamp"], frame_type=f"event_peak_{cls_name}"
            )

        if self.config.save_video:
            self.camera.stop_video_recording()

        # Reset event state
        self.in_event = False
        self.peak_per_class = {}

    def _bbox_to_sensor_coords(self, bbox: BoundingBox, roi: Rectangle) -> Tuple[float, float, float, float]:
        """Map a bbox normalized [0, 1] within `roi` into absolute sensor pixel coords."""
        x0 = roi.x + bbox.xmin * roi.width
        y0 = roi.y + bbox.ymin * roi.height
        x1 = roi.x + bbox.xmax * roi.width
        y1 = roi.y + bbox.ymax * roi.height
        return x0, y0, x1, y1

    def _rescale_detections_to_roi(
        self, detections: List[DetectionResultYOLO], source_roi: Rectangle, target_roi: Rectangle
    ) -> List[DetectionResultYOLO]:
        """
        Re-express detections normalized within `source_roi` (e.g. a zoomed-in
        inference crop) as bboxes normalized within `target_roi` (e.g. the
        original full-frame ROI), so they line up with frames/detections
        captured under `target_roi`. Detections with no overlap are dropped;
        partial overlaps are clamped into [0, 1].
        """
        rescaled = []
        for d in detections:
            sx0, sy0, sx1, sy1 = self._bbox_to_sensor_coords(d.bbox, source_roi)

            nx0 = (sx0 - target_roi.x) / target_roi.width
            ny0 = (sy0 - target_roi.y) / target_roi.height
            nx1 = (sx1 - target_roi.x) / target_roi.width
            ny1 = (sy1 - target_roi.y) / target_roi.height

            if nx1 <= 0 or ny1 <= 0 or nx0 >= 1 or ny0 >= 1:
                continue  # no overlap with the target frame at all

            rescaled.append(DetectionResultYOLO(
                score=d.score,
                class_name=d.class_name,
                bbox=BoundingBox(
                    xmin=max(0.0, nx0), ymin=max(0.0, ny0),
                    xmax=min(1.0, nx1), ymax=min(1.0, ny1),
                )
            ))
        return rescaled


    def focus_on_detection(
        self,
        detection: DetectionResultYOLO,
        metadata: dict,
        zoom_margin: float = 1.4,
        settle_frames: int = 5,
    ):
        """
        Temporarily narrow the IMX500 inference ROI to zoom in on a specific
        detection, capture one fresh frame + detection pass at that tighter
        crop, then restore the ROI that was active beforehand.

        Returned detections are rescaled back into full-frame normalized
        coordinates, so they can be drawn on / compared against the original
        (non-zoomed) frame and detections directly.
        """
        full_sensor = Rectangle(0, 0, 4056, 3040)

        request = self.camera.picam2.capture_request()
        curr_scaled_roi = self.detector.yolo_model.get_roi_scaled(request)
        request.release()
        logging.debug(f"OLD ROI: {curr_scaled_roi}")

        # Reproject the triggering detection's bbox into sensor pixel coords.
        scaler_crop = Rectangle(*metadata['ScalerCrop'])
        det_x0, det_y0, det_x1, det_y1 = self._bbox_to_sensor_coords(detection.bbox, scaler_crop)

        det_w = max(det_x1 - det_x0, 1)
        det_h = max(det_y1 - det_y0, 1)
        center_x = det_x0 + det_w / 2
        center_y = det_y0 + det_h / 2

        logging.debug(f"Sensor Coords: {center_x}/{center_y}, {det_h}/{det_w}")

        # Pad, then stretch the short dimension to match the model's input
        # aspect ratio, so the zoom doesn't squash the image.
        model_aspect = 640 / 480
        padded_w = det_w * zoom_margin
        padded_h = det_h * zoom_margin
        if padded_w / padded_h > model_aspect:
            padded_h = padded_w / model_aspect
        else:
            padded_w = padded_h * model_aspect

        new_roi = Rectangle(
            int(center_x - padded_w / 2),
            int(center_y - padded_h / 2),
            int(padded_w),
            int(padded_h),
        ).bounded_to(full_sensor)

        self.detector.yolo_model.set_inference_roi_abs(new_roi.to_tuple())
        
        request = self.camera.picam2.capture_request()
        curr_scaled_roi = self.detector.yolo_model.get_roi_scaled(request)
        request.release()
        logging.debug(f"New ROI: {curr_scaled_roi}")

        time.sleep(0.25)

        zoom_frame, zoomed_detections = None, None
        try:
            timeout = 0
            while zoomed_detections is None:
                zoom_frame_out, zoom_metadata = self.camera.get_frames()
                zoomed_detections = self.detector.get_detections(zoom_metadata)

                timeout += 1

                if timeout > settle_frames:
                    break

            if zoomed_detections:
                zoomed_detections = self._rescale_detections_to_roi(
                    zoomed_detections, source_roi=new_roi, target_roi=full_sensor
                )

            zoom_frame = zoom_frame_out[
                curr_scaled_roi[1] : curr_scaled_roi[1] + curr_scaled_roi[3], 
                curr_scaled_roi[0] : curr_scaled_roi[0] + curr_scaled_roi[2]]

        finally:
            self.detector.yolo_model.set_inference_roi_abs(full_sensor.to_tuple())

            time.sleep(0.25)


        return zoomed_detections, zoom_frame

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

                detection_results = self.detector.get_detections(metadata)

                # if detection_results is none, then NO inference results is provided
                # "no detections" will result in an empty list
                if detection_results is not None:
                    zoom_detection_results = []
                    zoom_frame = None
                    for detection in detection_results:
                        zoom_dets, zoom_frame = self.focus_on_detection(detection, metadata)

                        if zoom_dets is not None:
                            zoom_detection_results += zoom_dets

                    if len(zoom_detection_results) > 0:
                        detection_results = zoom_detection_results

                    if self.config.draw_bbox:
                        self.camera.update_detections(detection_results)

                    self._update_ema(detection_results)
                    logging.debug(f"EMA per class: { {c: f'{v:.3f}' for c, v in self.ema_per_class.items()} }")

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
            logging.info("Shutting down...")
            if self.config.save_video and encoding:
                self.camera.stop_video_recording()
            self.camera.stop_camera()
            logging.info("Camera closed cleanly.")