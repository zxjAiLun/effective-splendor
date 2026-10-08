"""M67-only lossless object compression/dedup; original raw content SHA preserved.

PT ZIP tensor bodies deduplicate by byte SHA. Reassembly must equal original raw
bytes/hash before torch.load. JSON gzip and original commits/HEAD retained. Install
only within separately pinned M67 processes, never on historical campaigns.
"""
import gzip
import hashlib
import io
import json
import struct
import zipfile

def pt_segments(data):
    """Partition exact original torch ZIP bytes at tensor body boundaries."""
    boundaries={0,len(data)}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            if '/data/' not in info.filename:continue
            if info.compress_type!=zipfile.ZIP_STORED:raise ValueError('unexpected compressed Torch ZIP member')
            start=info.header_offset
            if data[start:start+4]!=b'PK\x03\x04':raise ValueError('invalid local ZIP header')
            name,extra=struct.unpack_from('<HH',data,start+26)
            body=start+30+name+extra;end=body+info.compress_size
            if not 0<=body<=end<=len(data):raise ValueError('invalid tensor span')
            boundaries.update((body,end))
    points=sorted(boundaries)
    return [data[a:b] for a,b in zip(points,points[1:])]

def install():
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.engine.ppo.contract import sha
    if getattr(CommitStore,'_m67_compressed',False):return
    original_put,original_get=CommitStore._put,CommitStore._get
    def put(self,folder,data,suffix):
        if folder!='objects':return original_put(self,folder,data,suffix)
        self._require_lock();key=hashlib.sha256(data).hexdigest();path=self.root/folder/(key+suffix)
        if path.exists():
            if get(self,folder,key,suffix)!=data:raise ValueError('content-addressed artifact is corrupt')
        elif suffix=='.pt':
            parts=[]
            for segment in pt_segments(data):
                part=hashlib.sha256(segment).hexdigest();target=self.root/'m67-blocks'/(part+'.gz')
                if target.exists():
                    if gzip.decompress(target.read_bytes())!=segment:raise ValueError('deduplicated block corrupt')
                else:self._write(target,gzip.compress(segment,compresslevel=1,mtime=0))
                parts.append({'sha256':part,'bytes':len(segment)})
            manifest={'format':'m67-exact-pt-blocks-v1','raw_sha256':key,'raw_bytes':len(data),'parts':parts}
            self._write(path,gzip.compress(json.dumps(manifest,sort_keys=True).encode(),compresslevel=1,mtime=0))
        else:self._write(path,gzip.compress(data,compresslevel=1,mtime=0))
        return key
    def get(self,folder,key,suffix):
        if folder!='objects':return original_get(self,folder,key,suffix)
        sha(key,'artifact hash');path=self.root/folder/(key+suffix)
        try:
            unpacked=gzip.decompress(path.read_bytes())
            if suffix=='.pt':
                manifest=json.loads(unpacked)
                if manifest['format']!='m67-exact-pt-blocks-v1' or manifest['raw_sha256']!=key:raise ValueError('PT manifest identity mismatch')
                chunks=[]
                for part in manifest['parts']:
                    sha(part['sha256'],'block hash');chunk=gzip.decompress((self.root/'m67-blocks'/(part['sha256']+'.gz')).read_bytes())
                    if len(chunk)!=part['bytes'] or hashlib.sha256(chunk).hexdigest()!=part['sha256']:raise ValueError('PT block hash mismatch')
                    chunks.append(chunk)
                data=b''.join(chunks)
                if len(data)!=manifest['raw_bytes']:raise ValueError('PT byte count mismatch')
            else:data=unpacked
        except (OSError,EOFError) as error:raise ValueError('compressed object corrupt') from error
        if hashlib.sha256(data).hexdigest()!=key:raise ValueError('artifact hash mismatch')
        return data
    CommitStore._put,CommitStore._get=put,get
    CommitStore._m67_compressed=True
