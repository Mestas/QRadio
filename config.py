import os

# 百度TTS API配置
# 请替换为你自己的百度AI平台凭证
APP_ID = '121665854'
API_KEY = '5t4CiGdr9aV5EmrcQT8RnR4L'
SECRET_KEY = 'BFhvJKqp7Pz8MDAiXzIYiLmdDcfedTYo'

# 文件夹路径
BOOKS_DIR = 'Books'
AUDIO_FILES_DIR = 'Audio_files'
PLAYBACK_RECORDS_FILE = 'playback_records.json'

# 音色配置
VOICE_OPTIONS = {
    "女声": 0,
    "男声": 1,
    "度逍遥": 3,
    "度丫丫": 4
}

# 播放速度选项
SPEED_OPTIONS = {
    "0.5x": 0.5,
    "0.75x": 0.75,
    "1.0x": 1.0,
    "1.25x": 1.25,
    "1.5x": 1.5,
    "2.0x": 2.0
}

# 创建必要的文件夹
os.makedirs(BOOKS_DIR, exist_ok=True)
os.makedirs(AUDIO_FILES_DIR, exist_ok=True)
