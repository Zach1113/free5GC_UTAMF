#!/usr/bin/env python3
"""Small, checkout-scoped free5GC experiment lifecycle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/env'))
from configure import load_env, fingerprint

NFS=('upf','nrf','amf','smf','udr','pcf','udm','nssf','ausf','chf','nef')
STATE=ROOT/'runtime/core-state.json'

def run(args,**kwargs):
    return subprocess.run(args,cwd=ROOT,check=True,**kwargs)

def git_commit(path):
    return subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()

def alive(pid, name):
    p=Path(f'/proc/{pid}/cmdline')
    try: return str(ROOT/'bin'/name) in p.read_bytes().replace(b'\0',b' ').decode(errors='replace')
    except FileNotFoundError: return False

def tcp_ready(ip,port):
    try:
        with socket.create_connection((ip,port),timeout=.5): return True
    except OSError: return False

def wait_for(check,description,seconds=45):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if check(): return
        time.sleep(.25)
    raise RuntimeError(f'{description} did not become ready')

def config_hash():
    h=hashlib.sha256()
    for file in sorted((ROOT/'runtime/config').glob('*cfg.yaml')):
        h.update(file.name.encode()+b'\0'+file.read_bytes())
    return h.hexdigest()

def host_metadata():
    cpu=''
    for line in Path('/proc/cpuinfo').read_text().splitlines():
        if line.startswith('model name'):
            cpu=line.split(':',1)[1].strip(); break
    return {'os_release':Path('/etc/os-release').read_text().splitlines()[0],
        'kernel':os.uname().release,'cpu_model':cpu,'logical_cpu_count':os.cpu_count(),
        'cpu_affinity':sorted(os.sched_getaffinity(0)),
        'go_version':subprocess.check_output([shutil.which('go') or '/usr/local/go/bin/go','version'],text=True).strip()}

def source_state(path):
    status=subprocess.check_output(['git','-C',str(path),'status','--porcelain','--untracked-files=all'],text=True)
    return {'dirty':bool(status),'status_sha256':hashlib.sha256(status.encode()).hexdigest()}

def manifest(env,run_dir):
    return {**host_metadata(),'core_source':source_state(ROOT),'amf_source':source_state(ROOT/'NFs/amf'),'schema_version':1,'run_id':env['RUN_ID'],'role':'core','deployment_mode':env['DEPLOYMENT_MODE'],
        'start_wall_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'hostname':socket.gethostname(),
        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'time_namespace':os.readlink('/proc/self/ns/time'), 'clock_type':'CLOCK_MONOTONIC',
        'core_repo_commit':git_commit(ROOT),'amf_commit':git_commit(ROOT/'NFs/amf'),
        'free5gc_base_commit':'3b34a08e93a9b334f0f4005d3a3a9f79b66d59b9',
        'mode':env['AMF_MODE'],'requested_workers':int(env['AMF_WORKERS']),
        'effective_workers':None,'gnb_count':1,'ue_count':int(env['UE_COUNT']),
        'config_sha256':config_hash(),'shared_config_fingerprint':fingerprint(env),'clean_shutdown':False}

def doctor():
    env=load_env()
    checks={'python_yaml':False,'go':bool(shutil.which('go')),
        'mongod_reachable':tcp_ready('127.0.0.1',27017),
        'gtp5g_loaded':Path('/sys/module/gtp5g').exists(),
        'runtime_config':(ROOT/'runtime/config/amfcfg.yaml').exists()}
    try: import yaml; checks['python_yaml']=True
    except ImportError: pass
    for name in NFS: checks['binary_'+name]=(ROOT/'bin'/name).exists()
    print(json.dumps(checks,indent=2))
    return all(checks.values())

CORE_NETWORK=ROOT/'runtime/core-network-state.json'

def network_up():
    env=load_env()
    if env['DEPLOYMENT_MODE']=='single-vm': return
    if os.geteuid()!=0: raise RuntimeError('core-network-up requires root')
    if CORE_NETWORK.exists(): raise RuntimeError('Core network state already exists')
    old=Path('/proc/sys/net/ipv4/ip_forward').read_text().strip()
    nat=['iptables','-t','nat','-A','POSTROUTING','-s',env['UE_SUBNET'],'-o',env['CORE_INTERFACE'],'-j','MASQUERADE']
    Path('/proc/sys/net/ipv4/ip_forward').write_text('1\n')
    try: run(nat)
    except Exception:
        Path('/proc/sys/net/ipv4/ip_forward').write_text(old+'\n')
        raise
    CORE_NETWORK.write_text(json.dumps({'old_forward':old,'nat_delete':nat[:3]+['-D']+nat[4:]},indent=2)+'\n')

def network_down():
    if STATE.exists(): raise RuntimeError('stop Core before core-network-down')
    if not CORE_NETWORK.exists(): return
    state=json.loads(CORE_NETWORK.read_text())
    subprocess.run(state['nat_delete'],check=False)
    Path('/proc/sys/net/ipv4/ip_forward').write_text(state['old_forward']+'\n')
    CORE_NETWORK.unlink()

def up():
    if os.geteuid()!=0: raise RuntimeError('core-up requires root (sudo -E make core-up)')
    env=load_env()
    if STATE.exists(): raise RuntimeError('core-state.json exists; run core-status or core-down first')
    config=ROOT/'runtime/config/amfcfg.yaml'
    if not config.exists(): raise RuntimeError('run make configure first')
    import yaml
    amf=yaml.safe_load(config.read_text())['configuration']
    if amf['ngapSchedulerMode']!=env['AMF_MODE'] or int(amf['ngapWorkerPoolSize'])!=int(env['AMF_WORKERS']):
        raise RuntimeError('requested AMF mode/workers differ from runtime config')
    if not tcp_ready('127.0.0.1',27017): raise RuntimeError('MongoDB not reachable')
    if not Path('/sys/module/gtp5g').exists(): raise RuntimeError('gtp5g module not loaded')
    run_dir=ROOT/'runtime/runs'/env['RUN_ID']/'core'
    if run_dir.exists(): raise RuntimeError(f'run directory already exists: {run_dir}')
    logs=run_dir/'logs'; logs.mkdir(parents=True)
    m=manifest(env,run_dir)
    (run_dir/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    trace_env=os.environ.copy()
    trace_env.update(RUN_ID=env['RUN_ID'],AMF_BENCH_TRACE=str(run_dir/'amf_messages.csv'),
        AMF_BENCH_EVENT_TRACE=str(run_dir/'amf_events.csv'),AMF_MODE=env['AMF_MODE'],AMF_WORKERS=env['AMF_WORKERS'],GIN_MODE='release')
    processes={}
    try:
        for name in NFS:
            binary=ROOT/'bin'/name
            cfg=ROOT/'runtime/config'/f'{name}cfg.yaml'
            if not binary.exists() or not cfg.exists(): raise RuntimeError(f'missing {binary} or {cfg}')
            log_path=logs/f'{name}.log'
            with log_path.open('ab',buffering=0) as log:
                proc=subprocess.Popen([str(binary),'-c',str(cfg),'-l',str(log_path)],cwd=ROOT,
                    env=trace_env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            processes[name]={'pid':proc.pid,'log':str(log_path)}
            STATE.parent.mkdir(parents=True,exist_ok=True)
            STATE.write_text(json.dumps({'run_id':env['RUN_ID'],'processes':processes},indent=2)+'\n')
            if name=='nrf': wait_for(lambda: tcp_ready('127.0.0.10',8000),'NRF',60)
            if name=='amf':
                wait_for(lambda: trace_env['AMF_BENCH_TRACE'] and (run_dir/'amf_messages.csv').exists() and (run_dir/'amf_events.csv').exists(),'AMF trace files')
                pattern=f'Initializing NGAP worker pool with {env["AMF_WORKERS"]} workers (buffer size: '
                wait_for(lambda: pattern in log_path.read_text(errors='replace') and f'mode: {env["AMF_MODE"]}' in log_path.read_text(errors='replace'),'effective AMF mode/workers')
                m['effective_workers']=int(env['AMF_WORKERS'])
                m['time_namespace']=os.readlink(f'/proc/{proc.pid}/ns/time')
                (run_dir/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
            if not alive(proc.pid,name): raise RuntimeError(f'{name} exited during startup')
        wait_for(lambda: 'Received PFCP Association Setup Accepted Response' in (logs/'smf.log').read_text(errors='replace'),'SMF-UPF PFCP association',60)
        (run_dir/'status.json').write_text(json.dumps({'ready':True,'processes':processes},indent=2)+'\n')
        print(f'Core ready; data: {run_dir}')
    except Exception:
        down()
        raise

def return_run_ownership(run_dir):
    uid=os.environ.get('SUDO_UID'); gid=os.environ.get('SUDO_GID')
    if not uid or not gid: return
    for path in [run_dir,*run_dir.rglob('*')]:
        os.chown(path,int(uid),int(gid))

def down():
    if not STATE.exists(): return
    state=json.loads(STATE.read_text())
    processes=state['processes']
    # AMF drains its workers and trace while NRF and other NFs are still alive.
    if 'amf' in processes and alive(processes['amf']['pid'],'amf'):
        os.kill(processes['amf']['pid'],signal.SIGTERM)
        deadline=time.monotonic()+30
        while alive(processes['amf']['pid'],'amf') and time.monotonic()<deadline: time.sleep(.2)
    for name,item in reversed(list(processes.items())):
        if name=='amf': continue
        pid=item['pid']
        if alive(pid,name):
            try: os.kill(pid,signal.SIGTERM)
            except ProcessLookupError: pass
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if all(not alive(item['pid'],name) for name,item in processes.items()): break
        time.sleep(.2)
    survivors=[name for name,item in processes.items() if alive(item['pid'],name)]
    run_dir=ROOT/'runtime/runs'/state['run_id']/'core'
    mp=run_dir/'manifest.json'
    if mp.exists():
        m=json.loads(mp.read_text()); m['end_wall_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        m['clean_shutdown']=not survivors and (run_dir/'amf_event_trace_summary.json').exists() and (run_dir/'amf_trace_summary.json').exists()
        mp.write_text(json.dumps(m,indent=2)+'\n')
    return_run_ownership(run_dir)
    if survivors: raise RuntimeError(f'processes still alive after SIGTERM: {survivors}')
    STATE.unlink()
    print(f'Core stopped; data: {run_dir}')

def status():
    if not STATE.exists(): print('Core stopped'); return
    state=json.loads(STATE.read_text())
    result={name:{**item,'alive':alive(item['pid'],name)} for name,item in state['processes'].items()}
    print(json.dumps(result,indent=2))

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['doctor','core-up','core-down','core-status','core-network-up','core-network-down','clean-runtime'])
    action=parser.parse_args().action
    if action=='doctor': sys.exit(0 if doctor() else 1)
    if action=='core-up': up()
    elif action=='core-network-up': network_up()
    elif action=='core-network-down': network_down()
    elif action=='core-down': down()
    elif action=='core-status': status()
    elif action=='clean-runtime':
        if STATE.exists() or CORE_NETWORK.exists(): raise RuntimeError('Core or Core network is running')
        shutil.rmtree(ROOT/'runtime/config',ignore_errors=True)
if __name__=='__main__':
    try: main()
    except Exception as exc: raise SystemExit(f'experiment: {exc}')
