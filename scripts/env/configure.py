#!/usr/bin/env python3
"""Render ignored runtime config from env.local without changing tracked YAML."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import sys

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: python3 -m pip install pyyaml")

ROOT = Path(__file__).resolve().parents[2]
SHARED = ("DEPLOYMENT_MODE", "CORE_VM_IP", "RAN_VM_IP", "N2_AMF_IP", "N3_UPF_IP", "RAN_N2_IP", "RAN_N3_IP", "RAN_CONTROL_IP", "RAN_DATA_IP", "UE_NS_IP", "PLMN_MCC", "PLMN_MNC", "TAC", "DNN", "SST", "SD", "UE_SUBNET", "GNB_ID")

class UniqueLoader(yaml.SafeLoader):
    pass

def unique_map(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_map)

def load_env():
    path = ROOT / "config/env.local"
    if not path.exists():
        raise ValueError(f"create {path} from config/env.example")
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid env line: {line}")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key in result:
            raise ValueError(f"duplicate env key {key}")
        if not value or "<" in value or ">" in value:
            raise ValueError(f"empty or placeholder value for {key}")
        result[key] = value
    for key in SHARED + ("AMF_MODE", "AMF_WORKERS", "RUN_ID", "CORE_INTERFACE", "UE_COUNT"):
        if not result.get(key):
            raise ValueError(f"missing {key}")
    if result["DEPLOYMENT_MODE"] not in ("single-vm", "dual-vm"):
        raise ValueError("DEPLOYMENT_MODE must be single-vm or dual-vm")
    if result["AMF_MODE"] not in ("blog", "paper"):
        raise ValueError("AMF_MODE must be blog or paper")
    for key in ("AMF_WORKERS", "UE_COUNT"):
        if not result[key].isdigit() or int(result[key]) < 1:
            raise ValueError(f"{key} must be positive")
    for key in ("CORE_VM_IP", "RAN_VM_IP", "N2_AMF_IP", "N3_UPF_IP", "RAN_N2_IP", "RAN_N3_IP", "RAN_CONTROL_IP", "RAN_DATA_IP", "UE_NS_IP"):
        ipaddress.ip_address(result[key])
    ipaddress.ip_network(result["UE_SUBNET"])
    if result["DEPLOYMENT_MODE"] == "single-vm":
        if result["CORE_VM_IP"] != result["N2_AMF_IP"] or result["CORE_VM_IP"] != result["N3_UPF_IP"]:
            raise ValueError("single-vm Core N2/N3 must bind the host veth IP")
        if result["RAN_VM_IP"] != result["RAN_N2_IP"] or result["RAN_N2_IP"] != result["RAN_N3_IP"]:
            raise ValueError("single-vm RAN N2/N3 must bind the RAN veth IP")
        if result["RAN_CONTROL_IP"] != result["RAN_DATA_IP"]:
            raise ValueError("single-vm RAN control and data addresses must share the gNB veth IP")
        if ipaddress.ip_address(result["UE_NS_IP"]) not in ipaddress.ip_network(result["RAN_CONTROL_IP"] + "/24", strict=False):
            raise ValueError("UE_NS_IP must be in the gNB namespace /24")

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", result["RUN_ID"]):
        raise ValueError("RUN_ID may contain only letters, digits, dot, underscore, hyphen")
    return result

def fingerprint(env):
    payload = {key: env[key] for key in SHARED}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def render():
    env = load_env()
    out = ROOT / "runtime/config"
    out.mkdir(parents=True, exist_ok=True)
    for src in (ROOT / "config").glob("*cfg.yaml"):
        doc = yaml.load(src.read_text(), Loader=UniqueLoader)
        if src.name == "amfcfg.yaml":
            c = doc["configuration"]
            c["ngapIpList"] = [env["N2_AMF_IP"]]
            c["ngapSchedulerMode"] = env["AMF_MODE"]
            c["ngapWorkerPoolSize"] = int(env["AMF_WORKERS"])
            c["servedGuamiList"][0]["plmnId"].update(mcc=env["PLMN_MCC"], mnc=env["PLMN_MNC"])
            c["supportTaiList"][0]["plmnId"].update(mcc=env["PLMN_MCC"], mnc=env["PLMN_MNC"])
            c["supportTaiList"][0]["tac"] = env["TAC"]
            c["plmnSupportList"][0]["plmnId"].update(mcc=env["PLMN_MCC"], mnc=env["PLMN_MNC"])
            c["plmnSupportList"][0]["snssaiList"][0] = {"sst": int(env["SST"]), "sd": env["SD"]}
            c["supportDnnList"] = [env["DNN"]]
        elif src.name == "smfcfg.yaml":
            cfg = doc["configuration"]
            cfg["plmnList"][0].update(mcc=env["PLMN_MCC"], mnc=env["PLMN_MNC"])
            for index, item in enumerate(cfg["snssaiInfos"]):
                item["sNssai"]["sd"] = env["SD"] if index == 0 else str(item["sNssai"]["sd"]).zfill(6)
                if index == 0:
                    item["sNssai"]["sst"] = int(env["SST"])
                    item["dnnInfos"][0]["dnn"] = env["DNN"]
            for upf in cfg["userplaneInformation"]["upNodes"].values():
                for index, item in enumerate(upf.get("sNssaiUpfInfos", [])):
                    item["sNssai"]["sd"] = env["SD"] if index == 0 else str(item["sNssai"]["sd"]).zfill(6)
                    if index == 0:
                        item["sNssai"]["sst"] = int(env["SST"])
                        item["dnnUpfInfoList"][0]["dnn"] = env["DNN"]
                        item["dnnUpfInfoList"][0]["pools"][0]["cidr"] = env["UE_SUBNET"]
                for interface in upf.get("interfaces", []):
                    if interface.get("interfaceType") == "N3":
                        interface["endpoints"] = [env["N3_UPF_IP"]]
        elif src.name == "upfcfg.yaml":
            for interface in doc["gtpu"].get("ifList", []):
                if interface.get("type") == "N3":
                    interface["addr"] = env["N3_UPF_IP"]
            doc["dnnList"][0].update(dnn=env["DNN"], cidr=env["UE_SUBNET"])
        (out / src.name).write_text(yaml.safe_dump(doc, sort_keys=False))
    (out / "experiment.json").write_text(json.dumps({"shared_config_fingerprint": fingerprint(env), "env": {k:v for k,v in env.items() if k not in ("AUTH_KEY", "OPC_KEY")}}, indent=2) + "\n")
    print(f"configured {out}; shared fingerprint {fingerprint(env)}")

if __name__ == "__main__":
    try:
        render()
    except (KeyError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"configure: {exc}")
