"""Explicit, online deployment step; never called by the runtime."""
from pathlib import Path
from huggingface_hub import snapshot_download

if __name__ == "__main__":
    base = Path(__file__).resolve().parents[1]
    snapshot_download("Systran/faster-whisper-small", cache_dir=str(base / "models"),
                      allow_patterns=["*.json", "*.bin", "*.txt"])
    from whisperlivekit.silero_vad_iterator import load_onnx_session
    load_onnx_session()  # WLK ships its VAD; verify that the packaged model loads.
    print("small 模型與本機語音活動偵測已備妥。")
