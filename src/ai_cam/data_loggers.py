from datetime import datetime
import numpy as np

import os
import logging
import json
import cv2

import ai_cam.utils as utils

class DataLogger:
    def __init__(self, device_name: str, output_dir: str, save_data: bool,
                 save_images: bool, draw_bbox: bool, auto_select_media: bool):

        self.logger = logging.getLogger(__name__)

        self.device_name = device_name
        self.save_images = save_images
        self.draw_bbox = draw_bbox
        self.save_data = save_data

        self.logger.info("Saving images: %s, detection data: %s", self.save_images, self.save_data)

        if auto_select_media:
            usb_path = utils.find_first_usb_drive()
            if usb_path is None:
                self.data_output = output_dir
                self.logger.warning("No drive mounted under /media: saving to %s instead", output_dir)
            else:
                self.data_output = os.path.join(usb_path, "output")
                self.logger.info("Using the drive mounted at %s", usb_path)
        else:
            self.data_output = output_dir

        self.logger.info("Saving outputs to %s", self.data_output)

        # Create output directories
        os.makedirs(self.data_output, exist_ok=True)
        self.image_detections_path = os.path.join(self.data_output, "images")
        os.makedirs(self.image_detections_path, exist_ok=True)

        self.json_detections_path = os.path.join(self.data_output, "detections")
        os.makedirs(self.json_detections_path, exist_ok=True)

    def _save_img(self, detection_list, frame, timestamp, frame_type):
        if self.draw_bbox:
            try:
                frame = utils.draw_detections(detection_list, frame)
            except Exception as e:
                self.logger.warning("Couldn't draw the detections: %s", e)

        timestamp_str = timestamp.strftime("%Y%m%d-%H%M%S-%f")[:-3]
        filename = f"{self.device_name}_{frame_type}_{timestamp_str}.jpg"

        # Save the frame locally
        image_path = os.path.join(self.image_detections_path, filename)
        try:
            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ok = cv2.imwrite(image_path, image_rgb)
            if not ok:
                self.logger.warning("Couldn't save the image %s", image_path)
        except Exception as e:
            self.logger.warning("Couldn't save the image %s: %s", image_path, e)

    def _to_json(self, detection_list, filename):
        json_path = os.path.join(self.json_detections_path, f"{filename}.json")
        try:
            with open(json_path, 'w') as f:
                json.dump(detection_list, f, indent=2)

        except Exception as e:
            self.logger.warning("Couldn't save the detections %s: %s", json_path, e)

    def log_data(self, detection_list, timestamp, log_type):

        timestamp_str = timestamp.strftime("%Y%m%d-%H%M%S-%f")[:-3]
        # filename with timestamp with only the first 3 digits of the microseconds (milliseconds)
        filename = f"{self.device_name}_{log_type}_{timestamp_str}"

        # Convert detection objects to dict
        detection_dict_list = [detection.to_dict() for detection in detection_list]

        self._to_json(detection_dict_list, filename)

    def log_results(self, detection_list, frame, timestamp, frame_type: str = "detection"):
        if self.save_images:
            self._save_img(detection_list, frame, timestamp, frame_type=frame_type)
            
        if self.save_data:
            self.log_data(detection_list, timestamp, log_type=frame_type)
