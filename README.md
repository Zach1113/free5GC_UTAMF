# free5GC UT-AMF Research Environment

This repository provides a 5G Core research environment based on free5GC `v4.2.3`. It compares two approaches to parallel AMF message processing:

- the free5GC NGAP worker pool (`blog`); and
- a paper-inspired AMF that dispatches work at the NAS boundary (`paper`).

The research examines how the dispatch key and hand-off location affect AMF processing during UE registration and PDU Session establishment. This repository contains the complete Core source tree. The modified AMF is maintained as a separate Git submodule so that its version can be pinned and updated independently.

The `paper` mode is based on the NAS-boundary hand-off described by Nha and Nakao in *Multithreading-Based AMF Optimization for Pre-Slice Congestion Control in 5G Core Networks* (IEEE GC Wkshps 2025). This implementation studies its dispatch boundary and subscriber-based key. The priority mechanism described in the paper is outside the current implementation scope.

## Research design

After receiving an NGAP message from the gNB, the AMF can hand the work to a worker at different points:

```text
gNB
 │
 │ NGAP message
 ▼
SCTP reader
 ├─ blog ─────────► select worker by NGAP UE ID ─► NGAP handler ─► NAS
 ├─ paper-early ──► select worker by IMSI ───────► NGAP handler ─► NAS
 └─ paper ────────► NGAP handler ───────────────► select worker by IMSI ─► NAS
```

The three modes have the following roles:

| Mode | Dispatch key | Worker hand-off point | Purpose |
|---|---|---|---|
| `blog` | NGAP UE ID | Before the NGAP handler | Formal baseline using the free5GC NGAP worker-pool design |
| `paper` | IMSI | At the NAS boundary inside the NGAP handler | Formal comparison using the paper-inspired hand-off point |
| `paper-early` | IMSI | Before the NGAP handler | Diagnostic mode that separates the dispatch-key and hand-off-point variables |

The formal comparison uses only `blog` and `paper`. `paper-early` is a project-specific diagnostic mode and must not be presented as the paper's formal design.

### Comparison cases

The scheduler mode and worker count should be controlled independently. For example:

```text
blog  + 1 worker
blog  + 4 workers
paper + 1 worker
paper + 4 workers
```

Before each case, verify that the AMF startup log reports the requested mode and worker count. Then run the same UE registration, PDU Session establishment, and user-plane connectivity checks. The current mode-switching script does not perform load generation, repetitions, timing, statistical analysis, or plotting.

### Known limitations

- In `paper` mode, work is handed off at the NAS boundary. The beginning of the NGAP handler still runs on the SCTP reader goroutine, so its serial section differs from `blog`.
- `paper` mode has a known teardown race. Deregistration and teardown performance are outside the current research scope.
- `paper-early` obtains the IMSI before the NGAP handler. It exists to distinguish the effect of changing the dispatch key from the effect of changing the hand-off point.
- Changing the mode requires an AMF restart. A running AMF does not reload these settings dynamically.

## Source layout

```text
.
├── NFs/
│   ├── amf/                 # Modified AMF Git submodule
│   └── ...                  # Other free5GC v4.2.3 NF sources
├── config/amfcfg.yaml       # Tracked base config; never edited by the switch script
├── scripts/
│   └── switch-amf-mode.sh
└── runtime/config/          # Generated runtime config; ignored by Git
```

Pinned source versions:

- free5GC: `v4.2.3`, commit `3b34a08e93a9b334f0f4005d3a3a9f79b66d59b9`
- Modified AMF: branch `feat/submodule`, currently pinned to commit `d1c749254442beeeb405234e2a50ba9afb460e41`

Clone the repository together with the AMF submodule:

```bash
git clone --recurse-submodules https://github.com/Zach1113/free5GC_UTAMF.git
cd free5GC_UTAMF
```

If the repository has already been cloned but the AMF directory is empty, initialize it with:

```bash
git submodule update --init --recursive
```

## Switching the AMF mode

Usage:

```text
scripts/switch-amf-mode.sh MODE [WORKERS]
```

`MODE` must be `blog`, `paper`, or `paper-early`. `WORKERS` is an optional positive integer.

### Formal comparison examples

```bash
# free5GC NGAP dispatch with one worker
scripts/switch-amf-mode.sh blog 1

# free5GC NGAP dispatch with four workers
scripts/switch-amf-mode.sh blog 4

# NAS-boundary dispatch with one worker
scripts/switch-amf-mode.sh paper 1

# NAS-boundary dispatch with four workers
scripts/switch-amf-mode.sh paper 4
```

Diagnostic mode:

```bash
scripts/switch-amf-mode.sh paper-early 4
```

When `WORKERS` is omitted, the script preserves the value in the existing runtime config. On the first run, it uses the value from the tracked base config:

```bash
scripts/switch-amf-mode.sh paper
```

The script does not accept an explicit value of `0`, which prevents a formal experiment from accidentally using automatic worker detection. A base-config value of `ngapWorkerPoolSize: 0` tells the AMF to use `runtime.NumCPU()`; formal comparisons should always specify a positive worker count.

### Generated configuration

The script does not modify the tracked `config/amfcfg.yaml`. It creates or updates:

```text
runtime/config/amfcfg.yaml
```

The `runtime/` directory is ignored by Git, so switching modes does not dirty the working tree. Repeating the same command produces the same configuration.

Inspect the generated values with:

```bash
grep -E 'ngapSchedulerMode|ngapWorkerPoolSize' runtime/config/amfcfg.yaml
```

### Starting the AMF with the generated config

Build the AMF:

```bash
make amf
```

Start it with the generated configuration:

```bash
./bin/amf --config runtime/config/amfcfg.yaml
```

The startup log should contain a line similar to:

```text
Initializing NGAP worker pool with 4 workers (buffer size: 4096, mode: paper)
```

If the reported mode or worker count differs from the requested value, stop that validation run, invoke the switching script again, and restart the AMF.

## Upstream sources and licenses

The Core source is based on [free5GC](https://github.com/free5gc/free5gc). The modified AMF comes from [amf-ngap-dispatch-bench](https://github.com/DBGR18/amf-ngap-dispatch-bench) and is pinned through the `NFs/amf` submodule. License and notice files from each upstream component remain in their respective source trees. Repository-level licensing information is available in `LICENSE` and `THIRD-PARTY-NOTICES.txt`.
