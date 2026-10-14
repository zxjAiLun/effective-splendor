"""Stream a sealed M79 tree as a deterministic tar.gz; no model calls or deletion."""
import argparse,gzip,hashlib,json,os,psutil,sys,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest

def main():
    from scripts.prism_dsw_ppo_process import same_process
    state=read(ROOT/'pipeline/status.json')
    if same_process(state['pid'],state['create_time']):raise ValueError('history requires stopped scientific writer')
    if not (ROOT/'pipeline/completion.json').exists() and state['state']!='STOPPED_REQUIRES_RECONCILIATION':raise ValueError('unsealed execution')
    budget=read(ROOT/'round-budget.json');deadline=budget['deadline']
    journal=read(ROOT/'pipeline/resources.json')
    cpu_limit=min(30000-sum(r.get('cpu_seconds',0) for r in journal if r['category']=='audit_transfer_control'),300000-sum(r.get('cpu_seconds',0) for r in journal))
    if cpu_limit<=0:raise ValueError('history remaining CPU budget exhausted')
    if time.time()>=deadline:raise ValueError('original round deadline exhausted')
    # These are public recovery-key backups, not research inputs. Preserve them on node.
    excluded=('recovery-hooks/','history-delivery/')
    members={}
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT).as_posix()
        if path.is_file() and not path.is_symlink() and not rel.startswith(excluded) and not path.name.endswith(('.lock','.tmp')) and 'authorized-before-' not in path.name:
            members[rel]=dict(bytes=path.stat().st_size,sha256=digest(path))
        if time.time()>=deadline or time.process_time()>=cpu_limit:raise ValueError('history source scan budget')
    total=sum(v['bytes'] for v in members.values())
    if total>40802189312:raise ValueError('M79 source storage cap exceeded')
    dest=ROOT/'history-delivery';dest.mkdir(exist_ok=True)
    manifest=dict(format='prism-m79-history-source-v1',execution_sha256=digest(ROOT/'execution.json'),execution_revision_sha256=digest(ROOT/'execution-revisions/r6.json'),members=members,bytes=total,files=len(members),observed_at=time.time(),new_games=0,source_deleted=False)
    path=dest/'source-manifest.json'
    if path.exists() and read(path)['members']!=members:raise ValueError('frozen history source differs')
    if not path.exists():write(path,manifest)
    archive_hash=hashlib.sha256();archive_bytes=[0];started=time.time();process=psutil.Process()
    class Sink:
        def write(self,data):
            if time.time()>=deadline or time.process_time()>=cpu_limit or process.memory_info().rss>1024**3:raise ValueError('history finite resource limit')
            archive_hash.update(data);archive_bytes[0]+=len(data)
            return sys.stdout.buffer.write(data)
        def flush(self):sys.stdout.buffer.flush()
    class CheckedReader:
        def __init__(self,path,expected):self.file=path.open('rb');self.hash=hashlib.sha256();self.expected=expected
        def read(self,n=-1):
            chunk=self.file.read(n);self.hash.update(chunk);return chunk
        def close(self):
            self.file.close()
            if self.hash.hexdigest()!=self.expected:raise ValueError('history member changed during stream')
    with gzip.GzipFile(filename='',fileobj=Sink(),mode='wb',compresslevel=1,mtime=0) as compressed, tarfile.open(fileobj=compressed,mode='w|') as archive:
        for rel,item in members.items():
            source=ROOT/rel;info=archive.gettarinfo(str(source),arcname=rel);info.mtime=0;info.uid=info.gid=0;info.uname=info.gname=''
            reader=CheckedReader(source,item['sha256'])
            try:archive.addfile(info,reader)
            finally:reader.close()
        data=path.read_bytes();import io
        info=tarfile.TarInfo('history-source-manifest.json');info.size=len(data);info.mtime=0;archive.addfile(info,io.BytesIO(data))
    sys.stdout.buffer.flush()
    write(dest/'stream-receipt.json',dict(status='PASS_STREAMED_SOURCE',archive_sha256=archive_hash.hexdigest(),archive_bytes=archive_bytes[0],source_manifest_sha256=digest(path),cpu_seconds=time.process_time(),elapsed_seconds=time.time()-started,new_games=0,source_deleted=False))

if __name__=='__main__':main()
