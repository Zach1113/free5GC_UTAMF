#!/usr/bin/env python3
"""Development-only idempotent subscriber fixture for free-ran-ue UEs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/env'))
from configure import load_env

def provision(config_path):
    env=load_env()
    cfg=yaml.safe_load(config_path.read_text())['ue']
    count=int(env['UE_COUNT'])
    mcc,mnc=env['PLMN_MCC'],env['PLMN_MNC']
    msin=cfg['msin']; base=int(msin)
    auth=cfg['authenticationSubscription']
    snssai={'sst':int(env['SST']),'sd':env['SD']}
    key=f'{int(env["SST"]):02d}{env["SD"]}'
    docs=[]
    for i in range(count):
        supi=f'imsi-{mcc}{mnc}{base+i:0{len(msin)}d}'
        common={'ueId':supi,'servingPlmnId':mcc+mnc}
        docs.append({
          'auth':{'ueId':supi,'authenticationMethod':'5G_AKA',
            'encPermanentKey':auth['encPermanentKey'],'encOpcKey':auth['encOpcKey'],
            'authenticationManagementField':auth['authenticationManagementField'],
            'sequenceNumber':{'sqn':auth['sequenceNumber']}},
          'am':{**common,'subscribedUeAmbr':{'uplink':'1 Gbps','downlink':'2 Gbps'},
            'nssai':{'defaultSingleNssais':[snssai],'singleNssais':[snssai]}},
          'sm':{**common,'singleNssai':snssai,'dnnConfigurations':{env['DNN']:{
            'pduSessionTypes':{'defaultSessionType':'IPV4','allowedSessionTypes':['IPV4']},
            'sscModes':{'defaultSscMode':'SSC_MODE_1','allowedSscModes':['SSC_MODE_1']},
            '5gQosProfile':{'5qi':9,'arp':{'priorityLevel':8},'priorityLevel':8},
            'sessionAmbr':{'uplink':'1000 Mbps','downlink':'1000 Mbps'}}}},
          'selection':{**common,'subscribedSnssaiInfos':{key:{'dnnInfos':[{'dnn':env['DNN']}]}}},
          'am_policy':{'ueId':supi,'subscCats':['free5gc']},
          'sm_policy':{'ueId':supi,'smPolicySnssaiData':{key:{'snssai':snssai,'smPolicyDnnData':{env['DNN']:{'dnn':env['DNN']}}}}}
        })
    payload=json.dumps(docs)
    js='''const docs=JSON.parse(%s);
const names={auth:'subscriptionData.authenticationData.authenticationSubscription',am:'subscriptionData.provisionedData.amData',sm:'subscriptionData.provisionedData.smData',selection:'subscriptionData.provisionedData.smfSelectionSubscriptionData',am_policy:'policyData.ues.amData',sm_policy:'policyData.ues.smData'};
const tenant=db.getCollection('tenantData').findOne({});
for(const item of docs){for(const [kind,name] of Object.entries(names)){
 const data=item[kind]; if(tenant && tenant.tenantId) data.tenantId=tenant.tenantId;
 db.getCollection(name).updateOne({ueId:data.ueId},{$setOnInsert:data},{upsert:true});
}}
for(const item of docs){
 const auth=db.getCollection(names.auth);
 auth.updateOne({ueId:item.auth.ueId,sequenceNumber:item.auth.sequenceNumber.sqn},{$set:{sequenceNumber:item.auth.sequenceNumber}});
}
for(const item of docs){if(!db.getCollection(names.auth).findOne({ueId:item.auth.ueId}) || !db.getCollection(names.am).findOne({ueId:item.auth.ueId})) throw new Error('provision verification failed');}
print(JSON.stringify({provisioned:docs.length}));
''' % json.dumps(payload)
    result=subprocess.run(['mongosh','--quiet','free5gc','--file','/dev/stdin'],input=js,text=True,capture_output=True)
    if result.returncode: raise RuntimeError(f'mongosh failed: {result.stderr[-500:]}')
    print(result.stdout.strip())

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Development-only fixture; never run against production MongoDB')
    p.add_argument('--ue-config',type=Path,required=True)
    a=p.parse_args()
    try: provision(a.ue_config)
    except Exception as exc: raise SystemExit(f'provision: {exc}')
