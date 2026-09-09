# Whisper 工作台架構

## 邊界

- `whisper_app/live`：WhisperLiveKit 子程序、PCM 串流、本機工作儲存與頁面路由。`/live/#capture` 與 `/live/#editor` 是兩個互斥顯示的工作頁，共用收音狀態。
- `文字稿編輯工具.html`：原有獨立工具及同源嵌入橋接。已確認片段只附加，編輯快照獨立儲存。
- `whisper_app/privacy.py`：正式執行的離線與使用統計設定；下載僅出現在明確的部署流程。

- `app.py`：桌面 Gradio 元件、輸入驗證、流程編排與狀態呈現。
- `whisper_app/domain`：轉錄請求、結果、環境報告與任務狀態資料模型。
- `whisper_app/services`：轉錄、說話人分離、說話者指派、輸出、歷史、品質設定與儲存管理。
- `whisper_app/environment`：硬體／runtime 掃描、路徑啟用與建議規則。
- `whisper_app/jobs`：單一共享推理資源、取消 token 與任務歷史。
- `scripts`：無虛擬環境掃描、發行檢查、真實推論試跑與發行包建立。

## 主要資料流

1. UI 將單檔或批次設定轉為 `TranscriptionRequest`。
2. `JobManager` 取得唯一推理資源並提供取消 token。
3. `TranscriptionService` 選擇 CPU／CUDA runtime，逐段產生 `TranscriptSegment`。
4. 啟用說話人分離時，`DiarizationService` 產生匿名說話者時間片段，`assign_speakers` 再合併到轉錄句段。
5. `write_transcription_outputs` 原子寫入選定格式；完成後建立 history manifest。
6. UI、TXT、JSON、SRT、VTT 都使用同一個 `sequence` 與 `segment_id`。

## 設計決策

- 原音檔轉錄保留 Gradio 並掛載到 FastAPI 根路徑；即時收音使用獨立網頁與持續存在的編輯器，不把逐段編輯塞進 Gradio 表格。
- 即時辨識固定 WLK 0.2.26／faster-whisper／LocalAgreement，使用既有 CTranslate2 模型。每場啟動新子程序避免引擎 singleton 與 GPU 快取跨工作干擾；不用雲端備援，也不在錄音時下載模型。
- 不把 AMD／Intel 當成 CUDA 故障：沒有 NVIDIA CUDA 硬體時提供 CPU／int8 建議。
- `auto` 可在 CUDA 載入失敗時退回 CPU；使用者明確指定 `cuda` 時則直接回報錯誤。
- 同一時間只允許一個單檔或批次工作使用推理資源，避免模型與 GPU cache 互相破壞。
- 輸出先寫暫存檔再替換；取消或失敗會移除本次已建立的半成品。
