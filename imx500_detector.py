from picamera2.devices import IMX500
from picamera2.devices.imx500 import (NetworkIntrinsics,
                                      postprocess_nanodet_detection)
from picamera2 import Metadata

import logging
from typing import Optional, List
import numpy as np
from libcamera import Rectangle, Size

from utils import DetectionResultYOLO, apply_nms, read_class_list


class IMX500Yolo:
    def __init__(self, model_path: str, labels_path: str, valid_classes_path: str, confidence: float,
                 iou_threshold: float):
        self.valid_classes_path = valid_classes_path
        self.confidence = confidence
        self.iou_threshold = iou_threshold

        self.logger = logging.getLogger(__name__)

        self.yolo_model = IMX500(model_path)
        self.intrinsics = self.yolo_model.network_intrinsics

        if not self.intrinsics:
            self.intrinsics = NetworkIntrinsics()
            self.intrinsics.task = "object detection"

        logging.info(f"postprocess: {self.intrinsics.postprocess}")

        self.yolo_model.show_network_fw_progress_bar()
        model_w, model_h = self.yolo_model.get_input_size()

        self.model_wh = (model_w, model_h)
        self.sensor_resolution = (4056, 3040)
        self.raw_resolution = (4056 // 2, 3040 // 2)

        # Load class names and valid classes
        self.class_names = read_class_list(labels_path)
        if self.valid_classes_path:
            self.valid_classes = read_class_list(self.valid_classes_path)
            logging.info(f"Monitoring for classes: {', '.join(sorted(self.valid_classes))}")
        else:
            self.valid_classes = None
            logging.info(f"Monitoring all classes")

        self.logger.info("Model initialized!")
        self.logger.info(f"Model input shape HxW: {model_h}, {model_w}")

    def get_scaled_obj(self, obj, isp_output_size, scaler_crop) -> Rectangle:
        """Scale the object coordinates based on the camera configuration and sensor properties."""

        obj_bound = obj.bounded_to(scaler_crop)
        obj_translated = obj_bound.translated_by(-scaler_crop.topLeft)
        obj_scaled = obj_translated.scaled_by(isp_output_size, scaler_crop.size)

        return obj_scaled

    def convert_inference_coords(self, coords: tuple, metadata: dict) -> tuple:
        """Convert relative inference coordinates into the output image coordinates space.
        The image passed to the YOLO model is a scaled version of the raw sensor data
        However, the output video stream from the camera is a crop and scaled version of the sensor image!
        So we need to do some funky transformations to make the model output line up with the video stream....
        This is mainly copied from picamera2/picamera2/devices/imx500/imx500.py
        """

        isp_output_size = Size(self.model_wh[0], self.model_wh[1])
        scaler_crop = Rectangle(*metadata['ScalerCrop'])

        x0, y0, x1, y1 = coords
        full_sensor = Rectangle(0, 0, 4056, 3040)
        width, height = full_sensor.size.to_tuple()
        obj = Rectangle(
            *np.maximum(
                np.array([x0 * width, y0 * height, (x1 - x0) * width, (y1 - y0) * height]),
                0,
            ).astype(np.int32)
        )
        out = self.get_scaled_obj(obj, isp_output_size, scaler_crop)
        return out.to_tuple()

    def extract_detections(self, np_outputs: np.ndarray, metadata: dict) -> Optional[List[DetectionResultYOLO]]:
        """Extract detections from the IMX500 output."""
        if np_outputs:
            boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]

            results = []
            for box, score, category in zip(boxes, scores, classes):
                score = float(score)
                if score >= self.confidence:

                    class_name = self.class_names[int(category)]
                    if self.valid_classes and class_name not in self.valid_classes:
                        continue

                    x0, y0, x1, y1 = box

                    bbox = (float(x0) / self.model_wh[0], float(y0) / self.model_wh[1],
                            float(x1) / self.model_wh[0], float(y1) / self.model_wh[1])

                    bbox_xy_wh = self.convert_inference_coords(bbox, metadata)

                    box = {"xmin": bbox_xy_wh[0] / self.model_wh[0],
                           "ymin": bbox_xy_wh[1] / self.model_wh[1],
                           "xmax": (bbox_xy_wh[0] + bbox_xy_wh[2]) / self.model_wh[0],
                           "ymax": (bbox_xy_wh[1] + bbox_xy_wh[3]) / self.model_wh[1]}

                    detection = {"score": round(score, 4),
                                 "class_name": class_name,
                                 "bbox": box}

                    results.append(DetectionResultYOLO.from_dict(detection))
                    logging.info(f"- {x0}, {y0}, {x1} {y1}: score {score}")

            if len(results) > 0:
                unique_results = apply_nms(results, nms_threshold=self.iou_threshold)
                return unique_results
            else:
                return None
        else:
            return None

    def get_detections(self, metadata: Metadata) -> Optional[List[DetectionResultYOLO]]:
        results = self.yolo_model.get_outputs(metadata, add_batch=True)

        # Extract and process detections
        detections = self.extract_detections(results, metadata)

        if detections:
            logging.info(f"Detected {len(detections)}")
            for detection in detections:
                class_name = detection.class_name
                score = detection.score
                logging.info(f"- {class_name} with confidence {score:.2f}")

        return detections



