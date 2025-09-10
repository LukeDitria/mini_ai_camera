import time
import cv2
from datetime import datetime
import logging
import sys
import sdnotify

from data_loggers import DataLogger
import get_args
from imx500_detector import IMX500Yolo
from csi_camera import CameraCSI

class DetectorLogger:
    def __init__(self):
        # Set up logging to stdout (systemd will handle redirection)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(sys.stdout),  # Logs go to stdout (captured by systemd)
                logging.StreamHandler(sys.stderr)  # Warnings and errors go to stderr
            ]
        )
        logging.info("Capture Box Awake!")

        self.n = sdnotify.SystemdNotifier()

        # First parse command line arguments with all defaults
        self.args = get_args.parse_arguments()
                
        self.detector = IMX500Yolo(model_path=self.args.model, labels_path=self.args.labels,
                                    valid_classes_path=self.args.valid_classes, confidence=self.args.confidence,
                                    iou_threshold=self.args.iou_threshold)

        self.data_logger = DataLogger(device_name=self.args.device_name, output_dir=self.args.output_dir,
                                      save_data=self.args.save_data, save_images=self.args.save_images,
                                      draw_bbox=self.args.draw_bbox,
                                      auto_select_media=self.args.auto_select_media)

        self.no_detection_run = self.args.buffer_secs * self.args.ips

            # Parse video size
        if isinstance(self.args.video_size, str):
            self.video_w, self.video_h = map(int, self.args.video_size.split(','))
        else:
            # Handle case where video_size might be a list/tuple in the JSON
            self.video_w, self.video_h = self.args.video_size

        self.camera = CameraCSI(
            device_name=self.args.device_name, video_wh=(self.video_w, self.video_h),
            save_video=self.args.save_video, data_output=self.data_logger.data_output,
            buffer_secs=self.args.buffer_secs)

        # Tell systemd we've started successfully
        self.n.notify("READY=1")

    def run_detection(self):
        detections_run = 0
        no_detections_run = 0
        encoding = False

        seconds_per_frame = 1/self.args.ips
        last_frame_time = time.time()
        last_heartbeat_time = time.time()
        last_log_time = time.time()

        if self.args.lps is not None:
            seconds_per_log = 1/self.args.lps
        else:
            seconds_per_log = 0

        logging.info("Wait for startup!")
        time.sleep(2)
        logging.info("Starting!")
        while True:
            # Generate timestamp
            timestamp = datetime.now().astimezone()

            # Capture and process frame
            frame, metadata = self.camera.get_frames()
            if frame is None:
                continue

            data_list = self.detector.get_detections(metadata)

            if data_list:
                if time.time() - last_log_time >= seconds_per_log:
                    last_log_time = time.time()
                    self.data_logger.log_results(data_list, frame, timestamp)

                detections_run += 1
                no_detections_run = 0
            else:
                no_detections_run += 1
                detections_run = 0

            # Trigger a video recoding event
            if self.args.save_video:
                if detections_run == self.args.detection_run:
                    if not encoding:
                        self.camera.start_video_recording()
                        encoding = True
                elif encoding and no_detections_run == self.no_detection_run:
                        self.camera.stop_video_recording()
                        encoding = False

            # Maintain Max Inference Rate
            time_diff = time.time() - last_frame_time
            wait_time = max(0, seconds_per_frame - time_diff)
            time.sleep(wait_time)
            last_frame_time = time.time()

            if time.time() - last_heartbeat_time >= 10:
                last_heartbeat_time = time.time()
                self.n.notify("WATCHDOG=1")

def main():
    logger = DetectorLogger()
    logger.run_detection()

if __name__ == "__main__":
    main()