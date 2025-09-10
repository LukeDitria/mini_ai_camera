from typing import Any, List, Dict, Optional, Union, Tuple
from dataclasses import dataclass, asdict
import numpy as np
import os
import cv2

@dataclass
class BoundingBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def xyxy(self) -> List[float]:
        return [self.xmin, self.ymin, self.xmax, self.ymax]

    def to_dict(self) -> dict:
        return {
            "xmin": self.xmin,
            "ymin": self.ymin,
            "xmax": self.xmax,
            "ymax": self.ymax
        }

@dataclass
class DetectionResultYOLO:
    score: float
    class_name: str
    bbox: BoundingBox

    @classmethod
    def from_dict(cls, detection_dict: dict) -> 'DetectionResultYOLO':
        return cls(
            score=detection_dict['score'],
            class_name=detection_dict['class_name'],
            bbox=BoundingBox(
                xmin=detection_dict['bbox']['xmin'],
                ymin=detection_dict['bbox']['ymin'],
                xmax=detection_dict['bbox']['xmax'],
                ymax=detection_dict['bbox']['ymax']
            )
        )

    def to_dict(self):
        result = {
            'score': self.score,
            'class_name': self.class_name,
            'bbox': self.bbox.to_dict()
        }
        return result


def compute_iou(box1: BoundingBox, box2: BoundingBox) -> float:

    # Calculate intersection coordinates
    x1 = max(box1.xmin, box2.xmin)
    y1 = max(box1.ymin, box2.ymin)
    x2 = min(box1.xmax, box2.xmax)
    y2 = min(box1.ymax, box2.ymax)

    # Calculate intersection area
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    if intersection == 0:
        return 0

    # Calculate union area
    box1_area = (box1.xmax - box1.xmin) * (box1.ymax - box1.ymin)
    box2_area = (box2.xmax - box2.xmin) * (box2.ymax - box2.ymin)
    union = box1_area + box2_area - intersection

    return intersection / union

def apply_nms(detections: List[DetectionResultYOLO], nms_threshold: float = 0.65) -> List[DetectionResultYOLO]:
    """
    Apply Non-Maximum Suppression to filter overlapping detections.
    """
    if not detections:
        return []

    # Sort detections by confidence score
    detections = sorted(detections, key=lambda x: x.score, reverse=True)
    kept_detections = []

    while detections:
        # Keep the detection with highest confidence
        current = detections.pop(0)
        kept_detections.append(current)

        # Filter out detections with high IoU
        detections = [
            det for det in detections
            if compute_iou(current.bbox, det.bbox) < nms_threshold
        ]

    return kept_detections

def read_class_list(filepath: str):
    """Read list of class names from a text file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

def find_first_usb_drive() -> Optional[str]:
    # Relies on raspi OS to auto mount USB storage to /media/username etc
    # Lite version does not auto mount any USB, if using Lite you need to manually set this up for a certain USB

    media_path = "/media"

    # Check if /media exists
    if not os.path.exists(media_path):
        return None

    # Get all user directories under /media (usually just one)
    media_items = os.listdir(media_path)

    for user_dir in media_items:
        user_path = os.path.join(media_path, user_dir)

        # If this is a directory
        if os.path.isdir(user_path):
            # Check for any subdirectories (mounted drives)
            try:
                usb_drives = os.listdir(user_path)
                if usb_drives:
                    # Return the first drive found
                    return os.path.join(user_path, usb_drives[0])
            except:
                pass

    # No USB drives found
    return None

def draw_detections(detections: List[DetectionResultYOLO], frame: np.ndarray) -> np.ndarray:
    for detection in detections:
        x0, y0, x1, y1 = detection.bbox.xyxy

        x0 = int(x0 * frame.shape[1])
        y0 = int(y0 * frame.shape[0])
        x1 = int(x1 * frame.shape[1])
        y1 = int(y1 * frame.shape[0])

        class_name = detection.class_name
        score = detection.score

        label = f"{class_name} ({score:.2f})"

        # Calculate text size and position
        (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        text_x = int(x0)
        text_y = int(y0 - 15)

        # Draw the background rectangle on the overlay
        cv2.rectangle(frame,
                      (text_x, text_y - text_height),
                      (text_x + text_width, text_y + baseline),
                      (255, 255, 255),  # Background color (white)
                      cv2.FILLED)

        # Draw text on top of the background
        cv2.putText(frame, label, (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        # Draw detection box
        cv2.rectangle(frame, (x0, y0), (x1, y1), (0, 255, 0, 0), thickness=2)

    return frame
