import argparse
import logging
import json


def parse_arguments():
    parser = argparse.ArgumentParser(description="Hailo object detection on camera stream")
    parser.add_argument("--config_file", type=str, help="Path to JSON configuration file")

    parser.add_argument("--output_dir", type=str, default="output",
                        help="Directory name to save detection results")

    parser.add_argument("--device_name", type=str, default="site1",
                        help="The name of this device to be used when saving data")

    parser.add_argument("--model", type=str, default="yolov8n.rpk",
                        help="Path for the model file")
    parser.add_argument("--labels", type=str, default="coco.txt",
                        help="Path to a text file containing labels")
    parser.add_argument("--valid_classes", type=str,
                        help="Path to text file containing list of valid class names to detect")

    parser.add_argument("--confidence", type=float, default=0.5,
                        help="Confidence threshold (default: 0.5)")
    parser.add_argument("--iou_threshold", type=float, default=0.5,
                        help="IOU threshold (default: 0.5)")
                        
    parser.add_argument("--ips", type=int, default=5,
                        help="Inferences per second (default: 5)")
    parser.add_argument("--lps", type=int,
                        help="Logs per second, if defined image saves and detection logging will occur at this rate")

    parser.add_argument("--video_size", type=str, default="1920,1080",
                        help="Video size as width,height for saving images and video (default: 1920,1080)")

    parser.add_argument("--buffer_secs", type=int, default=3,
                        help="The Circular buffer size in seconds (default: 3)")
    parser.add_argument("--detection_run", type=int, default=5,
                        help="Number of detections in a row before recording starts (default: 5)")

    parser.add_argument("--save_video", action='store_true', help="Save video clips of detections")
    parser.add_argument("--save_images", action='store_true', help="Save images of the detections")
    parser.add_argument("--save_data", action='store_true', help="Save detection data json")
    parser.add_argument("--auto_select_media", action='store_true',
                        help="Auto selects a device mounted to /media to use as the storage device for outputs")
    parser.add_argument("--draw_bbox", action='store_true',
                        help="Draw bounding boxes on the saved images")


    args = parser.parse_args()

    if args.config_file:
        try:
            with open(args.config_file, 'r') as f:
                config = json.load(f)

            # Override CLI args with JSON config values
            for key, value in config.items():
                if hasattr(args, key):
                    setattr(args, key, value)

            logging.info(f"Loaded configuration from {args.config_file}")
        except Exception as e:
            logging.info(f"Error loading config file: {e}")
            logging.info("Using command line arguments instead")

    return args
