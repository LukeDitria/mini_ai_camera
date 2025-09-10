from picamera2 import Picamera2, Preview, Metadata
from picamera2.encoders import H264Encoder, Quality
from picamera2.outputs import CircularOutput
import cv2
import numpy as np
from typing import Optional, Tuple

import os
import logging
from datetime import datetime

class CameraCSI():
    def __init__(self, device_name: str, video_wh: Tuple[int, int] = (1920,1080),
                save_video: bool = False, data_output: str = ".", buffer_secs: int = 5):

        self.logger = logging.getLogger(__name__)
        self.logger.info("Camera initialized!")

        self.device_name = device_name
        self.video_wh = video_wh

        self.save_video = save_video
        self.buffer_secs = buffer_secs
        self.video_file_name = None

        self.data_output = data_output
        if self.save_video:
            self.videos_detections_path = os.path.join(self.data_output, "videos")
            os.makedirs(self.videos_detections_path, exist_ok=True)

        self.picam2 = Picamera2()

        # Configure camera stream
        main_res = {'size': self.video_wh, 'format': 'XRGB8888'}
        controls = {'FrameRate': 30}
        config = self.picam2.create_video_configuration(main_res, controls=controls)
        self.picam2.configure(config)

        self.picam2.start()

        if self.save_video:
            self.encoder = H264Encoder(1000000, repeat=True)
            self.output = CircularOutput(buffersize=self.buffer_secs * self.fps)
            self.picam2.start_recording(self.encoder, self.output, quality=Quality.HIGH)
            self.logger.info(f"Saving Video")

    def get_frames(self) -> Optional[Tuple[np.ndarray, np.ndarray, Metadata]]:
        # Capture and process frame
        frame = self.picam2.capture_array("main")
        metadata = self.picam2.capture_metadata()

        return frame, metadata

    def start_video_recording(self):
        if self.save_video:
            self.logger.info("Starting Video recording!")
            timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
            self.video_file_name = os.path.join(self.videos_detections_path, f"{self.device_name}_{timestamp}.h264")
            self.output.fileoutput = self.video_file_name
            self.output.start()
        else:
            self.logger.info("Save video is not running!")

    def stop_video_recording(self):
        if self.save_video:
            self.logger.info("Stoping Video recording!")
            self.output.stop()
        else:
            self.logger.info("Save video is not running!")

    def stop_camera(self):
        self.picam2.stop()
        self.picam2.close()