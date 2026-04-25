
import json
import pathlib
from datetime import time
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings
from platformdirs import user_data_dir


class CamConfig(BaseSettings, extra="forbid"):
    output_dir: str = Field(default="output", description="Directory name to save detection results")
    device_name: str = Field(default="site1", description="The name of this device to be used when saving data")

    model: str = Field(default="models/yolov8n.rpk", description="Path for the model file")
    labels: str = Field(default="models/coco_labels.txt", description="Path to a text file containing labels")
    valid_classes: str | None = Field(default=None, description="Path to text file containing valid class names")

    confidence: float = Field(default=0.5, ge=0, le=1, description="Confidence threshold")
    iou_threshold: float = Field(default=0.5, ge=0, le=1, description="IOU threshold")

    ips: int = Field(default=5, gt=0, description="Inferences per second")

    video_size: str = Field(default="1920,1080", description="Video size as width,height")

    buffer_secs: int = Field(default=3, gt=0, description="Circular buffer size in seconds")

    ema_alpha: float = Field(default=0.2, ge=0, le=1, description="EMA smoothing factor")
    event_threshold: float = Field(default=0.4, ge=0, le=1, description="EMA confidence threshold to trigger an event")

    save_video: bool = Field(default=False, description="Save video clips of detections")
    save_images: bool = Field(default=False, description="Save images of detections")
    save_data: bool = Field(default=True, description="Save detection data json")
    auto_select_media: bool = Field(default=False, description="Auto select mounted /media storage device")
    draw_bbox: bool = Field(default=False, description="Draw bounding boxes on saved images")

    @classmethod
    def from_file(cls, path: str | None = None):
        if path is None:
            return cls()
        ext = pathlib.Path(path).suffix
        if ext == ".json":
            config_path = Path(path)
            if config_path.exists():
                with open(path) as f:
                    return cls.model_validate(json.load(f))
            else:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                cfg = cls()

                # Update paths relative to config file folder
                cfg.model = str(config_path.parent / cfg.model)
                cfg.labels = str(config_path.parent / cfg.labels)
                cfg.output_dir = str(config_path.parent / cfg.output_dir)

                data = cfg.model_dump(mode='json')
                with open(path, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                return cfg

        raise ValueError(f"unsupported file type '{ext}'")
