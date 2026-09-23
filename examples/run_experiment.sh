#!/usr/bin/env bash
# Edit this section for each run. Full guide: docs/EXPERIMENT_USAGE.md.
# The script provisions development subscribers.
set -euo pipefail
DEPLOYMENT_MODE=single-vm       # single-vm or dual-vm
RUN_ID="example-$(date -u +%Y%m%dT%H%M%SZ)"
AMF_MODE=blog                   # blog or paper
AMF_WORKERS=1
UE_COUNT=1                      # May be increased for experiments.
RUN_HOLD_SECONDS=5             # Time available for any added workload after UE setup.
CORE_VM_IP=10.0.1.1
RAN_VM_IP=10.0.1.2
CORE_INTERFACE=ens33
N2_AMF_IP=10.0.1.1
N3_UPF_IP=10.0.1.1
RAN_N2_IP=10.0.1.2
RAN_N3_IP=10.0.1.2
RAN_CONTROL_IP=10.0.2.1
RAN_DATA_IP=10.0.2.1
UE_NS_IP=10.0.2.2
EXISTING_RAN_NS=free-ran-ns    # Clear both names to create checkout-owned namespaces.
EXISTING_UE_NS=free-ue-ns
RAN_SSH=''                      # For dual-vm: user@ran-vm
RAN_REPO=''                     # For dual-vm: absolute path on RAN VM
PLMN_MCC=208
PLMN_MNC=93
TAC=000001
DNN=internet
SST=1
SD=010203
UE_SUBNET=10.60.0.0/16
GNB_ID=000314
# End editable section.

CORE_REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ "$DEPLOYMENT_MODE" == single-vm ]]; then
    RAN_REPO=${RAN_REPO:-"$CORE_REPO/../free-ran-ue"}
else
    [[ -n "$RAN_SSH" && "$RAN_REPO" == /* ]] || { echo 'Set RAN_SSH and absolute RAN_REPO for dual-vm' >&2; exit 2; }
fi
[[ "$RUN_ID" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'Invalid RUN_ID' >&2; exit 2; }

cat > "$CORE_REPO/config/env.local" <<ENV
DEPLOYMENT_MODE=$DEPLOYMENT_MODE
RUN_ID=$RUN_ID
CORE_VM_IP=$CORE_VM_IP
RAN_VM_IP=$RAN_VM_IP
CORE_INTERFACE=$CORE_INTERFACE
N2_AMF_IP=$N2_AMF_IP
N3_UPF_IP=$N3_UPF_IP
RAN_N2_IP=$RAN_N2_IP
RAN_N3_IP=$RAN_N3_IP
RAN_CONTROL_IP=$RAN_CONTROL_IP
RAN_DATA_IP=$RAN_DATA_IP
UE_NS_IP=$UE_NS_IP
PLMN_MCC=$PLMN_MCC
PLMN_MNC=$PLMN_MNC
TAC=$TAC
DNN=$DNN
SST=$SST
SD=$SD
UE_SUBNET=$UE_SUBNET
GNB_ID=$GNB_ID
AMF_MODE=$AMF_MODE
AMF_WORKERS=$AMF_WORKERS
UE_COUNT=$UE_COUNT
ENV
if [[ -n "$EXISTING_RAN_NS" || -n "$EXISTING_UE_NS" ]]; then
    [[ "$DEPLOYMENT_MODE" == single-vm && -n "$EXISTING_RAN_NS" && -n "$EXISTING_UE_NS" ]] || { echo 'Set both existing namespaces only for single-vm' >&2; exit 2; }
    printf 'EXISTING_RAN_NS=%s\nEXISTING_UE_NS=%s\n' "$EXISTING_RAN_NS" "$EXISTING_UE_NS" >> "$CORE_REPO/config/env.local"
fi
[[ "$RUN_HOLD_SECONDS" =~ ^[0-9]+$ ]] || { echo 'RUN_HOLD_SECONDS must be a nonnegative integer' >&2; exit 2; }

ran_make() {
    if [[ "$DEPLOYMENT_MODE" == single-vm ]]; then
        (cd "$RAN_REPO" && sudo -n make "$@")
    else
        ssh -o BatchMode=yes "$RAN_SSH" "cd '$RAN_REPO' && sudo -n make $*"
    fi
}
ran_build() {
    if [[ "$DEPLOYMENT_MODE" == single-vm ]]; then
        (cd "$RAN_REPO" && make configure build)
    else
        ssh -o BatchMode=yes "$RAN_SSH" "cd '$RAN_REPO' && make configure build"
    fi
}

if [[ "$DEPLOYMENT_MODE" == single-vm ]]; then
    cp "$CORE_REPO/config/env.local" "$RAN_REPO/config/env.local"
else
    scp -q "$CORE_REPO/config/env.local" "$RAN_SSH:$RAN_REPO/config/env.local"
fi

sudo -v

core_started=0
ran_started=0
network_started=0
core_network_started=0
cleanup() {
    if (( ran_started )); then ran_make ran-down || true; fi
    if (( core_started )); then (cd "$CORE_REPO" && sudo -n make core-down) || true; fi
    if (( network_started )); then ran_make network-down || true; fi
    if (( core_network_started )); then (cd "$CORE_REPO" && sudo -n make core-network-down) || true; fi
}
trap cleanup EXIT

(cd "$CORE_REPO" && make configure build-core && make -B amf && make test-amf)
ran_build
if [[ "$DEPLOYMENT_MODE" == single-vm ]]; then
    UE_CONFIG="$RAN_REPO/runtime/config/ue.yaml"
else
    UE_CONFIG="$CORE_REPO/runtime/config/ue_fixture.yaml"
    scp -q "$RAN_SSH:$RAN_REPO/runtime/config/ue.yaml" "$UE_CONFIG"
    chmod 600 "$UE_CONFIG"
fi
(cd "$CORE_REPO" && python3 scripts/provision_subscribers.py --ue-config "$UE_CONFIG")
if [[ "$DEPLOYMENT_MODE" == single-vm ]]; then
    ran_make network-up
    network_started=1
else
    (cd "$CORE_REPO" && sudo -n make core-network-up)
    core_network_started=1
fi
(cd "$CORE_REPO" && sudo -n make core-up)
core_started=1
ran_make ran-up
ran_started=1
sleep "$RUN_HOLD_SECONDS"

ran_make ran-down
ran_started=0
(cd "$CORE_REPO" && sudo -n make core-down)
core_started=0
if (( network_started )); then ran_make network-down; network_started=0; fi
if (( core_network_started )); then (cd "$CORE_REPO" && sudo -n make core-network-down); core_network_started=0; fi

CORE_DATA="$CORE_REPO/runtime/runs/$RUN_ID/core"
if [[ "$DEPLOYMENT_MODE" == single-vm ]]; then
    RAN_DATA="$RAN_REPO/runtime/runs/$RUN_ID/ran"
else
    RAN_DATA="$CORE_REPO/runtime/collected/$RUN_ID/ran"
    mkdir -p -- "$(dirname -- "$RAN_DATA")"
    scp -qr "$RAN_SSH:$RAN_REPO/runtime/runs/$RUN_ID/ran" "$RAN_DATA"
fi
python3 "$CORE_REPO/scripts/validate_run.py" "$CORE_DATA" "$RAN_DATA" --output "$CORE_DATA"
printf 'Experiment data: %s\n' "$CORE_DATA"
printf 'RAN raw data: %s\n' "$RAN_DATA"
