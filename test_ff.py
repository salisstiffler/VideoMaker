import subprocess

cmd = ['ffmpeg', '-y', '-i', 'dummy_vid.mp4', '-filter_complex', "[0:v]subtitles='tmp_render_sub.srt':force_style='FontSize=24'[v_sub]", '-map', '[v_sub]', '-c:v', 'libx264', 'out.mp4']
res = subprocess.run(cmd, capture_output=True, text=True, errors='ignore')

print('Exit:', res.returncode)
with open('debug_err.log', 'w', encoding='utf-8') as f:
    f.write(res.stderr)
