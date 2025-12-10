import streamlit as st
import edge_tts
# import asyncio
# import os
import json
import time
import threading
from pathlib import Path
from streamlit.components.v1 import html


BOOK_DIR  = Path(r"Books")
AUDIO_DIR = Path(r"Audio_files")
PROC_DIR  = Path(r"Process_files")

# -------------------- edge-tts 工具 --------------------
VOICE_LIST = None                       # 缓存语音列表

async def _load_voice_list():
    """异步拉一次线上音色列表，缓存到全局变量"""
    global VOICE_LIST
    if VOICE_LIST is None:
        VOICE_LIST = await edge_tts.list_voices()
    return VOICE_LIST
    
def get_voices():
    """同步包装：Streamlit 调用时先跑一遍事件循环"""
    return asyncio.run(_load_voice_list())

def voice_id_to_name(v):
    """把 edge-tts 的音色字典转成可读名称"""
    return f"{v['Locale']}  {v['Gender']}  {v['Name']}"
def book_text(book_name: str):
    return (BOOK_DIR / f"{book_name}.txt").read_text(encoding="utf-8")

def audio_path(book: str, voice_id: str):
    # voice_id 里可能带路径符号，一律用最后一段
    voice_name = voice_id.split('\\')[-1].split('/')[-1]
    return AUDIO_DIR / book / f"{voice_name}.mp3"

def prog_path(book: str, voice_id: str):
    voice_name = voice_id.split('\\')[-1].split('/')[-1]
    return PROC_DIR / book / f"{voice_name}.json"

def load_progress(book: str, voice_id: str):
    p = prog_path(book, voice_id)
    if p.exists():
        return json.loads(p.read_text()).get("seconds", 0.0)
    return 0.0

def save_progress(book: str, voice_id: str, seconds: float):
    voice_name = voice_id.split('\\')[-1].split('/')[-1]
    p = PROC_DIR / book / f"{voice_name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"seconds": seconds}, ensure_ascii=False))
    print("[save]", p, "->", seconds)

def generate_audio(text: str, voice_id: str, output_file: Path,
                   rate: int = 0, volume: float = 0):
    """
    用 edge-tts 在后台线程生成音频
    rate  : ±%  例如 +20% / -20%
    volume: ±%  例如 +10% / -10%
    """
    async def _task():
        communicate = edge_tts.Communicate(
            text,
            voice_id,
            rate=f"{rate:+.0%}" if rate else "+0%",
            volume=f"{volume:+.0%}" if volume else "+0%"
        )
        await communicate.save(str(output_file))

    threading.Thread(target=lambda: asyncio.run(_task()), daemon=True).start()

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="QRadio Player", layout="centered")
st.title("📚 QRadio Player")

books = sorted([f.stem for f in BOOK_DIR.glob("*.txt")])
if not books:
    st.warning("Books 文件夹内暂无 .txt 文件"); st.stop()

voices = get_voices()
voice_map = {voice_id_to_name(v): v['Name'] for v in voices}

with st.sidebar:
    book_sel = st.selectbox("选择书籍", books)
    voice_desc = st.selectbox("选择音色", list(voice_map.keys()))
    voice_id   = voice_map[voice_desc]

audio_file = audio_path(book_sel, voice_id)
text = book_text(book_sel)

# 首次生成
if not audio_file.exists():
    with st.spinner("正在后台生成音频，请稍候…"):
        audio_file.parent.mkdir(parents=True, exist_ok=True)
        generate_audio(text, voice_id, audio_file)
        # 简单等待完成
        progress = st.progress(0)
        for i in range(100):
            time.sleep(0.1)
            progress.progress(i+1)
            if audio_file.exists():
                break
        progress.empty()
    st.success("音频生成完毕！")

# 读取上次进度
start_sec = load_progress(book_sel, voice_id)

# 播放器
st.write(f"<span style='color: blue; font-size: 18px'>正在播放：{book_sel}</span>", unsafe_allow_html=True)
st.write(f"<span style='color: blue; font-size: 18px'>音色：{voice_desc}</span>", unsafe_allow_html=True)
audio_bytes = audio_file.read_bytes()
audio_player = st.audio(audio_bytes, format="audio/mp3", start_time=int(start_sec))

st.write(f"<span style='color: green; font-size: 18px'>当前播放秒数</span>", unsafe_allow_html=True)
st.write(
    '''
    <div id="live-time-display"
         style="
            font-family: 'Microsoft YaHei', sans-serif;
            font-size: 18px;
            font-weight: bold;
            color: #ff6600;
         ">
        0.0秒
    </div>
    ''',
    unsafe_allow_html=True
)

# 让 JS 直接更新播放时间显示，同时更新URL参数
html("""
<script>
(function(){
  const aud = window.parent ? window.parent.document.querySelector('audio') : document.querySelector('audio');
  const timeDisplay = window.parent ? window.parent.document.getElementById('live-time-display') : document.getElementById('live-time-display');
  if (!aud || !timeDisplay) return;
  timeDisplay.style.cssText = `
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.2;
    margin: 0.5rem 0;
  `;
  setInterval(() => {
    const t = aud.currentTime;
    const tFixed = t.toFixed(1);
    timeDisplay.textContent = tFixed + '秒';
    const url = new URL(window.parent ? window.parent.location : window.location);
    url.searchParams.set('t_live', tFixed);
    if (window.parent && window.parent.history) {
      window.parent.history.replaceState(null, null, url);
    } else {
      window.history.replaceState(null, null, url);
    }
  }, 100);
})();
</script>
""", height=0)

if st.button("💾 保存当前进度"):
    live = st.query_params.get("t_live", "0")
    try:
        current_sec = float(live)
        save_progress(book_sel, voice_id, current_sec)
        st.success(f"已保存 {current_sec:.1f} 秒")
    except (ValueError, TypeError) as e:
        st.error(f"无法获取当前播放时间: {e}")

    


