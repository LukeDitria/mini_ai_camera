from picamera2 import Picamera2, Preview, Metadata, MappedArray
from picamera2.encoders import H264Encoder, Quality
from picamera2.outputs import CircularOutput

import cv2
import numpy as np
from typing import Optional, Tuple
import os
import logging
from typing import List

from datetime import datetime
from ai_cam.utils import DetectionResultYOLO, draw_detections

class CameraCSI():
    def __init__(self, device_name: str, video_wh: Tuple[int, int] = (1920,1080),
                save_video: bool = False, data_output: str = ".", buffer_secs: int = 5, 
                fps: int = 10, camera_num: int = 0, draw_bbox: bool = False):

        self.logger = logging.getLogger(__name__)

        self.device_name = device_name
        self.video_wh = video_wh

        self.save_video = save_video
        self.buffer_secs = buffer_secs
        self.video_file_name = None

        self.latest_detections = None
        self.draw_bbox = draw_bbox

        self.data_output = data_output
        if self.save_video:
            self.videos_detections_path = os.path.join(self.data_output, "videos")
            os.makedirs(self.videos_detections_path, exist_ok=True)

        self.picam2 = Picamera2(camera_num)

        if self.draw_bbox:
            self.picam2.post_callback = self.video_bbox

        # Configure camera stream. The format is picamera2's video default (XBGR8888, RGB order in
        # memory), which the image saving relies on. 3 buffers: same frame rate and delay as 6, less memory.
        main = {'size': self.video_wh, 'format': 'XBGR8888'}
        controls = {'FrameRate': fps}
        config = self.picam2.create_video_configuration(main=main, controls=controls, buffer_count=3)
        self.picam2.configure(config)

        self.picam2.start()
        self.logger.info("Camera started: %sx%s at %s fps", *config["main"]["size"], fps)

        if self.save_video:
            self.encoder = H264Encoder(1000000, repeat=True)
            self.output = CircularOutput(buffersize=self.buffer_secs * fps)
            self.picam2.start_recording(self.encoder, self.output, quality=Quality.HIGH)
            self.logger.info("Saving video")

    def get_frames(self) -> Optional[Tuple[np.ndarray, np.ndarray, Metadata]]:
        # Capture and process frame
        (frame, ), metadata = self.picam2.capture_arrays(["main"])

        return frame, metadata

    def update_detections(self, detections: List[DetectionResultYOLO]):
        self.latest_detections = detections

    def video_bbox(self, request):
        with MappedArray(request, "main") as m:
            if self.latest_detections is not None:
                draw_detections(self.latest_detections, m.array)

    def start_video_recording(self, classes_name):
        if self.save_video:
            self.logger.info("Starting video recording")
            timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
            self.video_file_name = os.path.join(self.videos_detections_path, f"{self.device_name}_{classes_name}_{timestamp}.h264")
            self.output.fileoutput = self.video_file_name
            self.output.start()
        else:
            self.logger.debug("Save video is not running")

    def stop_video_recording(self):
        if self.save_video:
            self.logger.info("Stopping video recording")
            self.output.stop()
        else:
            self.logger.debug("Save video is not running")

    def stop_camera(self):
        self.picam2.stop()
        self.picam2.close()