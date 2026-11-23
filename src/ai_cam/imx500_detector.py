import logging
import time

from libcamera import Rectangle
from picamera2.devices import IMX500
from picamera2.devices.imx500 import NetworkIntrinsics

from ai_cam.utils import BoundingBox, DetectionResultYOLO, apply_nms, read_class_list

_logger = logging.getLogger(__name__)

FULL_SENSOR = Rectangle(0, 0, 4056, 3040)


class IMX500Yolo:
    def __init__(
        self, model_path: str, labels_path: str, valid_classes_path: str, confidence: float, iou_threshold: float
    ):
        self.valid_classes_path = valid_classes_path
        self.confidence = confidence
        self.iou_threshold = iou_threshold

        self.yolo_model = IMX500(model_path)
        self.intrinsics = self.yolo_model.network_intrinsics

        if not self.intrinsics:
            self.intrinsics = NetworkIntrinsics()
            self.intrinsics.task = "object detection"

        self.intrinsics.update_with_defaults()

        self.network_ips = int(self.intrinsics.inference_rate)
        _logger.info("Inference rate: %s, postprocess: %s", self.network_ips, self.intrinsics.postprocess)

        self.yolo_model.show_network_fw_progress_bar()
        model_w, model_h = self.yolo_model.get_input_size()
        self.model_wh = (model_w, model_h)

        # The inference ROI (sensor pixels) and when it was last changed: frames exposed before then
        # were inferred with the previous one.
        self.roi = FULL_SENSOR
        self.roi_set_ns = 0
        self.yolo_model.set_inference_roi_abs(self.roi.to_tuple())

        # Load class names and valid classes
        self.class_names = read_class_list(labels_path)
        if self.valid_classes_path:
            self.valid_classes = read_class_list(self.valid_classes_path)
            _logger.info("Monitoring for classes: %s", ", ".join(sorted(self.valid_classes)))
        else:
            self.valid_classes = None
            _logger.info("Monitoring all classes")

        _logger.info("Model initialized, input shape HxW: %s, %s", model_h, model_w)

    def set_roi(self, roi: Rectangle) -> None:
        """Run inference on `roi` (sensor pixels) from the next frames on. Frames already exposed
        were inferred with the previous ROI: see roi_in_effect()."""
        self.roi = roi.bounded_to(FULL_SENSOR)
        self.yolo_model.set_inference_roi_abs(self.roi.to_tuple())
        self.roi_set_ns = time.monotonic_ns()

    def roi_in_effect(self, metadata: dict) -> bool:
        """Whether this frame has model output and was exposed after the last ROI change."""
        return metadata.get("CnnOutputTensor") is not None and metadata.get("SensorTimestamp", 0) > self.roi_set_ns

    def to_frame_box(self, box: tuple, roi: Rectangle, scaler_crop: Rectangle) -> BoundingBox | None:
        """Map a box in model-input pixels to one normalized to the video frame.

        The model sees `roi` stretched to its input size, so its boxes are relative to the ROI. The
        video frame shows `scaler_crop` of the sensor. None when the box is outside the frame.
        """
        model_w, model_h = self.model_wh
        x0, y0, x1, y1 = box
        sx0 = roi.x + x0 / model_w * roi.width
        sy0 = roi.y + y0 / model_h * roi.height
        sx1 = roi.x + x1 / model_w * roi.width
        sy1 = roi.y + y1 / model_h * roi.height

        nx0 = (sx0 - scaler_crop.x) / scaler_crop.width
        ny0 = (sy0 - scaler_crop.y) / scaler_crop.height
        nx1 = (sx1 - scaler_crop.x) / scaler_crop.width
        ny1 = (sy1 - scaler_crop.y) / scaler_crop.height
        if nx1 <= 0 or ny1 <= 0 or nx0 >= 1 or ny0 >= 1:
            return None
        return BoundingBox(xmin=max(0.0, nx0), ymin=max(0.0, ny0), xmax=min(1.0, nx1), ymax=min(1.0, ny1))

    def extract_detections(
        self, np_outputs, roi: Rectangle, scaler_crop: Rectangle
    ) -> list[DetectionResultYOLO] | None:
        """Extract detections from the IMX500 output, as boxes normalized to the video frame."""
        if not np_outputs:
            return None

        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]
        results = []
        for box, score, category in zip(boxes, scores, classes, strict=False):
            score = float(score)
            if score < self.confidence:
                continue

            class_name = self.class_names[int(category)]
            if self.valid_classes and class_name not in self.valid_classes:
                continue

            frame_box = self.to_frame_box(tuple(float(v) for v in box), roi, scaler_crop)
            if frame_box is None:
                continue
            results.append(DetectionResultYOLO(score=round(score, 4), class_name=class_name, bbox=frame_box))
            _logger.debug("- %s: score %s", box, score)

        return apply_nms(results, nms_threshold=self.iou_threshold) if results else []

    def get_detections(self, metadata: dict, roi: Rectangle | None = None) -> list[DetectionResultYOLO] | None:
        """Detections in this frame, None when it has no model output. `roi` is the ROI the frame was
        inferred with (the full sensor unless given)."""
        results = self.yolo_model.get_outputs(metadata, add_batch=True)
        if not results:
            _logger.debug("No model output")

        detections = self.extract_detections(results, roi or FULL_SENSOR, Rectangle(*metadata["ScalerCrop"]))
        for detection in detections or []:
            _logger.debug("- %s with confidence %.2f", detection.class_name, detection.score)
        return detections
