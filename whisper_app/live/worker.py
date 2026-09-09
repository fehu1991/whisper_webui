"""One WLK process per microphone session. stdin: framed PCM16; stdout: JSONL."""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import sys
from pathlib import Path

from whisper_app.live.models import local_model
from whisper_app.live.transcript import TranscriptAssembler
from whisper_app.privacy import configure_offline, deny_worker_network


async def run(size: str, language: str):
    base = Path(__file__).resolve().parents[2]
    configure_offline(base)
    deny_worker_network()
    protocol = sys.stdout
    sys.stdout = sys.stderr  # Third-party prints must never corrupt the protocol.
    logging.disable(logging.CRITICAL)

    def emit(data):
        protocol.write(json.dumps(data, ensure_ascii=False) + "\n")
        protocol.flush()

    processor = None
    try:
        from whisper_app.environment.runtime_paths import activate_gpu_dll_dirs
        dll_handles = activate_gpu_dll_dirs(base)
        from whisperlivekit import AudioProcessor, TranscriptionEngine, WhisperLiveKitConfig
        from opencc import OpenCC
        converter = OpenCC("s2tw") if language == "zh" else None

        def convert_rows(rows):
            if converter:
                for row in rows:
                    row["original_text"] = row["text"]
                    row["text"] = converter.convert(row["text"])
            return rows

        model_path = local_model(base, size)
        config = WhisperLiveKitConfig(
            backend="faster-whisper", backend_policy="localagreement",
            model_size=size, model_path=str(model_path), lan=language,
            warmup_file="", pcm_input=True, diarization=False,
            target_language="", min_chunk_size=0.5, asr_coalesce_min_s=0.5,
            retention_seconds=60, buffer_trimming_sec=10, log_level="CRITICAL",
        )
        engine = await asyncio.to_thread(TranscriptionEngine, config=config)
        processor = AudioProcessor(transcription_engine=engine)
        stream = await processor.create_tasks()
        assembler = TranscriptAssembler()

        async def output():
            async for response in stream:
                if response.error:
                    raise RuntimeError("串流辨識失敗。")
                state = await processor.get_current_state()
                # Processed audio can lead committed words; never use it as a pause.
                rows = convert_rows(assembler.update(state.tokens))
                lag = state.remaining_time_transcription_processing
                preview = assembler.preview + (response.buffer_transcription or "")
                emit({"type": "transcript", "rows": rows,
                      "preview": converter.convert(preview) if converter else preview,
                      "lag": lag})
                if lag > 30:
                    raise RuntimeError("辨識已落後超過 30 秒，請改用較小模型。")
            rows = convert_rows(assembler.update([], final=True))
            if rows:
                emit({"type": "transcript", "rows": rows, "preview": "", "lag": 0})

        output_task = asyncio.create_task(output())
        async def input_audio():
            while True:
                header = await asyncio.to_thread(sys.stdin.buffer.read, 4)
                if not header:
                    await processor.process_audio(b"")
                    break
                if len(header) != 4:
                    raise ValueError("音訊資料不完整。")
                length = struct.unpack("<I", header)[0]
                if length > 64000 or length % 2:
                    raise ValueError("音訊區塊格式錯誤。")
                data = await asyncio.to_thread(sys.stdin.buffer.read, length) if length else b""
                if len(data) != length:
                    raise ValueError("音訊連線中斷。")
                await processor.process_audio(data)
                if not length:
                    break

        emit({"type": "ready", "device": str(engine.asr.model.model.device),
              "compute_type": str(engine.asr.model.model.compute_type)})
        input_task = asyncio.create_task(input_audio())
        done, _ = await asyncio.wait([input_task, output_task], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if output_task in done and not input_task.done():
            raise RuntimeError("辨識程序提前結束。")
        await asyncio.wait_for(output_task, timeout=90)
        emit({"type": "done"})
    except Exception as exc:
        # Do not include third-party exceptions: they can contain transcript text.
        message = str(exc) if type(exc) in (ValueError, RuntimeError) and str(exc).startswith(("辨識已落後", "音訊", "辨識程序")) else "無法完成本機辨識。請確認模型、CUDA 環境及即時套件，或改用較小模型。"
        emit({"type": "error", "message": message})
    finally:
        if processor:
            await processor.cleanup()


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2]))
