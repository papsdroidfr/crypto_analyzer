import os
import time
from pathlib import Path

from scripts.clean_old_logs import clean_charts, clean_logs


def test_clean_logs_removes_only_old_log_files(tmp_path: Path) -> None:
    old_log = tmp_path / "old.log"
    recent_log = tmp_path / "recent.log"
    old_text = tmp_path / "old.txt"
    old_log.touch()
    recent_log.touch()
    old_text.touch()
    old_timestamp = time.time() - 2 * 24 * 60 * 60
    os.utime(old_log, (old_timestamp, old_timestamp))
    os.utime(old_text, (old_timestamp, old_timestamp))

    assert clean_logs(tmp_path, days=1) == 1
    assert not old_log.exists()
    assert recent_log.exists()
    assert old_text.exists()


def test_clean_charts_removes_only_old_png_files(tmp_path: Path) -> None:
    old_chart = tmp_path / "old.png"
    recent_chart = tmp_path / "recent.png"
    old_text = tmp_path / "old.txt"
    old_chart.touch()
    recent_chart.touch()
    old_text.touch()
    old_timestamp = time.time() - 2 * 24 * 60 * 60
    os.utime(old_chart, (old_timestamp, old_timestamp))
    os.utime(old_text, (old_timestamp, old_timestamp))

    assert clean_charts(tmp_path, days=1) == 1
    assert not old_chart.exists()
    assert recent_chart.exists()
    assert old_text.exists()