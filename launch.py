"""
Launch the Playable Ad Generator.
Run with: python launch.py
"""
import subprocess
import sys
import time
import webbrowser

PORT = 8000
URL = f"http://localhost:{PORT}"


def main():
    print("=" * 50)
    print("  Playable Ad Generator")
    print("=" * 50)
    print(f"  Starting server on {URL}")
    print("  Press Ctrl+C to stop.")
    print("=" * 50)

    server = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "app:app",
            "--host", "0.0.0.0",
            "--port", str(PORT),
            "--reload",
        ]
    )

    # Give the server a moment to start before opening the browser
    time.sleep(2)
    webbrowser.open(URL)

    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
