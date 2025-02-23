import random
from os import urandom

def randbytes(size):
    return urandom(size)

def humanbytes(size):
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    while size >= 1024 and unit_idx < len(units) - 1:
        size /= 1024
        unit_idx += 1
    return f"{size:.2f} {units[unit_idx]}"

def format_time(seconds):
    """Chuyển đổi giây thành định dạng phút:giây"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"