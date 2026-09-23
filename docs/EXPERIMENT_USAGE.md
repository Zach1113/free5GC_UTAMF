# AMF dispatch 實驗交接與使用說明

本文對應同一份工作區中的三個程式碼範圍：

| 範圍 | 位置 | 用途 |
| --- | --- | --- |
| Core | `free5GC_UTAMF/` | 啟停 free5GC、產生 Core 設定、收集 AMF trace、驗證結果 |
| AMF | `free5GC_UTAMF/NFs/amf/` | `blog`／`paper` 排程與 AMF 探測點；它是 Core 的 Git submodule |
| RAN/UE | `free-ran-ue/` | 單一 gNB、可設定數量的 UE、namespace 與 RAN/UE trace |

**從 Core 工作區執行** [`examples/run_experiment.sh`](../examples/run_experiment.sh)。每次執行一組設定，建立一個新的 `RUN_ID`；實驗組可編輯腳本，增加 UE 數、流量或重複次數。`UE_COUNT=1` 只是範例預設，不是正式實驗的 UE 規格。目前 gNB 固定為一個。

## 1. 目錄與版本

在新 VM 上，將 Core 與 RAN checkout 放在相鄰目錄，並初始化 Core 的 AMF submodule：

```bash
cd /path/to/free5GC_UTAMF
git submodule update --init --recursive
```

單 VM 範例會從 Core 的相鄰目錄尋找 `free-ran-ue`；若使用其他位置，在腳本頂端設定 `RAN_REPO`。Core 的執行檔在 `bin/`，RAN 執行檔在 `build/`。兩側 `config/env.local`、編譯產物與 `runtime/` 不隨 Git checkout 提供，範例腳本會產生所需設定並編譯。保存實驗資料時，一併保存兩側 manifest 中的版本、設定 fingerprint 與來源狀態欄位。

## 2. 主機條件

在 **Core VM** 準備 Go、Python 3 + PyYAML、`mongosh`/可連線的 MongoDB、`gtp5g` kernel module、`iproute2`、`iptables`、sudo 權限，以及可用的 free5GC NF 設定。單 VM 還需要能建立或使用 network namespace。在 **RAN VM** 準備 Go、Python 3 + PyYAML、`iproute2`、sudo 權限，以及建立 UE TUN 介面的能力。這份工作區的 live smoke 使用 Go 1.26.2；版本以實際相依套件與編譯結果為準。

先檢查：

```bash
cd /home/ubuntu/UTokyo_research/free5GC_UTAMF
command -v go python3 mongosh ip iptables
python3 -c 'import yaml; print(yaml.__version__)'
lsmod | grep '^gtp5g'
sudo -v
```

腳本會讀寫 **Core VM 的 `free5gc` MongoDB**，依 RAN UE 設定為缺少的 IMSI 建立 development subscriber；已有的 subscriber 原則上保留。只在實驗用資料庫執行。UE 的認證資料從 RAN `runtime/config/ue.yaml` 讀取，勿把該檔或完整執行日誌公開分享。

## 3. 單 VM：Core + namespace 內的 gNB/UE

現有 VM 已有 `free-ran-ns`（gNB）與 `free-ue-ns`（UE），範例腳本的預設值會**沿用**它們；腳本會檢查 IP，停止時不刪除這兩個既有 namespace。沿用模式假設既有路由、IP forwarding 與 UE 資料面的 NAT 已配置好，腳本不會代為建立。啟動前可檢查：

```bash
sudo ip netns list
sudo ip netns exec free-ran-ns ip -br addr
sudo ip netns exec free-ue-ns ip -br addr
sudo ip netns exec free-ran-ns ip route
sudo ip netns exec free-ue-ns ip route
sysctl net.ipv4.ip_forward
sudo iptables -t nat -S POSTROUTING
```

範例預設的網路是 Core host `10.0.1.1`、RAN N2/N3 `10.0.1.2`、gNB/UE 控制面 `10.0.2.1`/`10.0.2.2`、UE PDU subnet `10.60.0.0/16`。`CORE_INTERFACE=ens33` 是**這台 VM** 的外部介面名稱，在其他 VM 必須改為當地介面。IP 也必須符合當地拓樸。

若是新 VM、沒有上述既有 namespace，先編輯腳本，把 `EXISTING_RAN_NS` 和 `EXISTING_UE_NS` **都設為空字串**。`network-up` 會建立屬於本 checkout 的兩個 namespace、veth 與 NAT；腳本完成後會執行 `network-down` 清理。建立前確認範例的 `10.0.1.0/24`、`10.0.2.0/24` 未與主機既有網路衝突。

執行：

```bash
cd /home/ubuntu/UTokyo_research/free5GC_UTAMF
# 先編輯 examples/run_experiment.sh 頂端的參數
bash examples/run_experiment.sh
```

腳本需要本機 sudo 權限（必要時會提示密碼），接著依序產生 runtime 設定、編譯 Core/AMF/RAN、補齊 subscriber、啟動網路與 Core、啟動 gNB/UE、等待 `RUN_HOLD_SECONDS`、依序停止 RAN 與 Core、驗證 trace。請保留終端機最後印出的兩個資料路徑。

## 4. 雙 VM：Core 與 RAN 分開

在 **Core VM** 執行同一支腳本；RAN VM 要先放好對應的 `free-ran-ue` checkout。編輯腳本頂端：

| 參數 | 雙 VM 設法 |
| --- | --- |
| `DEPLOYMENT_MODE` | `dual-vm` |
| `RAN_SSH` | 可從 Core VM 非互動登入的 `user@ran-vm` |
| `RAN_REPO` | RAN VM 上 `free-ran-ue` 的絕對路徑 |
| `EXISTING_RAN_NS`、`EXISTING_UE_NS` | 兩者均設為空字串；雙 VM 的 gNB/UE 在 RAN VM 主網路命名空間執行 |
| `CORE_VM_IP`、`N2_AMF_IP`、`N3_UPF_IP` | Core VM 上可供 RAN VM 連線的 IP；本範例三者設為同一 IP |
| `RAN_VM_IP`、`RAN_N2_IP`、`RAN_N3_IP`、`RAN_CONTROL_IP`、`RAN_DATA_IP` | RAN VM 可用的 IP；最簡設定可全部設為同一 IP |
| `CORE_INTERFACE` | Core VM 的外部資料面介面 |
| `UE_NS_IP` | 設定契約要求此欄位；雙 VM 模式不建立 UE namespace |

例如兩台 VM 互通 IP 分別是 `192.168.56.101` 與 `192.168.56.102`，可把 Core 相關 IP 設為 `.101`、RAN 相關 IP 設為 `.102`；這只是設定範例，實際以 VM 網路為準。Core VM 與 RAN VM 間須能通過 AMF N2 **SCTP 38412** 及 UPF/RAN N3 **UDP 2152**。RAN VM 上的 UE 與 gNB 使用同機位址互通；gNB 控制面預設 TCP 31413、資料面預設 UDP 31414。

從 Core VM 測試 SSH 與遠端 sudo：

```bash
ssh -o BatchMode=yes user@ran-vm 'command -v go; sudo -n true'
```

遠端 `sudo -n true` 必須成功，因為範例腳本不會等待遠端密碼。腳本會以 SCP 傳送相同的 `config/env.local`，在 RAN VM 建置並啟停 gNB/UE，完成後將 RAN trace 複製回 Core VM。**雙 VM live run 尚未在本工作區實測**；交接時應先跑一個 UE 的 smoke，確認 N2/N3、路由、subscriber 及 trace。

## 5. 編輯實驗參數與加入負載

只需編輯腳本開頭 `# End editable section.` 之前。核心欄位如下：

| 參數 | 意義 |
| --- | --- |
| `RUN_ID` | 每次都要唯一；既有 run directory 不會覆蓋 |
| `AMF_MODE` | `blog` 或 `paper` |
| `AMF_WORKERS` | 正整數；比較兩個 mode 時設成相同值 |
| `UE_COUNT` | 同一 gNB 下由 `ue -n` 啟動的 UE 數；可逐步增加 |
| `RUN_HOLD_SECONDS` | UE 全部完成 PDU session 後的等待秒數，預設 5；單純等待不會自行產生測試流量 |
| `PLMN_*`、`TAC`、`SST`、`SD`、`DNN`、`UE_SUBNET` | Core、RAN、subscriber 共用的設定；比較 mode 時固定不變 |

腳本每次只執行一組設定與一個 run。做 mode 比較時，建議固定 VM、gNB、UE 數、worker 數、IP、subscriber 和流量，只切換 `AMF_MODE`，並用新的 `RUN_ID` 重複多次。多 UE 實驗要控制**同時啟動與到達速率**；僅提高總 UE 數，未必造成 worker 排隊。`blog` 在 NGAP handler 前把訊息交給 worker；`paper` 在 SCTP reader 上先處理 NGAP，到 NAS 邊界才交給 worker，因此高負載下可能出現不同的 reader 瓶頸。Core README 也記錄 `paper` 模式的 teardown race；正式數據應分開看註冊/PDU 成功率與 teardown 問題。

若需 ping、iperf 或其他業務流量，在腳本 `ran_started=1` 與 `ran_make ran-down` 之間加入命令，並把負載原始輸出另存；目前範例只產出註冊/PDU/NGAP 的 timing trace，沒有自動產生流量指標。

## 6. 輸出與判讀

成功執行後，Core 資料位於 `free5GC_UTAMF/runtime/runs/<RUN_ID>/core/`；單 VM 的 RAN 資料位於 `free-ran-ue/runtime/runs/<RUN_ID>/ran/`；雙 VM 則會複製到 Core 的 `runtime/collected/<RUN_ID>/ran/`。

| 檔案 | 用途 |
| --- | --- |
| Core `manifest.json`、RAN `manifest.json` | 模式、worker、UE 數、版本、主機與 clock 資訊、共用設定 fingerprint、clean shutdown |
| Core `amf_messages.csv` | AMF NGAP dispatch 階段的原始時間戳與 worker 欄位 |
| Core `amf_events.csv` | AMF UE 事件與內部 StartTime 探測點 |
| RAN `gnb_events.csv`、`ue_events.csv` | gNB 與 UE 的註冊/PDU 原始事件 |
| `*_trace_summary.json` | 每個 writer 的寫入/遺失列數與關閉狀態 |
| Core `per_ue_metrics.csv` | 驗證器輸出的每 UE duration，單位為 **ns** |
| Core `validation.json` | `pass`、UE 筆數、跨程序時間欄位是否有效、錯誤原因 |
| `logs/` | 各 Core NF、gNB、UE 的診斷日誌 |

`per_ue_metrics.csv` 中，`registration_ns` 是 UE 的 `reg_start` 到 `reg_done`（已送出 Registration Complete）；`pdu_ns` 是 `pdu_start` 到 `pdu_done`（UE TUN 已 ready）；`total_ns` 是 `reg_start` 到 `pdu_done`。`starttime_gnb_observed_ns` 是 gNB 從收到 Registration Request 到收到 Authentication Request 或 context setup 的同鐘觀察值；`starttime_amf_internal_ns` 是 AMF 從收到 InitialUEMessage 到開始 authentication/context setup 的同鐘值。`starttime_paper_literal_ns` 跨 gNB/AMF 程序相減，只在**單 VM、相同 boot ID 與 time namespace、CLOCK_MONOTONIC** 時填入；雙 VM 下空白是預期行為。CSV 中的 `ue_id`/`supi_hash` 是雜湊識別碼。

檢查一個單 VM run：

```bash
cd /home/ubuntu/UTokyo_research/free5GC_UTAMF
RUN_ID=example-20260923T143636Z
python3 scripts/validate_run.py \
  "runtime/runs/$RUN_ID/core" \
  "../free-ran-ue/runtime/runs/$RUN_ID/ran" \
  --output "runtime/runs/$RUN_ID/core"
cat "runtime/runs/$RUN_ID/core/validation.json"
```

雙 VM 時把第二個路徑改為 `runtime/collected/$RUN_ID/ran`。`pass=true`、`ue_rows=UE_COUNT`、`rows_dropped=0`、`clean_shutdown=true` 才表示這組 trace 完整；`paper_literal_valid=false` 本身不代表雙 VM run 失敗。

## 7. 中斷、恢復與常見失敗

查詢狀態及手動停止，**先停 RAN，再停 Core，最後清理網路**。單 VM：

```bash
cd /home/ubuntu/UTokyo_research/free-ran-ue
sudo make ran-status
sudo make ran-down
cd /home/ubuntu/UTokyo_research/free5GC_UTAMF
sudo make core-status
sudo make core-down
cd /home/ubuntu/UTokyo_research/free-ran-ue
sudo make network-down
```

沿用既有 namespace 時，`network-down` 不會刪除它們。雙 VM 則先在 **RAN VM** 執行：

```bash
cd /path/to/free-ran-ue
sudo make ran-status
sudo make ran-down
```

再到 **Core VM** 執行：

```bash
cd /path/to/free5GC_UTAMF
sudo make core-status
sudo make core-down
sudo make core-network-down
```
若仍有 lifecycle state 檔，先看 `core-status`/`ran-status` 與各 run 的 `logs/`，不要直接刪掉 state 或 run directory。使用既有 namespace 時，也不要執行 upstream 的 namespace 刪除腳本。

- `sudo -n` 失敗：本機先 `sudo -v`；雙 VM 要讓 RAN SSH 帳號能非互動執行 sudo。
- `run directory already exists`：改用新的 `RUN_ID`，保留舊資料。
- Core 起不來：檢查 MongoDB、`gtp5g`、`CORE_INTERFACE`、Core `logs/smf.log`/`logs/amf.log`；`make doctor` 可檢查常見相依。
- gNB NG Setup 失敗：核對 `N2_AMF_IP`、`RAN_N2_IP`、SCTP 38412、路由與 `logs/gnb.log`。
- UE 數未達標或 PDU 失敗：檢查 `logs/ue.log`、Core `logs/udm.log`/`logs/smf.log`、subscriber fixture、DNN/S-NSSAI/N3。
- 驗證失敗：讀 `validation.json.errors`、trace summary 與原始 CSV；不要把失敗 run 納入效能比較。

## 8. 已做過的本機確認

在這台 VM 上，單 VM 範例腳本端到端成功；`blog/1 worker` 與 `paper/2 workers` 完成單 UE trace；`blog/1 worker` 完成兩 UE trace；`blog/4 workers` 與 `paper/4 workers` 各交替跑三次並通過驗證。4-worker 的逐次資料在 `free5GC_UTAMF/runtime/comparisons/compare-w4-20260923T144301Z/runs.csv`。這些是功能與小樣本 smoke，不是正式的大規模效能結論。雙 VM只完成兩側 config render/fingerprint 一致性檢查，尚待第二台 VM 的 live smoke。
