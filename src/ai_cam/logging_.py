import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path


def init_logging(logger: logging.Logger, level: int = logging.INFO):
    # Clamp root logger
    logging.getLogger().setLevel(logging.WARNING)

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers[:] = []  # idempotent re-init

    # Handler for terminal output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)

    # Attach handlers to logger
    logger.addHandler(console_handler)


class RotatingCSVLogger:
    def __init__(self, log_dir: Path, retention_days: int = 7):
        """
        Daily CSV logger with automatic deletion of old files.

        Args:
            log_dir: Directory to store CSV logs
            retention_days: Number of days to keep old logs
        """
        self.log_dir = log_dir
        self.log_dir.mkdir(exist_ok=True)
        self.retention_days = retention_days
        self.headers = [
            "Timestamp",
            "Battery Voltage",
            "Battery Current",
            "PV Voltage",
            "PV Current",
            "PV PI Temperature",
        ]
        self.cleanup_old_logs()

    def log_stats(self, bat_v: float, bat_c: float, pv_v: float, pv_c: float, temp):
        datetime_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [datetime_str, bat_v, bat_c, pv_v, pv_c, temp]
        self._log_row(row)

    def _get_today_file(self) -> Path:
        """Return the Path object for today's CSV file."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"{today_str}.csv"

    def cleanup_old_logs(self):
        """Delete CSV files older than retention_days."""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        for file in self.log_dir.glob("*.csv"):
            try:
                file_date = datetime.strptime(file.stem, "%Y-%m-%d")
                if file_date < cutoff:
                    file.unlink()
            except ValueError:
                # Skip files that don't match the date pattern
                continue

    def _log_row(self, row: list):
        """Append a row to today's CSV file, creating headers if needed. Clean old logs files."""
        self.cleanup_old_logs()
        current_log_path = self._get_today_file()
        write_header = not current_log_path.exists() and bool(self.headers)
        with current_log_path.open("a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(self.headers)
            writer.writerow(row)