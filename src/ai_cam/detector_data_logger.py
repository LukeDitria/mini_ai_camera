
import time
import cv2
from datetime import datetime
import logging
import sys
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
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.StreamHandler(sys.stderr)
            ]
        )
        logging.info("Capture Box Awake!")
        self.n = sdnotify.SystemdNotifier()

        self.config = config
        logging.info(self.config.model)

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

        self.no_detection_run = self.config.buffer_secs * self.config.ips

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

    def run(self):
        detections_run = 0
        no_detections_run = 0
        encoding = False

        seconds_per_frame = 1 / self.config.ips
        last_frame_time = time.time()
        last_heartbeat_time = time.time()
        last_log_time = time.time()

        seconds_per_log = (1 / self.config.lps) if self.config.lps else 0

        logging.info("Wait for startup!")
        time.sleep(2)
        logging.info("Starting!")

        self.n.notify("READY=1")

        while True:
            timestamp = datetime.now().astimezone()

            frame, metadata = self.camera.get_frames()
            if frame is None:
                continue

            data_list = self.detector.get_detections(metadata)

            if data_list:
                if seconds_per_log == 0 or time.time() - last_log_time >= seconds_per_log:
                    last_log_time = time.time()
                    self.data_logger.log_results(data_list, frame, timestamp)

                detections_run += 1
                no_detections_run = 0
            else:
                no_detections_run += 1
                detections_run = 0

            if self.config.save_video:
                if detections_run == self.config.detection_run and not encoding:
                    self.camera.start_video_recording()
                    encoding = True
                elif encoding and no_detections_run == self.no_detection_run:
                    self.camera.stop_video_recording()
                    encoding = False

            time_diff = time.time() - last_frame_time
            wait_time = max(0, seconds_per_frame - time_diff)
            time.sleep(wait_time)
            last_frame_time = time.time()

            if time.time() - last_heartbeat_time >= 10:
                last_heartbeat_time = time.time()
                self.n.notify("WATCHDOG=1")


def main():
    config = CamConfig()
    config = config.from_file(config.config_file)
    logger = DetectorLogger(config=config)
    logger.run()


if __name__ == "__main__":
    main()