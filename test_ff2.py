import subprocess, os, shutil

os.system('ffmpeg -y -f lavfi -i color=c=black:s=640x360:d=1 dummy_vid.mp4 2>nul')
with open('tmp_render_sub.srt', 'w', encoding='utf-8') as f:
    f.write('1\n00:00:00,000 --> 00:00:01,000\nHello\n')

cmd = ['ffmpeg', '-y', '-i', 'dummy_vid.mp4', '-filter_complex', "[0:v]subtitles='tmp_render_sub.srt':force_style='FontSize=24'[v_sub]", '-map', '[v_sub]', '-c:v', 'libx264', 'out.mp4']
res = subprocess.run(cmd, capture_output=True, text=True, errors='ignore')

print('Exit:', res.returncode)
with open('debug_err.log', 'w', encoding='utf-8') as f:
    f.write(res.stderr)
