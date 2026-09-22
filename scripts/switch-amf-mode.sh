#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/switch-amf-mode.sh MODE [WORKERS]

Render runtime/config/amfcfg.yaml with a different NGAP scheduler mode.

MODE:
  blog         free5GC NGAP worker-pool dispatch
  paper        NAS-boundary dispatch used for the formal comparison
  paper-early  diagnostic mode; not a formal experiment mode

WORKERS is optional. When provided, it must be a positive integer. When it is
omitted, the current rendered value is preserved (or the tracked default is
used on the first run).

Examples:
  scripts/switch-amf-mode.sh blog 1
  scripts/switch-amf-mode.sh paper 4
  scripts/switch-amf-mode.sh paper-early
EOF
}

if (( $# < 1 || $# > 2 )); then
    usage >&2
    exit 2
fi

mode=$1
workers=${2:-}

case "$mode" in
    blog|paper|paper-early) ;;
    *)
        printf 'error: unsupported AMF mode %q (expected blog, paper, or paper-early)\n' "$mode" >&2
        exit 2
        ;;
esac

if [[ -n "$workers" && ! "$workers" =~ ^[1-9][0-9]*$ ]]; then
    printf 'error: WORKERS must be a positive integer, got %q\n' "$workers" >&2
    exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
tracked_config="$repo_root/config/amfcfg.yaml"
runtime_dir="$repo_root/runtime/config"
runtime_config="$runtime_dir/amfcfg.yaml"

if [[ ! -f "$tracked_config" ]]; then
    printf 'error: tracked AMF config not found: %s\n' "$tracked_config" >&2
    exit 1
fi

mkdir -p -- "$runtime_dir"

input_config=$tracked_config
if [[ -f "$runtime_config" ]]; then
    input_config=$runtime_config
fi

tmp_config=$(mktemp "$runtime_dir/.amfcfg.yaml.XXXXXX")
trap 'rm -f -- "$tmp_config"' EXIT

awk -v requested_mode="$mode" -v requested_workers="$workers" '
    /^[[:space:]]*ngapSchedulerMode[[:space:]]*:/ {
        mode_count++
        match($0, /^[[:space:]]*/)
        indent = substr($0, RSTART, RLENGTH)
        print indent "ngapSchedulerMode: " requested_mode " # blog | paper-early | paper"
        next
    }
    /^[[:space:]]*ngapWorkerPoolSize[[:space:]]*:/ {
        worker_count++
        if (requested_workers != "") {
            match($0, /^[[:space:]]*/)
            indent = substr($0, RSTART, RLENGTH)
            print indent "ngapWorkerPoolSize: " requested_workers " # positive integer; 0 in the tracked config means auto"
        } else {
            print
        }
        next
    }
    { print }
    END {
        if (mode_count != 1) {
            printf "error: expected exactly one ngapSchedulerMode key, found %d\n", mode_count > "/dev/stderr"
            exit 1
        }
        if (worker_count != 1) {
            printf "error: expected exactly one ngapWorkerPoolSize key, found %d\n", worker_count > "/dev/stderr"
            exit 1
        }
    }
' "$input_config" > "$tmp_config"

chmod --reference="$input_config" "$tmp_config"
mv -f -- "$tmp_config" "$runtime_config"
trap - EXIT

effective_workers=$(awk '
    /^[[:space:]]*ngapWorkerPoolSize[[:space:]]*:/ {
        sub(/^[[:space:]]*ngapWorkerPoolSize[[:space:]]*:[[:space:]]*/, "")
        sub(/[[:space:]]*#.*/, "")
        print
        exit
    }
' "$runtime_config")

printf 'AMF mode:    %s\n' "$mode"
printf 'AMF workers: %s\n' "$effective_workers"
printf 'Config:      %s\n' "$runtime_config"
printf 'Restart the AMF with --config %s for the change to take effect.\n' "$runtime_config"
