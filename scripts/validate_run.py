#!/usr/bin/env python3
"""Validate one run and export per-UE raw durations, without statistical summaries."""
import argparse
import csv
import json
from pathlib import Path
import sys

FIELDS=('run_id','ue_id','registration_ns','pdu_ns','total_ns','gnb_pre_amf_ns','starttime_gnb_observed_ns','starttime_amf_internal_ns','starttime_paper_literal_ns','paper_literal_valid')

def rows(path):
    if not path.exists(): raise ValueError(f'missing {path}')
    with path.open(newline='') as f:
        values=list(csv.DictReader(f))
    if not values: raise ValueError(f'empty {path}')
    return values

def number(row):
    v=row.get('clock_monotonic_ns','')
    if not v or int(v)<=0: raise ValueError(f'invalid monotonic timestamp: {row}')
    return int(v)

def event(group,name):
    matches=[r for r in group if r['event']==name]
    if not matches: raise ValueError(f'missing {name}')
    return min(matches,key=number)

def check_summary(path):
    data=json.loads(path.read_text())
    if data.get('rows_dropped',0)!=0 or data.get('error') or not data.get('clean_shutdown'):
        raise ValueError(f'trace integrity failed: {path}')

def validate(core,ran,output):
    errors=[]
    cm=json.loads((core/'manifest.json').read_text()); rm=json.loads((ran/'manifest.json').read_text())
    for key in ('run_id','shared_config_fingerprint','deployment_mode'):
        if cm.get(key)!=rm.get(key): errors.append(f'manifest mismatch: {key}')
    if cm.get('mode')!=rm.get('mode') or cm.get('requested_workers')!=cm.get('effective_workers'):
        errors.append('AMF mode/workers mismatch')
    if not cm.get('clean_shutdown') or not rm.get('clean_shutdown'): errors.append('run did not shut down cleanly')
    for path in (core/'amf_trace_summary.json',core/'amf_event_trace_summary.json',ran/'ue_trace_summary.json',ran/'gnb_trace_summary.json'):
        try: check_summary(path)
        except (OSError,ValueError) as exc: errors.append(str(exc))
    ue=rows(ran/'ue_events.csv'); gnb=rows(ran/'gnb_events.csv'); amf=rows(core/'amf_events.csv')
    rows(core/'amf_messages.csv')
    same_clock=(cm.get('deployment_mode')==rm.get('deployment_mode')=='single-vm' and bool(cm.get('boot_id')) and cm.get('boot_id')==rm.get('boot_id') and cm.get('time_namespace')==rm.get('time_namespace') and cm.get('clock_type')==rm.get('clock_type')=='CLOCK_MONOTONIC')
    output_rows=[]
    for uid in sorted({r['ue_id'] for r in ue}):
        try:
            group=[r for r in ue if r['ue_id']==uid]
            reg_start=event(group,'reg_start'); reg_done=event(group,'reg_done')
            pdu_start=event(group,'pdu_start'); pdu_done=event(group,'pdu_done')
            if not number(reg_start)<=number(reg_done)<=number(pdu_start)<=number(pdu_done): raise ValueError('UE event ordering invalid')
            gnb_initial=event([r for r in gnb if r['ue_id']==uid],'initial_ue_message_sent')
            ran_ue_id=gnb_initial['ran_ue_ngap_id']
            gnb_group=[r for r in gnb if r['ran_ue_ngap_id']==ran_ue_id]
            recv=event(gnb_group,'registration_request_received')
            response=event(gnb_group,'authentication_or_context_setup_received')
            amf_group=[r for r in amf if r['ran_ue_ngap_id']==ran_ue_id]
            amf_recv=event(amf_group,'initial_ue_message_received')
            actions=[r for r in amf_group if r['event'] in ('authentication_initiated','context_setup_initiated')]
            if not actions: raise ValueError('AMF action missing')
            action=min(actions,key=number)
            metrics={'run_id':cm['run_id'],'ue_id':uid,
                'registration_ns':number(reg_done)-number(reg_start),
                'pdu_ns':number(pdu_done)-number(pdu_start),
                'total_ns':number(pdu_done)-number(reg_start),
                'gnb_pre_amf_ns':number(gnb_initial)-number(recv),
                'starttime_gnb_observed_ns':number(response)-number(recv),
                'starttime_amf_internal_ns':number(action)-number(amf_recv),
                'starttime_paper_literal_ns':number(action)-number(recv) if same_clock else '',
                'paper_literal_valid':same_clock}
            for key,value in metrics.items():
                if key.endswith('_ns') and value!='' and value<0: raise ValueError(f'negative {key}')
            output_rows.append(metrics)
        except (ValueError,KeyError) as exc: errors.append(f'UE {uid}: {exc}')
    if len(output_rows)!=int(rm.get('ue_count',0)): errors.append(f'expected {rm.get("ue_count")} successful UEs, got {len(output_rows)}')
    output.mkdir(parents=True,exist_ok=True)
    with (output/'per_ue_metrics.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS); writer.writeheader(); writer.writerows(output_rows)
    result={'pass':not errors,'run_id':cm.get('run_id'),'ue_rows':len(output_rows),'paper_literal_valid':same_clock,'errors':errors}
    (output/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return not errors

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('core_run_dir',type=Path); p.add_argument('ran_run_dir',type=Path); p.add_argument('--output',type=Path)
    a=p.parse_args()
    try: sys.exit(0 if validate(a.core_run_dir,a.ran_run_dir,a.output or a.core_run_dir) else 1)
    except (OSError,ValueError,KeyError) as exc: raise SystemExit(f'FAIL: {exc}')
