import subprocess
import os

def create_test_video(path):
    # Create a 5 second test video
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=5:size=1920x1080:rate=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", path
    ]
    subprocess.run(cmd, check=True)

if __name__ == "__main__":
    test_video = "test_video.mp4"
    create_test_video(test_video)
    print(f"Created {test_video}")
    
    # Try to run the cover generator
    # We'll need to mock some things or just run it as is if it's standalone
    import cover_generator
    try:
        results = cover_generator.generate_covers(test_video, "Test Title HIGHLIGHTS", "test_output")
        print("Results:", results)
    except Exception as e:
        print("Error during cover generation:", e)
