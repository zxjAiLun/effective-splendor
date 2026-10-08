"""Explicit DSW process adapter. No systemd, no claim of hard cgroup isolation.

A relay owns a new process group, reaps its child (including waited child CPU),
checks its parent identity, and bounds wall/CPU/RSS. Only its own group is killed.
The existing PPO implementation is unchanged; install() replaces process I/O only
inside the new execution, whose source bytes must be separately pinned.
"""
import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write
from training.prism_portable.processes import directory_bytes


def same_process(pid, created):
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE and abs(p.create_time()-created) < .01
    except psutil.NoSuchProcess:
        return False


def stop_reason(elapsed, cpu, rss, count, *, wall, cpu_limit, memory, max_processes):
    if elapsed >= wall: return 'wall_deadline'
    if cpu >= cpu_limit: return 'cpu_deadline'
    if rss >= memory: return 'memory_deadline'
    if count > max_processes: return 'process_limit'
    return None


class ProcessTree:
    def __init__(self, *, cpu_seconds, memory_bytes, max_processes=6):
        if not math.isfinite(cpu_seconds) or cpu_seconds <= 0 or memory_bytes <= 0:
            raise ValueError('positive finite process budgets required')
        self.cpu_seconds, self.memory_bytes, self.max_processes = cpu_seconds, memory_bytes, max_processes
        self.process = None
        self.last = None
        self.closed = False

    def start(self, argv, *, cwd, stdout, stderr):
        if self.process is not None: raise ValueError('single-use owned process tree')
        if not sys.platform.startswith('linux'): raise ValueError('DSW adapter requires Linux')
        control = Path(os.environ['PRISM_PPO_CONTROL_DIR'])/'relay'
        control.mkdir(parents=True, exist_ok=True)
        self.record = control/(uuid.uuid4().hex+'.json')
        parent = psutil.Process()
        cmd = [sys.executable,'-B',str(Path(__file__).resolve()),'--relay',
               '--parent-pid',str(parent.pid),'--parent-created',str(parent.create_time()),
               '--record',str(self.record),'--cpu',str(self.cpu_seconds),
               '--memory',str(self.memory_bytes),'--max-processes',str(self.max_processes),
               '--wall',str(min(float(os.environ.get('PRISM_DSW_REMAINING_WALL','21600')),max(90,self.cpu_seconds*2))),
               '--',*map(str,argv)]
        self.process = subprocess.Popen(cmd,cwd=cwd,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
        self.created = psutil.Process(self.process.pid).create_time()
        return self.process

    def accounting(self):
        if self.record.exists(): self.last = read(self.record)
        return self.last or dict(cpu_seconds=0.,user_cpu_seconds=0.,kernel_cpu_seconds=0.,
                                 active_processes=0,peak_memory_bytes=0,process_tree_rss_sum_bytes=0)

    def terminate(self):
        if self.process is not None and same_process(self.process.pid,self.created):
            # Relay handles SIGTERM by persisting failure and killing only its own group.
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if same_process(self.process.pid,self.created) and os.getpgid(self.process.pid)==self.process.pid:
                    os.killpg(self.process.pid,signal.SIGKILL)
                self.process.wait(timeout=5)

    def wait(self, *, wall_seconds, storage_root=None, max_storage_bytes=None,
             stop_checker=None, snapshot=None, accounting=None, storage_interval=5.):
        began=time.monotonic();next_scan=next_snapshot=0.;reason=None
        while self.process.poll() is None:
            now=time.monotonic()
            counters=accounting() if accounting else self.accounting()
            if snapshot and now>=next_snapshot:snapshot(counters);next_snapshot=now+1
            reason=stop_reason(now-began,counters['cpu_seconds'],counters.get('process_tree_rss_sum_bytes',0),
                counters.get('active_processes',0),wall=wall_seconds,cpu_limit=self.cpu_seconds,
                memory=self.memory_bytes,max_processes=self.max_processes)
            if not reason and stop_checker:reason=stop_checker()
            if storage_root is not None and now>=next_scan:
                next_scan=now+storage_interval
                if directory_bytes(storage_root)>max_storage_bytes:reason='storage_deadline'
            if reason:self.terminate();break
            time.sleep(.1)
        code=self.process.wait(timeout=10);counters=self.accounting()
        reason=reason or counters.get('stop_reason')
        if storage_root is not None and directory_bytes(storage_root)>max_storage_bytes:reason='storage_deadline'
        return dict(counters,returncode=code,stop_reason=reason,wall_seconds=time.monotonic()-began,
                    accounting_scope='owned relay/group; sampled RSS soft limit; OS waited-child CPU')

    def close(self):
        if not self.closed:
            if self.process is not None:
                self.terminate();self.accounting()
            self.closed=True

    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def install():
    from training.prism_portable.engine.ppo import arena
    arena.ProcessTree = ProcessTree


def relay(args, command):
    import resource
    if not command:raise ValueError('missing owned command')
    if not same_process(args.parent_pid,args.parent_created):raise RuntimeError('launch parent died')
    # Become a subreaper: escaped grandchildren are still owned descendants.
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'PR_SET_CHILD_SUBREAPER')
    resource.setrlimit(resource.RLIMIT_CPU,(math.ceil(args.cpu),math.ceil(args.cpu)+1))
    resource.setrlimit(resource.RLIMIT_AS,(args.memory,args.memory))
    signals=[]
    signal.signal(signal.SIGTERM,lambda n,f:signals.append(n))
    signal.signal(signal.SIGINT,lambda n,f:signals.append(n))
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL)
    own=psutil.Process();began=time.monotonic();peak=0;reason=None;last_cpu=0
    def usage():
        nonlocal peak,last_cpu
        ru=resource.getrusage(resource.RUSAGE_SELF);rc=resource.getrusage(resource.RUSAGE_CHILDREN)
        user=ru.ru_utime+rc.ru_utime;system=ru.ru_stime+rc.ru_stime;rss=own.memory_info().rss
        children=own.children(recursive=True)
        for p in children:
            try:
                t=p.cpu_times();user+=t.user+getattr(t,'children_user',0);system+=t.system+getattr(t,'children_system',0);rss+=p.memory_info().rss
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        cpu=max(last_cpu,user+system);last_cpu=cpu;peak=max(peak,rss)
        return dict(cpu_seconds=cpu,user_cpu_seconds=user,kernel_cpu_seconds=system,
                    active_processes=1+len(children),peak_memory_bytes=peak,
                    process_tree_rss_sum_bytes=rss,observed_at=time.time(),pid=os.getpid())
    try:
        while process.poll() is None:
            counters=usage()
            reason=stop_reason(time.monotonic()-began,counters['cpu_seconds'],counters['process_tree_rss_sum_bytes'],
                counters['active_processes'],wall=args.wall,cpu_limit=args.cpu,memory=args.memory,max_processes=args.max_processes)
            if not same_process(args.parent_pid,args.parent_created):reason='parent_identity_lost'
            if signals:reason='operator_terminate'
            write(args.record,dict(counters,status='RUNNING',stop_reason=reason))
            if reason:break
            time.sleep(.1)
        if reason:
            for p in reversed(own.children(recursive=True)):
                try:p.kill()
                except psutil.NoSuchProcess:pass
        code=process.wait(timeout=10)
        counters=usage()
        write(args.record,dict(counters,status='FINISHED',returncode=code if not reason else 124,
                               stop_reason=reason,wall_seconds=time.monotonic()-began))
    finally:
        # The relay is its own process-group leader. A crash/parent loss never
        # targets any historical campaign or the SSH session's process group.
        for p in reversed(own.children(recursive=True)):
            try:p.kill()
            except psutil.NoSuchProcess:pass
    return 124 if reason else code


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--relay',action='store_true')
    p.add_argument('--parent-pid',type=int,required=True);p.add_argument('--parent-created',type=float,required=True)
    p.add_argument('--record',type=Path,required=True);p.add_argument('--cpu',type=float,required=True)
    p.add_argument('--memory',type=int,required=True);p.add_argument('--wall',type=float,required=True)
    p.add_argument('--max-processes',type=int,required=True);p.add_argument('command',nargs=argparse.REMAINDER)
    a=p.parse_args();raise SystemExit(relay(a,a.command[1:] if a.command[:1]==['--'] else a.command))
