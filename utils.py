import random
from os import urandom
import psutil

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

def get_network_latency():
    """Lấy thông tin latency mạng"""
    net_io = psutil.net_io_counters()
    return f"{net_io.bytes_sent / 1024 / 1024:.2f} MB sent / {net_io.bytes_recv / 1024 / 1024:.2f} MB recv"

def check_system_resources(cpu_threshold=90, mem_threshold=95):
    """Kiểm tra tài nguyên hệ thống để tránh crash"""
    cpu_usage = psutil.cpu_percent()
    mem_usage = psutil.virtual_memory().percent
    return cpu_usage < cpu_threshold and mem_usage < mem_threshold