# Whisper 本機轉錄工作台

在自己的 Windows 電腦上，把錄音檔轉成文字，或現場收音、即時轉錄並修改文字稿。**音檔與文字稿不送往雲端辨識。**

目前版本：`1.2.1`。GitHub 只提供程式與工具，不含模型、錄音或使用者資料；模型會在首次部署時下載。

## 先選你要做的事

| 需求 | 使用方式 |
|---|---|
| 錄音檔轉文字 | 啟動後使用原有音檔頁，支援單檔、批次與 TXT／SRT／VTT／JSON 輸出 |
| 現場即時轉錄 | 安裝即時功能後進入「即時收音」；切到「文字稿編輯」可邊聽邊改，切頁不中斷收音 |
| 整理已有的文字稿 | 雙擊 `文字稿編輯工具.html`，匯入結構化 TXT，不必載入模型 |
| 區分說話人 | 音檔轉錄可選用 pyannote；即時模式目前需手動標註 |

## 第一次使用

1. 準備 **Windows 10／11 x64、64 位元 Python 3.11～3.13**。安裝 Python 時勾選 `Add python.exe to PATH`；本版不支援 Python 3.14。
2. 在本頁按 **Code → Download ZIP**，對 ZIP 按右鍵選「全部解壓縮」。不要在 ZIP 裡直接點 CMD，也不要只下載個別檔案。
3. 雙擊 `DeployWhisper.cmd`，等待套件與模型下載完成。只需要轉文字時，pyannote 選項輸入 `N` 略過。
4. 雙擊 `WhisperDoctor.cmd` 檢查環境。
5. 需要現場即時轉錄，再雙擊 `DeployLive.cmd`；只做音檔轉錄可略過。
6. 雙擊 `RunWhisper.cmd` 開始使用。黑色視窗需保持開啟，關閉就會停止服務。

第一次下載可能需要一段時間，不是點一下就立即完成。詳細安裝畫面、GPU 設定與故障處理請看 [完整使用手冊](docs/USER_GUIDE.md)。

## 電腦需求

| 項目 | 需求 |
|---|---|
| 作業系統與 Python | Windows 10／11 x64；Python 3.11～3.13 x64 |
| 記憶體 | 基本音檔轉錄至少 8 GB；建議 16 GB 以上，長音檔可準備 32 GB |
| 可用空間 | 首次基本部署至少 15 GB，建議 20 GB；含 NVIDIA GPU 環境建議 30 GB |
| 顯示卡 | CPU 可執行；NVIDIA GPU 可加速。AMD／Intel GPU 目前使用 CPU 模式 |
| 即時收音 | 麥克風、桌面 Edge 或 Chrome，並允許本機頁面使用麥克風 |
| 其他 | Windows PowerShell 5.1；缺少 C++ 元件時需安裝 Visual C++ x64 Runtime |
| 網路 | 首次部署及模型下載需要網路；完成部署後可離線使用 |

FFmpeg 隨套件提供，不必另裝。CPU 能載入模型不代表一定跟得上現場語速，正式使用前請用實際麥克風測試。[完整環境需求與下載連結](docs/USER_GUIDE.md#電腦需求)

## 平常只需要這些入口

| 最外層檔案 | 什麼時候點 |
|---|---|
| `DeployWhisper.cmd` | 第一次安裝基本功能 |
| `DeployLive.cmd` | 加裝即時轉錄功能 |
| `RunWhisper.cmd` | 每次啟動工作台 |
| `WhisperDoctor.cmd` | 檢查電腦與環境 |
| `WhisperTools.cmd` | GPU 設定、模型管理與環境維護 |
| `文字稿編輯工具.html` | 單獨編輯已有的 TXT 文字稿 |

CMD 會自動呼叫內部腳本，**不用進入子資料夾找程式，也不要把 CMD 單獨移走。**

## 說明文件

- [安裝與完整使用手冊](docs/USER_GUIDE.md)：部署、GPU、工具選單、模型選擇、常見問題。
- [即時轉錄與保密操作](docs/LIVE_TRANSCRIPTION.md)：收音、切頁編輯、自動儲存、離線驗證與資料保留。
- [文字稿編輯工具操作](docs/USER_GUIDE.md#文字稿編輯工具)：TXT 格式、搜尋取代、批次修改與匯出。
- [原音檔轉錄實測數據](docs/USER_GUIDE.md#實測資料)：RTX 5050 的耗時與辨識限制；不代表即時模式效能。
- [版本變更](docs/CHANGELOG.md) · [程式架構](docs/ARCHITECTURE.md)

## 資料夾怎麼分

```text
whisper_webui/
├─ README.md                  ← 從這裡開始
├─ *.cmd                      ← 安裝、啟動與維護入口
├─ 文字稿編輯工具.html          ← 可獨立開啟的編輯工具
├─ docs/                      ← 完整說明與版本紀錄
├─ scripts/                   ← CMD 自動呼叫的內部腳本
├─ requirements/              ← 套件版本清單，不必手動開啟
├─ whisper_app/               ← 轉錄、即時收音與網頁程式碼
├─ app.py                     ← 主程式，由 CMD 啟動
└─ VERSION                    ← 版本資訊
```

模型、環境與工作資料在部署或使用後才會產生，不放進 GitHub。目錄分類不影響原有功能。

## 機密會議使用前

先完成部署，使用非機密語音測試，再斷網驗證收音、辨識、修改及重新載入。請勿把專案放在雲端同步資料夾。

即時錄音預設不存檔，但**文字稿與人工修改會保存在本機 `.whisper/`**，且不會自動清除；輸出檔位於 `transcriptions/`。獨立開啟 HTML 不會自動儲存，關閉前請下載 TXT。

程式的本機設計不等於資安認證。資料保存、磁碟加密與設備管理仍須依組織規範處理；詳見 [保密操作說明](docs/LIVE_TRANSCRIPTION.md)。
