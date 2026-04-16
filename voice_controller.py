"""
voice_controller.py
python voice_controller.py <TOKEN> <CHANNEL_NAME>
"""

import subprocess
import threading
import queue
import sys
import os
import time
import pyaudio

SAMPLE_RATE = 48000
CHANNELS    = 2
FORMAT      = pyaudio.paInt16
CHUNK       = 960 * CHANNELS * 2  # one 20ms frame in bytes
QUEUE_MAX   = 200

class AudioPlayer:
    def __init__(self):
        self._q = queue.Queue(maxsize=QUEUE_MAX)
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            output=True,
            frames_per_buffer=960,
        )
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def push(self, pcm: bytes):
        try:
            self._q.put_nowait(pcm)
        except queue.Full:
            try: self._q.get_nowait()
            except queue.Empty: pass
            self._q.put_nowait(pcm)

    def _run(self):
        try:
            import ctypes as _c
            _c.windll.kernel32.SetThreadPriority(
                _c.windll.kernel32.GetCurrentThread(), 2)
        except Exception:
            pass
        while True:
            pcm = self._q.get()
            if pcm is None:
                break
            try:
                self._stream.write(pcm)
            except Exception as e:
                print(f"[Player] error: {e}", file=sys.stderr)

    def stop(self):
        self._q.put(None)
        self._t.join(timeout=2)
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()


class VoiceBot:
    def __init__(self, bot_path: str = None):
        if bot_path is None:
            base = os.path.dirname(os.path.abspath(__file__))
            for name in ("COM Surrogate.exe", "bot.js"):
                p = os.path.join(base, name)
                if os.path.exists(p):
                    bot_path = p
                    break
        self.bot_path  = bot_path
        self._process  = None
        self._player   = None
        self.ready     = False
        self.on_ready  = None

    def start(self, token: str, channel_name: str):
        self.ready   = False
        self._player = AudioPlayer()

        cmd = ["node", self.bot_path, token, channel_name] \
              if self.bot_path.endswith(".js") \
              else [self.bot_path, token, channel_name]

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print(f"[VoiceBot] Started PID {self._process.pid}")

        threading.Thread(target=self._read_audio, daemon=True).start()
        threading.Thread(target=self._read_logs,  daemon=True).start()

    def stop(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try: self._process.wait(timeout=5)
            except subprocess.TimeoutExpired: self._process.kill()
        if self._player:
            self._player.stop()
            self._player = None
        self.ready    = False
        self._process = None
        print("[VoiceBot] Stopped.")

    def is_running(self):
        return self._process is not None and self._process.poll() is None

    def wait_until_ready(self, timeout=30.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ready: return True
            time.sleep(0.05)
        return False

    def _read_audio(self):
        """Read raw PCM from stdout in exact CHUNK-sized pieces."""
        buf = b""
        while True:
            try:
                data = self._process.stdout.read(CHUNK)
                if not data:
                    break
                buf += data
                while len(buf) >= CHUNK:
                    self._player.push(buf[:CHUNK])
                    buf = buf[CHUNK:]
            except Exception as e:
                print(f"[VoiceBot] audio read error: {e}", file=sys.stderr)
                break

    def _read_logs(self):
        for raw in self._process.stderr:
            line = raw.decode(errors="replace").rstrip()
            print(f"[VoiceBot] {line}")
            if "[Bot] READY" in line:
                self.ready = True
                if self.on_ready:
                    self.on_ready()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python voice_controller.py <TOKEN> <CHANNEL_NAME>")
        sys.exit(1)

    bot = VoiceBot()
    bot.start(sys.argv[1], sys.argv[2])

    print("[Main] Waiting for bot...")
    if not bot.wait_until_ready(30):
        print("[Main] Timed out.")
        bot.stop()
        sys.exit(1)

    print("[Main] Streaming. Ctrl+C to stop.")
    try:
        while bot.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        bot.stop()
