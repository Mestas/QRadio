import streamlit as st
import os
import json
import time
from datetime import datetime
from aip import AipSpeech
import config
import pandas as pd
import re
from urllib.parse import urlparse, parse_qs
from user_config import (
    init_user_config, verify_user, update_user_password, 
    get_user_info, update_last_login, load_user_config
)

# ----------- 1. 文本分段（同前） -----------
def split_text(text: str, max_bytes: int = 1800) -> list[str]:
    text = text.lstrip('\ufeff').strip()
    if not text:
        return []
    sentences = re.findall(r'[^。！？\.\?\!]*[。！？\.\?\!]?', text, flags=re.S)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentences = [s for s in sentences if re.search(r'[\u4e00-\u9fa5a-zA-Z0-9]', s)]
    if not sentences:
        return [text] if len(text.encode('utf-8')) <= max_bytes else []
    chunks, buf, buf_len = [], '', 0
    for sent in sentences:
        l = len(sent.encode('utf-8'))
        if buf_len + l <= max_bytes:
            buf, buf_len = buf + sent, buf_len + l
        else:
            if buf:
                chunks.append(buf)
            buf, buf_len = sent, l
    if buf:
        chunks.append(buf)
    return chunks


# ----------- 2. 仅合成，不落盘 -----------
# ----------- 新增：仅分段合成 WAV，不合并 -----------
def generate_segments_mp3(text: str, voice_type: int, base_name: str):
    """
    每段 ≤1800 字节，输出 mp3（aue=6），不合并
    返回 List[文件名]
    """
    client = init_baidu_tts()
    # 1=wav(带RIFF头)  3/4=裸pcm  6=mp3
    options = {'spd': 5, 'pit': 5, 'vol': 5, 'per': voice_type, 'aue': 6}
    chunks = split_text(text, max_bytes=1500)
    if not chunks:
        st.error("拆分后没有有效段落！")
        return []
    
    os.makedirs(config.AUDIO_FILES_DIR, exist_ok=True)
    files = []

    for idx, seg in enumerate(chunks, 1):
        try:
            result = client.synthesis(seg, 'zh', 1, options)
            st.write(f'一共有{len(chunks)}段，第{idx}段的汉字数为{len(seg)}个')
        except Exception as e:
            st.error(f"第 {idx} 段网络异常：{e}")
            return []

        # 硬拦截
        if isinstance(result, dict):
            st.error(f"第 {idx} 段合成失败：{result}")
            return False
        if len(result) < 100 or not result.startswith(b'RIFF'):
            st.error(f"第 {idx} 段不是合法 mp3，前4字节={result[:4]} 长度={len(result)}")
            return False

        fname = f"{base_name}_seg{idx:03d}.mp3"
        fpath = os.path.join(config.AUDIO_FILES_DIR, fname)
        with open(fpath, 'wb') as f:
            f.write(result)
        files.append(fname)
    return files


# ----------- 3. 保存 & 展示 -----------
def save_segments(segments, base_name: str):
    """把每段音频写成独立文件，并返回文件列表"""
    os.makedirs(config.AUDIO_FILES_DIR, exist_ok=True)
    files = []
    for idx, (txt, audio_bytes) in enumerate(segments, 1):
        fname = f"{base_name}_seg{idx:03d}.mp3"
        fpath = os.path.join(config.AUDIO_FILES_DIR, fname)
        with open(fpath, 'wb') as f:
            f.write(audio_bytes)
        files.append(fname)
    return files

# 初始化用户配置
init_user_config()

# 用户认证配置
def is_user_logged_in():
    """检查用户是否已登录"""
    return st.session_state.get('logged_in', False)

def show_login_page():
    """显示登录界面"""
    st.set_page_config(
        page_title="iRadio Player - 登录",
        page_icon="🔐",
        layout="centered"
    )
    
    st.title("🔐 iRadio Player 登录")
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("### 用户登录")
        
        with st.form("login_form"):
            username = st.text_input("用户名", placeholder="请输入用户名")
            password = st.text_input("密码", type="password", placeholder="请输入密码")
            submit_button = st.form_submit_button("登录", type="primary")
            
            if submit_button:
                if verify_user(username, password):
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    update_last_login(username)
                    st.success(f"✅ 登录成功！欢迎 {username}")
                    time.sleep(1)  # 给用户时间看到成功消息
                    st.rerun()
                else:
                    st.error("❌ 用户名或密码错误！")
        
        # st.markdown("---")
        # st.info("💡 测试账户：")
        # st.code("用户名: admin\n密码: admin")
        # st.code("用户名: user\n密码: user123")
        
        with st.expander("🔒 安全提示"):
            st.markdown("""
            - 请妥善保管您的登录信息
            - 不要在公共设备上保存密码
            - 定期更换密码以确保安全
            """)

def logout():
    """用户登出"""
    for key in list(st.session_state.keys()):
        if key != 'logged_in' and key != 'username':  # 保留关键状态
            del st.session_state[key]
    
    # 清除登录状态
    if 'logged_in' in st.session_state:
        del st.session_state['logged_in']
    if 'username' in st.session_state:
        del st.session_state['username']
    
    st.rerun()

def show_change_password():
    """显示修改密码界面"""
    st.subheader("🔑 修改密码")
    
    with st.form("change_password_form"):
        current_password = st.text_input("当前密码", type="password")
        new_password = st.text_input("新密码", type="password", help="新密码长度至少为6位")
        confirm_password = st.text_input("确认新密码", type="password")
        
        submitted = st.form_submit_button("修改密码", type="primary")
        
        if submitted:
            username = st.session_state.get('username', '')
            
            if not verify_user(username, current_password):
                st.error("❌ 当前密码错误！")
            elif new_password != confirm_password:
                st.error("❌ 新密码与确认密码不匹配！")
            elif len(new_password) < 6:
                st.error("❌ 新密码长度至少为6位！")
            elif current_password == new_password:
                st.error("❌ 新密码不能与当前密码相同！")
            else:
                if update_user_password(username, new_password):
                    st.success("✅ 密码修改成功！新密码已生效。")
                    st.info("🔒 为了安全起见，请重新登录。")
                    time.sleep(2)
                    logout()
                else:
                    st.error("❌ 密码修改失败，请稍后重试！")
    
    if st.button("← 取消修改", key="cancel_change_pwd"):
        st.session_state.show_change_password = False
        st.rerun()

def show_user_sidebar():
    """在侧边栏显示用户信息"""
    with st.sidebar:
        st.markdown("---")
        
        username = st.session_state.get('username', '')
        user_info = get_user_info(username)
        
        if user_info:
            st.markdown(f"👤 **当前用户:** {username}")
            st.markdown(f"📅 **角色:** {user_info.get('role', 'user')}")
            
            if user_info.get('last_login'):
                st.markdown(f"🕐 **最后登录:** {user_info['last_login'][:16]}")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🚪 登出", type="secondary", key="logout_btn"):
                logout()
        
        with col2:
            if st.button("🔑 修改密码", key="change_pwd_btn"):
                st.session_state.show_change_password = True

# 初始化百度TTS客户端
@st.cache_resource
def init_baidu_tts():
    return AipSpeech(config.APP_ID, config.API_KEY, config.SECRET_KEY)

# 获取txt文件列表
def get_txt_files():
    txt_files = []
    if os.path.exists(config.BOOKS_DIR):
        for file in os.listdir(config.BOOKS_DIR):
            if file.endswith('.txt'):
                txt_files.append(file)
    return sorted(txt_files)

# 获取音频文件列表
def get_audio_files():
    audio_files = []
    if os.path.exists(config.AUDIO_FILES_DIR):
        for file in os.listdir(config.AUDIO_FILES_DIR):
            if file.endswith('.mp3'):
                audio_files.append(file)
    return sorted(audio_files)

# 读取txt文件内容
def read_txt_file(filename):
    file_path = os.path.join(config.BOOKS_DIR, filename)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        st.error(f"读取文件失败: {e}")
        return None

# 使用百度TTS生成音频
def generate_audio(text, voice_type, output_filename):
    client = init_baidu_tts()
    
    options = {
    'spd': 5,
    'pit': 5,
    'vol': 5,
    'per': voice_type,
    'aue': 4,          # 4 = wav（16k 16bit PCM）
    # 其他可选：3=pcm（裸流），5=amr，6=mp3（默认）
    }
    
    try:
        result = client.synthesis(text, 'zh', 1, options)
        if not isinstance(result, dict):
            output_path = os.path.join(config.AUDIO_FILES_DIR, output_filename)
            with open(output_path, 'wb') as f:
                f.write(result)
            return True
        else:
            st.error(f"语音合成失败: {result}")
            return False
    except Exception as e:
        st.error(f"生成音频时出错: {e}")
        return False

# 获取音频文件的完整路径
def get_audio_path(filename):
    return os.path.join(config.AUDIO_FILES_DIR, filename)

# 加载播放记录
def load_playback_records():
    if os.path.exists(config.PLAYBACK_RECORDS_FILE):
        try:
            with open(config.PLAYBACK_RECORDS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

# 保存播放记录
def save_playback_records(records):
    try:
        with open(config.PLAYBACK_RECORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"保存播放记录失败: {e}")

# 更新播放记录
def update_playback_record(audio_file, position=0, duration=0, status="playing"):
    records = load_playback_records()
    
    if audio_file not in records:
        records[audio_file] = {
            'last_played': datetime.now().isoformat(),
            'play_count': 0,
            'total_play_time': 0,
            'last_position': 0,
            'duration': duration,
            'completed': False
        }
    
    records[audio_file]['last_played'] = datetime.now().isoformat()
    records[audio_file]['last_position'] = position
    
    if status == "completed":
        records[audio_file]['completed'] = True
        records[audio_file]['play_count'] += 1
    elif status == "playing":
        records[audio_file]['play_count'] += 1
    
    if duration > 0:
        records[audio_file]['duration'] = duration
    
    save_playback_records(records)
    return records[audio_file]

# 从URL参数获取当前播放位置
def get_playback_position_from_url():
    """从当前URL的查询参数中获取播放位置"""
    query_params = st.query_params
    if 't_live' in query_params:
        try:
            return float(query_params['t_live'])
        except (ValueError, TypeError):
            pass
    return 0

# 文本转语音界面
def show_tts_interface():
    st.header("📝 文本转语音")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        txt_files = get_txt_files()
        if not txt_files:
            st.warning(f"📁 请在 {config.BOOKS_DIR} 文件夹中添加txt文件")
            return
        
        selected_txt = st.selectbox("选择文本文件", txt_files, key="txt_selector")
        
        if selected_txt:
            content = read_txt_file(selected_txt)
            if content:
                st.text_area("文本内容预览", content[:500] + "..." if len(content) > 500 else content, height=200)
    
    with col2:
        voice_name = st.selectbox("选择音色", list(config.VOICE_OPTIONS.keys()), key="voice_selector")
        voice_type = config.VOICE_OPTIONS[voice_name]
        
        # if st.button("🎤 生成音频", type="primary"):
        #     if selected_txt:
        #         with st.spinner("正在生成音频..."):
        #             content = read_txt_file(selected_txt)
        #             if content:
        #                 base_name = os.path.splitext(selected_txt)[0]
        #                 output_filename = f"{base_name}_{voice_name}.mp3"
                        
        #                 if os.path.exists(os.path.join(config.AUDIO_FILES_DIR, output_filename)):
        #                     st.info("⚠️ 该音频文件已存在！")
        #                 else:
        #                     output_path = os.path.join(config.AUDIO_FILES_DIR, output_filename)
        #                     if generate_audio(content, voice_type, output_path):
        #                         st.success(f"✅ 长音频生成成功: {output_filename}")
        #                         st.balloons()
        #                     else:
        #                         st.error("❌ 长音频合成失败，请检查日志")
        # with col2:
        if st.button("🎤 分段合成音频", type="primary"):
            with st.spinner("正在分段合成 MP3..."):
                content = read_txt_file(selected_txt)
                if content:
                    base_name = os.path.splitext(selected_txt)[0]
                    files = generate_segments_mp3(content, voice_type, base_name)
                    if files:
                        st.success(f"✅ 已生成 {len(files)} 段 MP3。")
                        # for f in files:
                        #     audio_path = os.path.join(config.AUDIO_FILES_DIR, f)
                        #     with open(audio_path, 'rb') as af:
                        #         st.audio(af, format='audio/mp3')
                        #     st.download_button(label=f"下载 {f}", data=af,
                        #                     file_name=f, mime='audio/mp3')
                    else:
                        st.error("分段合成失败")
# 音频播放器界面
def show_player_interface():
    st.header("🎧 音频播放器")
    
    audio_files = get_audio_files()
    if not audio_files:
        st.warning(f"📁 请在 {config.AUDIO_FILES_DIR} 文件夹中添加音频文件")
        return
    
    playback_records = load_playback_records()
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        selected_audio = st.selectbox(
            "选择音频文件", 
            audio_files,
            format_func=lambda x: f"🎵 {x}",
            key="audio_selector"
        )
        
        if selected_audio:
            audio_path = get_audio_path(selected_audio)
            
            # 获取URL参数中的播放位置
            current_position = get_playback_position_from_url()
            
            # 获取保存的播放位置
            saved_position = playback_records.get(selected_audio, {}).get('last_position', 0)
            
            # 使用URL参数中的位置（如果存在），否则使用保存的位置
            start_position = current_position if current_position > 0 else saved_position
            
            st.info(f"📍 当前播放位置: {start_position:.1f}秒")
            
            # 读取并播放音频
            with open(audio_path, 'rb') as f:
                audio_bytes = f.read()
            
            # 使用Streamlit的音频播放器，设置起始位置
            st.audio(audio_bytes, format='audio/mp3', start_time=int(start_position))
            
            # 显示实时播放位置
            st.markdown("### ⏱️ 实时播放位置")
            st.markdown('<div id="live-time-display" style="font-size: 2rem; font-weight: 700; line-height: 1.2; margin: 0.5rem 0;">0.0秒</div>', unsafe_allow_html=True)
            
            # 插入JavaScript代码来更新播放位置
            js_code = f"""
            <script>
            (function() {{
                // 等待页面加载完成
                setTimeout(function() {{
                    const aud = window.parent.document.querySelector('audio');
                    const timeDisplay = window.parent.document.getElementById('live-time-display');
                    
                    if (!aud || !timeDisplay) {{
                        console.log('Audio or time display element not found');
                        return;
                    }}
                    
                    console.log('Audio element found:', aud);
                    console.log('Time display element found:', timeDisplay);
                    
                    // 设置初始显示
                    timeDisplay.textContent = '{start_position:.1f}秒';
                    
                    // 监听播放进度
                    aud.addEventListener('timeupdate', function() {{
                        const t = aud.currentTime;
                        const tFixed = t.toFixed(1);
                        
                        // 更新显示
                        if (timeDisplay) {{
                            timeDisplay.textContent = tFixed + '秒';
                        }}
                        
                        // 更新URL参数
                        try {{
                            const url = new URL(window.parent.location);
                            url.searchParams.set('t_live', tFixed);
                            window.parent.history.replaceState(null, null, url.toString());
                        }} catch (e) {{
                            console.log('Error updating URL:', e);
                        }}
                    }});
                    
                    // 监听播放结束
                    aud.addEventListener('ended', function() {{
                        try {{
                            const url = new URL(window.parent.location);
                            url.searchParams.set('t_live', '0');
                            window.parent.history.replaceState(null, null, url.toString());
                        }} catch (e) {{
                            console.log('Error updating URL on ended:', e);
                        }}
                    }});
                }}, 1000); // 延迟1秒执行，确保音频元素已加载
            }})();
            </script>
            """
            
            st.components.v1.html(js_code, height=0)
            
            # 控制按钮
            col_btn1, col_btn2, col_btn3 = st.columns(3)
            
            with col_btn1:
                if st.button("💾 保存当前位置", key="save_position"):
                    # 获取最新的播放位置
                    latest_position = get_playback_position_from_url()
                    if latest_position > 0:
                        update_playback_record(selected_audio, position=latest_position)
                        st.success(f"✅ 播放位置已保存: {latest_position:.1f}秒")
                    else:
                        st.warning("请先播放音频再保存位置")
            
            with col_btn2:
                if st.button("⏮️ 重置位置", key="reset_position"):
                    # 重置URL参数和记录
                    update_playback_record(selected_audio, position=0)
                    # 使用新的API设置查询参数
                    st.query_params['t_live'] = '0'
                    st.rerun()
            
            with col_btn3:
                if st.button("✅ 标记完成", key="mark_complete"):
                    latest_position = get_playback_position_from_url()
                    update_playback_record(selected_audio, status="completed")
                    st.success("音频已标记为完成！")
            
            # 显示播放记录
            if selected_audio in playback_records:
                record = playback_records[selected_audio]
                st.info(f"""
                📊 播放统计：
                - 播放次数：{record['play_count']}
                - 最后播放：{record['last_played'][:10]}
                - 保存位置：{record['last_position']:.1f}秒
                - 完成状态：{'✅ 已完成' if record.get('completed', False) else '⏸️ 进行中'}
                """)
    
    with col2:
        st.subheader("📊 播放统计")
        
        if selected_audio:
            current_record = playback_records.get(selected_audio, {})
            st.metric("播放次数", current_record.get('play_count', 0))
            st.metric("保存位置", f"{current_record.get('last_position', 0):.1f}秒")
            st.metric("完成状态", "✅ 已完成" if current_record.get('completed', False) else '⏸️ 进行中')
        
        st.subheader("📋 播放列表")
        
        playlist_data = []
        for audio in audio_files:
            record = playback_records.get(audio, {})
            playlist_data.append({
                '文件名': audio,
                '播放次数': record.get('play_count', 0),
                '最后播放': record.get('last_played', '从未')[:10] if record.get('last_played') else '从未',
                '状态': '✅ 完成' if record.get('completed', False) else '⏸️ 进行中',
                '位置': f"{record.get('last_position', 0):.1f}秒"
            })
        
        df = pd.DataFrame(playlist_data)
        st.dataframe(df, width='stretch')

# 播放记录界面
def show_playback_records():
    st.header("📊 播放记录统计")
    
    playback_records = load_playback_records()
    
    if not playback_records:
        st.info("暂无播放记录")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    total_files = len(get_audio_files())
    played_files = len([r for r in playback_records.values() if r['play_count'] > 0])
    total_plays = sum(r['play_count'] for r in playback_records.values())
    completed_files = len([r for r in playback_records.values() if r.get('completed', False)])
    completion_rate = (completed_files / total_files * 100) if total_files > 0 else 0
    
    with col1:
        st.metric("总音频文件", total_files)
    
    with col2:
        st.metric("已播放文件", played_files)
    
    with col3:
        st.metric("总播放次数", total_plays)
    
    with col4:
        st.metric("完成率", f"{completion_rate:.1f}%")
    
    st.subheader("📋 详细播放记录")
    
    records_data = []
    for filename, record in playback_records.items():
        records_data.append({
            '文件名': filename,
            '播放次数': record['play_count'],
            '最后播放': record['last_played'][:16],
            '播放位置': f"{record['last_position']:.1f}秒",
            '音频时长': f"{record['duration']:.1f}秒" if record['duration'] > 0 else '未知',
            '状态': '✅ 已完成' if record.get('completed', False) else '⏸️ 进行中'
        })
    
    df = pd.DataFrame(records_data)
    df = df.sort_values('最后播放', ascending=False)
    
    st.dataframe(df, width='stretch')
    
    if len(records_data) > 1:
        st.subheader("📈 播放趋势")
        
        date_plays = {}
        for record in playback_records.values():
            date = record['last_played'][:10]
            date_plays[date] = date_plays.get(date, 0) + 1
        
        if date_plays:
            chart_data = pd.DataFrame(
                list(date_plays.items()),
                columns=['日期', '播放次数']
            ).sort_values('日期')
            
            st.line_chart(chart_data.set_index('日期'))
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ 清空所有记录"):
            if os.path.exists(config.PLAYBACK_RECORDS_FILE):
                os.remove(config.PLAYBACK_RECORDS_FILE)
                st.success("所有播放记录已清空！")
                st.rerun()
    
    with col2:
        if st.button("📊 导出记录"):
            csv = df.to_csv(index=False)
            st.download_button(
                label="下载CSV文件",
                data=csv,
                file_name=f"playback_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )

# 主界面
def main():
    # 检查用户是否已登录
    if not is_user_logged_in():
        show_login_page()
        return
    
    # 用户已登录，显示主界面
    st.set_page_config(
        page_title="iRadio Player - 智能音频播放器",
        page_icon="🎵",
        layout="wide"
    )
    
    # 显示用户信息栏
    show_user_sidebar()
    
    # 处理修改密码界面
    if st.session_state.get('show_change_password', False):
        st.subheader("🔑 修改密码")
        show_change_password()
        return
    
    st.title("🎵 iRadio Player - 智能音频播放器")
    st.markdown("---")
    
    # 侧边栏功能菜单
    with st.sidebar:
        st.header("📚 功能菜单")
        
        # 检查API配置
        if config.APP_ID == 'your_app_id' or config.API_KEY == 'your_api_key':
            st.warning("⚠️ 请先配置百度TTS API凭证！")
            st.info("编辑 config.py 文件，填入你的百度AI平台凭证")
            return
        
        # 功能选择
        feature = st.radio(
            "选择功能",
            ["文本转语音", "音频播放器", "播放记录"],
            key="feature_selector"
        )
    
    # 主内容区域
    if feature == "文本转语音":
        show_tts_interface()
    elif feature == "音频播放器":
        show_player_interface()
    elif feature == "播放记录":
        show_playback_records()

if __name__ == "__main__":
    main()
