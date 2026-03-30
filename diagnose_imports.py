import sys
import traceback

def check_import(name):
    print(f"[*] Checking: {name}")
    try:
        __import__(name)
        print(f"    [+] OK")
    except ImportError as e:
        print(f"    [-] ImportError: {e}")
        # traceback.print_exc()
    except Exception as e:
        print(f"    [!] Error: {e}")
        traceback.print_exc()

print(f"Python version: {sys.version}")
print(f"Python path: {sys.path}\n")

check_import("f5_tts")
check_import("audio_separator")
check_import("pydub")
