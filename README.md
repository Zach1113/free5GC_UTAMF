# free5GC UT-AMF Research Environment

本 repository 是以 free5GC `v4.2.3` 為基礎建立的 5G Core 研究環境，用來比較兩種 AMF 訊息平行化設計：

- free5GC NGAP worker pool（`blog`）；
- 參考論文設計、在 NAS boundary 分派訊息的 AMF（`paper`）。

研究重點是觀察「分派依據」及「工作交接位置」如何影響 AMF 處理 UE 註冊與 PDU Session 建立的行為。這個 repository 保存完整的 Core source；修改版 AMF 則以獨立 submodule 管理，方便固定版本及單獨更新。

`paper` mode 參考 Nha 與 Nakao 的 *Multithreading-Based AMF Optimization for Pre-Slice Congestion Control in 5G Core Networks*（IEEE GC Wkshps 2025）所描述的 NAS-boundary hand-off。這裡研究的是其 dispatch boundary 與 subscriber-based key；論文中的 priority mechanism 不在目前實作範圍內。

## 研究設計

收到來自 gNB 的 NGAP 訊息後，AMF 可以在不同位置把工作交給 worker：

```text
gNB
 │
 │ NGAP message
 ▼
SCTP reader
 ├─ blog ─────────► 依 NGAP UE ID 選擇 worker ─► NGAP handler ─► NAS
 ├─ paper-early ──► 依 IMSI 選擇 worker ───────► NGAP handler ─► NAS
 └─ paper ────────► NGAP handler ──────────────► 依 IMSI 選擇 worker ─► NAS
```

三種 mode 的意義如下：

| Mode | Dispatch key | Worker hand-off 位置 | 用途 |
|---|---|---|---|
| `blog` | NGAP UE ID | NGAP handler 之前 | 正式實驗基準；free5GC 的 NGAP worker-pool 設計 |
| `paper` | IMSI | NGAP handler 內的 NAS boundary | 正式實驗比較組；參考論文的交接位置 |
| `paper-early` | IMSI | NGAP handler 之前 | 診斷組，用來把 dispatch key 與 hand-off 位置兩個變因拆開 |

正式比較只使用 `blog` 和 `paper`。`paper-early` 是本專案額外保留的診斷模式，不應當作論文設計的正式實驗組。

### 比較方式

模式和 worker 數應分開控制。例如：

```text
blog  + 1 worker
blog  + 4 workers
paper + 1 worker
paper + 4 workers
```

每個案例都應先確認 AMF startup log 顯示正確的 mode 和 worker 數，再執行相同的 UE registration、PDU Session establishment 與 user-plane connectivity 驗證。負載產生、重複次數、計時、統計及繪圖不由本 repository 目前的 mode-switching script 負責。

### 已知限制

- `paper` mode 在 NAS boundary 交接工作，NGAP handler 前段仍在 SCTP reader goroutine 執行，因此其 serial section 與 `blog` 不同。
- `paper` mode 存在已知的 teardown race；目前研究環境不以 deregistration 或 teardown performance 作為比較目標。
- `paper-early` 會提早取得 IMSI，目的是協助區分「改變 dispatch key」和「改變 hand-off 位置」的影響。
- 切換 mode 後必須重啟 AMF；執行中的 AMF 不會動態重新載入這些設定。

## Source layout

```text
.
├── NFs/
│   ├── amf/                 # 修改版 AMF Git submodule
│   └── ...                  # free5GC v4.2.3 的其他 NF source
├── config/amfcfg.yaml       # tracked 的基礎設定，不由切換腳本修改
├── scripts/
│   └── switch-amf-mode.sh
└── runtime/config/          # 生成的執行設定；Git ignored
```

版本基礎：

- free5GC：`v4.2.3`，commit `3b34a08e93a9b334f0f4005d3a3a9f79b66d59b9`
- 修改版 AMF：`feat/submodule`，目前 pin 在 commit `d1c749254442beeeb405234e2a50ba9afb460e41`

Clone 時必須同時取得 AMF submodule：

```bash
git clone --recurse-submodules https://github.com/Zach1113/free5GC_UTAMF.git
cd free5GC_UTAMF
```

如果已經 clone、但 AMF 目錄是空的：

```bash
git submodule update --init --recursive
```

## Switch AMF mode

使用方式：

```text
scripts/switch-amf-mode.sh MODE [WORKERS]
```

`MODE` 必須是 `blog`、`paper` 或 `paper-early`。`WORKERS` 是選填的正整數。

### 正式比較範例

```bash
# free5GC NGAP dispatch，1 worker
scripts/switch-amf-mode.sh blog 1

# free5GC NGAP dispatch，4 workers
scripts/switch-amf-mode.sh blog 4

# NAS-boundary dispatch，1 worker
scripts/switch-amf-mode.sh paper 1

# NAS-boundary dispatch，4 workers
scripts/switch-amf-mode.sh paper 4
```

診斷模式：

```bash
scripts/switch-amf-mode.sh paper-early 4
```

如果省略 `WORKERS`，腳本會保留現有 runtime config 的 worker 數；第一次執行時則沿用 tracked config 的設定：

```bash
scripts/switch-amf-mode.sh paper
```

為了避免正式實驗意外使用自動偵測值，腳本不接受顯式的 `0`。若基礎設定中的 `ngapWorkerPoolSize` 為 `0`，代表由 AMF 使用 `runtime.NumCPU()` 決定 worker 數；正式比較時應明確傳入正整數。

### 腳本會修改什麼

腳本不會直接更改 tracked 的 `config/amfcfg.yaml`，而是建立或更新：

```text
runtime/config/amfcfg.yaml
```

`runtime/` 已由 Git 忽略，所以切換 mode 不會污染 working tree。重複執行相同命令會得到相同設定。

檢查實際生成的值：

```bash
grep -E 'ngapSchedulerMode|ngapWorkerPoolSize' runtime/config/amfcfg.yaml
```

### 用生成的設定啟動 AMF

先建置 AMF：

```bash
make amf
```

啟動時必須明確使用生成的設定：

```bash
./bin/amf --config runtime/config/amfcfg.yaml
```

啟動後，log 應出現類似以下內容：

```text
Initializing NGAP worker pool with 4 workers (buffer size: 4096, mode: paper)
```

如果 log 中的 mode 或 worker 數與要求不同，請停止該次驗證，重新執行切換腳本並重啟 AMF。

## Upstream and license

Core source 基於 [free5GC](https://github.com/free5gc/free5gc)。修改版 AMF 來自 [amf-ngap-dispatch-bench](https://github.com/DBGR18/amf-ngap-dispatch-bench)，並透過 `NFs/amf` submodule 鎖定。各 upstream component 的授權與 notice 文件保留在相對應 source tree 中；repository 根目錄的授權資訊見 `LICENSE` 與 `THIRD-PARTY-NOTICES.txt`。
