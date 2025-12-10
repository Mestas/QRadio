import streamlit as st
import pyttsx3
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
# -------------------- pyttsx3 工具 --------------------
def get_voices():
    """获取本机所有可用语音"""
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    engine.stop()
    return voices

def voice_id_to_name(v):
    """把语音对象转成可读名称"""
    lang = v.languages[0] if v.languages else "unknown"
    return f"{lang}  {v.gender}  {v.name}"

def book_text(book_name: str):
    return (BOOK_DIR / f"{book_name}.txt").read_text(encoding="utf-8")

def audio_path(book: str, voice_id: str):
    # 使用voice_id的最后一部分作为文件名，避免包含注册表路径
    voice_name = voice_id.split('\\')[-1]
    return AUDIO_DIR / book / f"{voice_name}.mp3"

def prog_path(book: str, voice_id: str):
    # 使用voice_id的最后一部分作为文件名，避免包含注册表路径
    voice_name = voice_id.split('\\')[-1]
    return PROC_DIR / book / f"{voice_name}.json"

def load_progress(book: str, voice_id: str):
    p = prog_path(book, voice_id)
    if p.exists():
        return json.loads(p.read_text()).get("seconds", 0.0)
    return 0.0

def save_progress(book: str, voice_id: str, seconds: float):
    # 用你原来的规则：voice_id 最后一段当文件名
    voice_name = voice_id.split('\\')[-1]
    p = PROC_DIR / book / f"{voice_name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)   # 确保目录存在
    p.write_text(json.dumps({"seconds": seconds}, ensure_ascii=False))
    print("[save]", p, "->", seconds)             # 调试用，控制台可见

def generate_audio(text: str, voice_id: str, output_file: Path,
                   rate: int = 200, volume: float = 1.0):
    """后台线程生成音频，避免阻塞 Streamlit"""
    def _task():
        engine = pyttsx3.init()
        engine.setProperty('voice', voice_id)
        engine.setProperty('rate', rate)
        engine.setProperty('volume', volume)
        engine.save_to_file(text, str(output_file))
        engine.runAndWait()
        engine.stop()
    threading.Thread(target=_task, daemon=True).start()

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="QRadio Player", layout="centered")
st.title("📚 QRadio Player")

books = sorted([f.stem for f in BOOK_DIR.glob("*.txt")])
if not books:
    st.warning("Books 文件夹内暂无 .txt 文件"); st.stop()

voices = get_voices()
voice_map = {voice_id_to_name(v): v.id for v in voices}

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
        # 简单等待完成（生产环境可用回调或轮询）
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
# st.subheader(f"正在播放：{book_sel}  (音色：{voice_desc})")
st.write(f"<span style='color: blue; font-size: 18px'>正在播放：{book_sel}</span>", unsafe_allow_html=True)
st.write(f"<span style='color: blue; font-size: 18px'>音色：{voice_desc}</span>", unsafe_allow_html=True)
audio_bytes = audio_file.read_bytes()
audio_player = st.audio(audio_bytes, format="audio/mp3", start_time=int(start_sec))


# 添加播放时间的标题
st.write(f"<span style='color: green; font-size: 18px'>当前播放秒数</span>", unsafe_allow_html=True)
# 创建一个带有唯一ID的div，用于显示播放时间
# st.write('<div id="live-time-display">0.0秒</div>', unsafe_allow_html=True)
st.write(
    '''
    <div id="live-time-display"
         style="
            font-family: 'Microsoft YaHei', sans-serif;   /* 字体名 */
            font-size: 18px;                              /* 字号 */
            font-weight: bold;                            /* 粗细 */
            color: #ff6600;                               /* 颜色 */
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
  // 先尝试在父页面查找音频元素，如果找不到则在当前页面查找
  const aud = window.parent ? window.parent.document.querySelector('audio') : document.querySelector('audio');
  const timeDisplay = window.parent ? window.parent.document.getElementById('live-time-display') : document.getElementById('live-time-display');
  
  // 添加调试信息
  console.log('Audio element found:', aud);
  console.log('Time display element found:', timeDisplay);
  
  if (!aud || !timeDisplay) return;
  
  // 设置初始显示样式，匹配Streamlit metric组件
  timeDisplay.style.cssText = `
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.2;
    margin: 0.5rem 0;
  `;
  
  setInterval(() => {
    const t = aud.currentTime;
    const tFixed = t.toFixed(1);
    
    // 更新页面上的显示
    timeDisplay.textContent = tFixed + '秒';
    
    // 同时更新URL参数（用于保存功能）
    const url = new URL(window.parent ? window.parent.location : window.location);
    url.searchParams.set('t_live', tFixed);
    
    // 调试信息
    console.log('Setting URL parameter t_live to:', tFixed);
    
    if (window.parent && window.parent.history) {
      window.parent.history.replaceState(null, null, url);   // 不触发整页刷新
    } else {
      window.history.replaceState(null, null, url);
    }
  }, 100);
})();
</script>
""", height=0)


if st.button("💾 保存当前进度"):
    # 点击按钮时才读取当前播放时间
    live = st.query_params.get("t_live", "0")   # 返回 str，默认 "0"
    
    try:
        current_sec = float(live)
        save_progress(book_sel, voice_id, current_sec)
        st.success(f"已保存 {current_sec:.1f} 秒")
    except (ValueError, TypeError) as e:
        st.error(f"无法获取当前播放时间: {e}")
        print("[DEBUG] 转换错误:", e)
    # st.write(st.session_state)

    
