# Whisper 本機轉錄工作台

這是 Windows 桌面版的本機語音轉文字工具。音訊與轉錄結果留在自己的電腦，程式不會把音檔上傳到雲端。支援單檔、批次、麥克風錄音、TXT／SRT／VTT／JSON 輸出，也可選用 pyannote 加入匿名說話人標籤。

GitHub 版本不含模型、Python 虛擬環境或轉錄資料。第一次使用時，雙擊 `DeployWhisper.cmd`，程式會把所需內容下載到同一資料夾。

## 一分鐘安裝順序

1. 確認電腦是 Windows 10 或 Windows 11 的 64 位元版本。
2. 安裝 [Python 3.13.15 Windows 64 位元版](https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.exe)。安裝畫面務必勾選 `Add python.exe to PATH`。
3. 從 GitHub 下載 ZIP，完整解壓縮到本機資料夾。
4. 雙擊 `DeployWhisper.cmd`，依畫面指示等待安裝與模型下載完成。
5. 雙擊 `WhisperDoctor.cmd` 檢查環境。
6. 雙擊 `RunWhisper.cmd` 啟動介面。

只需要語音轉文字的人，不必申請 Hugging Face 帳號。安裝時遇到 pyannote 問題，可輸入 `N` 略過，之後仍能正常轉錄。

## 電腦需求

| 項目 | 必要條件 | 建議 |
|---|---|---|
| 作業系統 | Windows 10／11，64 位元 x64 | 安裝最新 Windows 更新 |
| Python | 64 位元 Python 3.11、3.12 或 3.13 | 使用 Python 3.13；目前不支援 Python 3.14 |
| 記憶體 | 8 GB，可使用 base／small | 16 GB 以上較適合 medium、large-v3 與說話人標註；長音檔可準備 32 GB |
| 磁碟 | 首次部署至少保留 15 GB | 建議 20 GB；安裝 NVIDIA GPU 環境時建議保留 30 GB |
| 網路 | 第一次安裝與模型下載必須連線 | 穩定寬頻；下載可能需要一段時間 |
| 瀏覽器 | Edge、Chrome 或 Firefox 桌面版 | 瀏覽器視窗寬度至少 1280 px |
| GPU | 不需要，CPU 可直接執行 | NVIDIA GPU 可加速；AMD／Intel GPU 目前使用 CPU 模式 |
| 其他 | Windows PowerShell 5.1 | 多數 Windows 10／11 已內建 |

程式使用套件內附的 FFmpeg，不必另外安裝。Windows 若缺少 C++ 執行元件，請安裝 [Microsoft Visual C++ x64 Runtime](https://aka.ms/vc14/vc_redist.x64.exe)。

## 從 GitHub 下載

建議從 GitHub 右側的 `Releases` 下載發布 ZIP。若沒有 Release，按綠色 `Code` 按鈕，再選 `Download ZIP`。

下載後依序處理：

1. 在 ZIP 上按滑鼠右鍵，選「內容」。如果畫面下方出現「解除封鎖」，先勾選並按「確定」。
2. 按「全部解壓縮」。不要直接在 ZIP 視窗裡執行 CMD。
3. 建議解壓縮到 `C:\WhisperWorkbench` 或 `D:\WhisperWorkbench`。避免放在 `Program Files`、網路磁碟或會同步的雲端資料夾。
4. 開啟解壓縮後的資料夾，應該能看到 `DeployWhisper.cmd`、`WhisperDoctor.cmd`、`RunWhisper.cmd`、`WhisperTools.cmd` 與本說明。

如果 Windows 顯示保護警告，先確認檔案來自本專案的 GitHub 頁面。確認無誤後，可選「其他資訊」再選「仍要執行」。

## 第一次部署

雙擊 `DeployWhisper.cmd`。部署程式會依序完成以下工作：

1. 檢查 Windows、Python 位元數、Python 版本與磁碟空間。
2. 在目前資料夾建立 `.venv`，不會改動其他 Python 專案。
3. 安裝 Whisper、Gradio 介面與內附 FFmpeg。
4. 下載 `base`、`small`、`medium`、`large-v3` 四個 Whisper 模型，合計約 5 GB。
5. 用 CPU 實際載入 base 模型，確認基本轉錄環境可用。
6. 詢問是否安裝 pyannote 說話人標註。

下載途中不要關閉黑色視窗。網路中斷、電腦重新啟動或下載失敗時，可再次雙擊 `DeployWhisper.cmd`；已完成的套件與模型會沿用。

### 說話人標註

pyannote 產生 `SPEAKER_00`、`SPEAKER_01` 等匿名標籤，用來區分同一音檔中的不同聲音。它不會辨識真實姓名。

需要這項功能時：

1. 建立或登入 [Hugging Face 帳號](https://huggingface.co/join)。
2. 開啟 [pyannote community-1 模型頁](https://huggingface.co/pyannote/speaker-diarization-community-1)，閱讀並接受模型條款。
3. 到 [Access Tokens](https://huggingface.co/settings/tokens) 建立 `Read` token。
4. 回到部署視窗貼上 token。輸入時畫面不會顯示字元。

token 只供當次下載使用，不會寫入專案設定、環境報告或轉錄檔。若顯示 `401 Unauthorized`，通常是 token 無效；`403 Forbidden` 通常表示尚未接受模型條款，或 token 沒有 gated model 讀取權限。

## 四個 CMD 工具

### DeployWhisper.cmd

首次安裝入口。負責檢查環境、建立 `.venv`、安裝套件、下載四個 Whisper 模型，並選擇是否安裝 pyannote。重新執行時會沿用已完成的內容，可用來補完中斷的下載。

### WhisperDoctor.cmd

環境檢查工具，不會安裝套件或刪除資料。它會檢查：

- Windows、Python、CPU、記憶體與磁碟空間。
- NVIDIA／AMD／Intel 顯示裝置。
- NVIDIA 驅動、CUDA、CTranslate2、PyTorch 與 FFmpeg。
- Whisper／pyannote 套件與本機模型。

完整報告儲存在 `.cache\environment\environment-report.json`。報告會隱藏個人路徑，也不會記錄 Hugging Face token。

### RunWhisper.cmd

日常啟動入口。黑色視窗必須保持開啟；關閉視窗就會停止程式。啟動後瀏覽器通常會自動開啟 `http://127.0.0.1:7860`。如果 7860 已被占用，程式會改用下一個可用連接埠，請以黑色視窗顯示的網址為準。

這是本機網址，不代表音檔已上傳網路。只有同一台電腦能連線。

### WhisperTools.cmd

維護與進階設定入口。主選單功能如下：

| 選項 | 功能 | 何時使用 |
|---|---|---|
| 1 | 完整環境檢測 | 部署後或故障時 |
| 2 | GPU 診斷與 faster-whisper CUDA 試跑 | NVIDIA GPU 設定完成後 |
| 3 | 安裝已驗證的基本依賴 | `.venv` 遺失或基本套件損壞時 |
| 4 | 安裝 CUDA 版 PyTorch | NVIDIA GPU 要加速 pyannote 時 |
| 5 | 安裝 pyannote 依賴 | 之後才決定使用說話人標註時 |
| 6 | 部署完整 NVIDIA GPU 環境 | 想使用 CUDA 加速時 |
| 7 | 重新套用已驗證的套件版本 | 套件需要修復或更新時 |
| 8 | 清理殘留檔、檢查相依，或重建 `.venv` | 環境嚴重損壞時；刪除前會再次詢問 |
| 9 | 查看、下載或更新 Whisper 模型 | 補下載 tiny 或重抓模型時 |
| 10 | 下載 pyannote 本機模型 | 已接受條款並準備好 token 時 |
| 11 | 驗證說話人標註 | pyannote 下載完成後 |
| 12 | 啟動 Whisper 介面 | 等同日常啟動 |

AMD 或 Intel 顯示裝置不要執行選項 4、6；目前請使用 CPU 模式。

## 模型怎麼選

| 模型 | 約略下載量 | 適合情況 |
|---|---:|---|
| tiny | 未隨部署下載 | 最慢電腦、快速試用；準確度最低，可用工具選項 9 下載 |
| base | 141 MB | 入門、短錄音、速度優先 |
| small | 464 MB | 一般中文錄音，速度與準確度較平衡 |
| medium | 1.46 GB | 中文會議、訪談，建議 16 GB 記憶體 |
| large-v3 | 2.95 GB | 準確度優先；耗時、記憶體與 GPU 顯示記憶體需求最高 |

第一次不確定時，CPU 電腦先選 `small`，NVIDIA GPU 電腦可從 `medium` 開始。裝置保持 `auto`；CPU 模式會自動改用 `int8`，不必手動調整。

## 實測資料

以下數據是本專案在指定硬體與設定下的本機實測結果，實際速度仍會受到音檔內容、電腦負載、暫存資料與背景程式影響，因此其他電腦不一定會得到完全相同的時間。

### 測試設定與硬體

| 項目 | 本次測試設定 |
|---|---|
| 模型 | `large-v3` |
| 裝置 | `cuda`（使用 NVIDIA GPU） |
| 精度 | `float16` |
| 辨識細節精度 | `10` |
| GPU | RTX 5050，8 GB GDDR6 |
| CPU | AMD Ryzen 5 3500X |

### 測試音檔與轉檔時間

| 音檔 | 音檔時長 | 轉檔用時 |
|---|---:|---:|
| A 檔案 | 01:10:46 | 11 分 31 秒 |
| B 檔案 | 00:05:58 | 09 分 18 秒 |
| A+B | 01:16:44 | 20 分 49 秒 |

本次功能使用排程接續轉檔。B 檔案開始轉檔時會受到 A 檔案暫存資料影響，因此 B 檔案的轉檔效率會降低；上表的 B 檔案時間應搭配這項測試條件理解。

### 測試結果與辨識限制

- 本次測試的辨識正確率至少為 97%；目前尚未進一步細算精確數值，這不是對所有音檔都適用的保證值。
- 比較容易出錯的內容包括：人名、不常見的單字、多人搶話、語速過快，以及連音或黏音。
- 若內容包含上述情況，建議回聽音檔並人工校對重要的人名、專有名詞與關鍵句子。

## 開始轉錄

1. 雙擊 `RunWhisper.cmd`，不要關閉黑色視窗。
2. 在瀏覽器選擇音檔、麥克風錄音或批次檔案。
3. 初次使用可選「CPU 品質」或「平衡」設定檔，再選輸出格式。
4. 已安裝 pyannote 時，可勾選說話人標註；沒有安裝就不要勾選。
5. 按「開始轉錄」。輸出會放在 `transcriptions` 資料夾，不會覆蓋舊結果。

支援的輸出包括時間軸 TXT、純文字 TXT、SRT、VTT 與 JSON。介面、字幕與文字檔使用相同句段編號，方便核對內容。

## 文字稿編輯工具

`文字稿編輯工具.html` 是獨立的本機網頁工具，專門用來整理 Whisper 產生的結構化 TXT 文字稿。它不需要安裝套件、不需要模型，也不會把檔案上傳到網路。

### 開啟方式

1. 雙擊 `文字稿編輯工具.html`。
2. 若 Windows 跳出「選擇要用哪個程式開啟」，選擇 Chrome、Edge 或其他現代瀏覽器。
3. 工具會直接在瀏覽器分頁中執行；關閉分頁前，請先下載修改後的 TXT。

### 可以處理的文字稿格式

工具主要讀取下列格式的 TXT 內容：

```text
1. [SPEAKER_02] [00:00:00.000 - 00:00:00.500] 碰到啊
```

編號可以省略，編號與時間碼周圍多出空白也可以讀取。時間格式必須是 `時:分:秒.毫秒`，例如 `00:12:34.567`。無法辨識的行會保留在表格中，標示為「未解析原始行」，修改後仍會原樣輸出，不會靜默刪除。

### 載入檔案

- 可以拖放或選取多個 `.txt` 檔案。
- 第一個載入的檔案是主檔，會決定預設下載檔名；後續檔案會依選取順序接在末尾，不會取代前一份內容，也不會自動重新編號。
- 可重複載入檔案。也可以把文字貼到貼上區，選擇「以貼上內容重新開始」或「附加貼上內容」。
- 讀取編碼可選「自動判斷」、UTF-8 或 Big5；輸出換行可選 Windows（CRLF）或 Unix（LF）。

### 編輯與整理

載入後，每一行可直接修改句型編號、說話者、開始時間、結束時間與文字內容。勾選行後，可以使用下列工具：

- 搜尋編號、說話者、時間或文字，也可以只搜尋文字或說話者。
- 篩選已解析、未解析、已選行、空白文字，或依說話者篩選。
- 對目前搜尋結果執行文字取代。搜尋「全部欄位」時，會修改說話者、文字與未解析原始行，不會修改編號與時間。
- 插入新行、重新編號、批次修改說話者，以及將選取行的時間整體前後位移。
- 對選取行或目前篩選結果批次加上前綴、加上後綴、移除指定文字、清除前後空白，或合併連續空白。
- 每列右側的操作選單可前插、後插、複製、上移、下移或刪除。前插、後插與複製會自動遞延後續編號；上移與下移只改變順序。

工具另提供「暫存詞彙」區，可放入常用的人名、專有名詞或口頭禪，按「複製」後貼到文字稿。這些詞彙只保留在目前分頁，關閉或重新開啟工具後會恢復預設值。

### 預覽與下載

在「輸出範圍」選擇要輸出的內容：全部資料、已選行或目前篩選結果。按「預覽」後，可以先修改預覽文字；只有選擇「全部資料」時，才能把預覽內容套用回表格。最後可選擇複製內容、下載目前預覽，或直接下載 TXT。

下載檔案會使用 UTF-8 加 BOM，檔名中的 Windows 禁用字元會自動替換，副檔名也會自動補上 `.txt`。

### 使用限制

- 這個工具的輸入與輸出都是 TXT，不能直接編輯 SRT、VTT 或 JSON。
- 工具不會自動儲存編輯進度，也不使用瀏覽器的 localStorage；重新整理或關閉分頁後，尚未下載的修改會消失。
- 重要內容請先下載備份，再繼續大量修改。
- 工具適合在電腦瀏覽器使用；文字表格欄位較多，小螢幕可能需要左右捲動。

## NVIDIA GPU 加速

先完成一般部署並確認 CPU 可以執行，再設定 GPU：

1. 安裝或更新 [NVIDIA 官方驅動](https://www.nvidia.com/en-us/drivers/)。
2. 雙擊 `WhisperTools.cmd`，執行選項 6。
3. 回到主選單執行選項 2，選擇 CUDA 試跑。
4. 試跑通過後，介面的裝置保持 `auto` 即可。

GPU 設定不完整時，`auto` 會退回 CPU。手動選 `cuda` 則會直接顯示錯誤。CTranslate2 的 Windows GPU 路徑需要 CUDA 12.x；只用 CPU 的電腦不需要安裝 CUDA。

## 常見問題

| 畫面或錯誤 | 處理方式 |
|---|---|
| 找不到 Python | 安裝 Python 3.13 x64，勾選 `Add python.exe to PATH`，安裝完成後重新開啟資料夾 |
| 只有 Python 3.14 | 另裝支援的 Python 3.13；部署程式會優先使用 3.13 |
| `DLL load failed` | 安裝 Microsoft Visual C++ x64 Runtime，重新開機後再部署 |
| 模型下載到一半失敗 | 重新執行 `DeployWhisper.cmd`，程式會沿用已下載內容 |
| `401 Unauthorized` | 重新建立 Hugging Face Read token |
| `403 Forbidden` | 先到 pyannote 模型頁接受條款，並確認 token 可讀取 gated model |
| 缺少 `cublas64_12.dll` | 先使用 CPU；NVIDIA 使用者執行工具選項 6 |
| 瀏覽器沒有自動開啟 | 查看黑色視窗中的網址，手動貼到瀏覽器 |
| 介面顯示太窄 | 將瀏覽器最大化；本版最低寬度為 1280 px，不支援手機版 |
| 中文顯示成亂碼 | 不要用 ANSI 編碼另存 CMD／PS1；重新下載原始發布 ZIP |

## 部署後產生的資料夾

| 資料夾 | 內容 | 可以刪除嗎 |
|---|---|---|
| `.venv` | 本專案專用 Python 與套件 | 可刪，但下次必須重新部署 |
| `models` | Whisper 與 pyannote 模型 | 可刪，但下次必須重新下載 |
| `.cache` | 環境報告與下載快取 | 可刪；診斷與安裝時會重建 |
| `transcriptions` | 轉錄結果 | 刪除前先備份需要的檔案 |
| `.whisper` | 使用者介面設定 | 可刪；會恢復預設設定 |

發布版的 `.gitignore` 已排除上述本機資料。把本資料夾放到自己的 GitHub 時，不會誤傳模型、虛擬環境、token 或轉錄結果。
