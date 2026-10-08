import base64
import logging
import queue
import threading
import urllib.request

import cv2
import numpy as np

_logger = logging.getLogger(__name__)

NTFY_SERVER = "https://ntfy.sh"


def _header(value: str) -> str:
    """A header value ntfy reads back as UTF-8 (RFC 2047 when it isn't plain ASCII)."""
    if value.isascii():
        return value
    return "=?UTF-8?B?" + base64.b64encode(value.encode()).decode() + "?="


class NtfyNotifier:
    """Sends notifications to an ntfy topic from a background thread, so a slow or missing
    connection never holds up detection. A message that can't be sent is logged and dropped."""

    def __init__(self, topic: str, server: str = NTFY_SERVER, image_width: int = 1280, timeout_secs: float = 15):
        self.url = f"{server.rstrip('/')}/{topic}"
        self.image_width = image_width
        self.timeout_secs = timeout_secs
        self._queue: queue.Queue = queue.Queue(maxsize=8)
        self._thread = threading.Thread(target=self._run, name="ntfy", daemon=True)
        self._thread.start()
        _logger.info("Notifications go to %s", self.url)

    def notify(
        self,
        title: str,
        message: str,
        image: np.ndarray | None = None,
        filename: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> None:
        """Queue a notification; `image` is a camera frame. Returns at once."""
        try:
            self._queue.put_nowait((title, message, image, filename, tags))
        except queue.Full:
            _logger.warning("Notification queue full: dropping '%s'", title)

    def send(
        self,
        title: str,
        message: str,
        image: np.ndarray | None = None,
        filename: str | None = None,
        tags: tuple[str, ...] = (),
        jpeg: bytes | None = None,
    ) -> int:
        """Send one notification now and return the HTTP status. `image` is a camera frame;
        `jpeg` an already encoded picture."""
        headers = {"Title": _header(title)}
        if tags:
            headers["Tags"] = _header(",".join(tags))

        if image is not None:
            jpeg = self._encode(image)
        if jpeg is not None:
            body = jpeg
            headers["Message"] = _header(message)
            headers["Filename"] = _header(filename or "detection.jpg")
        else:
            body = message.encode()

        request = urllib.request.Request(self.url, data=body, method="PUT", headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout_secs) as response:
            return response.status

    def _encode(self, image: np.ndarray) -> bytes:
        # Camera frames are in RGB(X) order; OpenCV writes BGR (as the data logger does)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        h, w = image.shape[:2]
        if w > self.image_width:
            image = cv2.resize(image, (self.image_width, round(h * self.image_width / w)), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError("couldn't encode the image")
        return encoded.tobytes()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            title = item[0]
            try:
                status = self.send(*item)
                _logger.debug("Sent '%s' (HTTP %s)", title, status)
            except Exception as err:
                _logger.warning("Couldn't send the notification '%s': %s", title, err)

    def close(self, timeout_secs: float = 5) -> None:
        """Send what's queued (waiting up to `timeout_secs`), then stop."""
        try:
            self._queue.put(None, timeout=timeout_secs)
        except queue.Full:
            return
        self._thread.join(timeout=timeout_secs)
