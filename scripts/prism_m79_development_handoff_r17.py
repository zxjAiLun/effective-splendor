"""Independent finite handoff entry: dead capacity probes stop visibly."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import prism_m79_aux_capacity_r17 as capacity
from scripts import prism_m79_development_handoff_r16 as prior

HERE = Path(__file__).resolve().parent
native_ssh = prior.ssh


def ssh(port, source, **kwargs):
    if port == 2223 and 'aux-capacity-r16.json' in source:
        source = r'''
import json,time,os
from pathlib import Path
r=Path('/mnt/workspace/splendor-m79-aux-r1/execution-revisions')
receipt=r/'aux-capacity-r17.json'
if not receipt.exists():receipt=r/'aux-capacity-r16.json'
launch=r/'aux-capacity-r17/launch.json'
if not launch.exists():launch=r/'aux-capacity-r16/launch.json'
value=json.loads(receipt.read_text()) if receipt.exists() else None
qualifier={'alive':False}
if launch.exists():
 record=json.loads(launch.read_text());p=Path('/proc')/str(record['pid'])
 if p.exists():
  try:
   born=next(int(s.split()[1]) for s in Path('/proc/stat').read_text().splitlines() if s.startswith('btime '))
   created=born+int((p/'stat').read_text().split(') ',1)[1].split()[19])/os.sysconf('SC_CLK_TCK')
   qualifier={'alive':abs(created-record['create_time'])<.01,'started_at':record['observed_at']}
  except (OSError,ValueError,IndexError):pass
print(json.dumps({'capacity':value,'qualifier':qualifier,'observed_at':time.time()}))
'''
        reply = native_ssh(port, source, **kwargs)
        ready = capacity.admission(reply, reply['observed_at'])
        return dict(ready=ready, capacity=reply.get('capacity'))
    return native_ssh(port, source, **kwargs)


def main():
    prior.HERE = HERE
    prior.ssh = ssh
    return prior.main()


if __name__ == '__main__':
    main()
