import logging
import os
from datetime import datetime

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 設定日誌格式
log_filename = datetime.now().strftime(f"{LOG_DIR}/bmo_runtime_%Y-%m-%d.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler() # 同時輸出到控制台
    ]
)

logger = logging.getLogger("BMO_Core")

def log_info(msg): logger.info(msg)
def log_warn(msg): logger.warning(msg)
def log_error(msg): logger.error(msg)
