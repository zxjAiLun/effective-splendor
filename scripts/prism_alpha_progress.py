"""Read-only compact M56 progress; never loads the active Torch writer."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'local-artifacts/prism/alpha-v0.1.1'


def snapshot():
    def read(path):
        try: return json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError): return None
    status = read(ART / 'controller-status.json') or {}
    training = len(list((ART / 'campaign/attempts').glob('*/completion.json')))
    stages = {}
    for name, total in (('development', 384), ('acceptance', 4096)):
        progress = [read(p) for p in (ART / name / 'runs').glob('*/progress.json')]
        done = sum(sum(g.get('status') == 'completed' for g in p.get('games', {}).values()) for p in progress if p)
        stages[name] = {'completed': done, 'budget': total}
    sessions = read(ART / 'campaign/supervisor-sessions.json') or []
    return {'controller': status.get('state'), 'training_arena_completions': training,
            'training_budget': 1024, 'exported_cycles': sorted(p.name for p in (ART / 'campaign').glob('cycle-*-export')),
            'evaluation': stages, 'training_supervisor': sessions[-1]['status'] if sessions else None,
            'training_error_bytes': (ART / 'training.stderr.log').stat().st_size,
            'controller_error_bytes': (ART / 'controller.stderr.log').stat().st_size}


if __name__ == '__main__':
    import sys
    s = snapshot()
    if '--json' in sys.argv:
        print(json.dumps(s, ensure_ascii=False))
    else:
        completed = len(s['exported_cycles'])
        print(f"训练完赛：{s['training_arena_completions']}/1024；已完成并导出：{completed}/4轮。")
        if s['controller'] == 'WAITING_FOR_C4' and completed < 4:
            within = s['training_arena_completions'] - 256 * completed
            print(f"当前：第{completed + 1}轮" + ('更新中。' if within >= 256 else f'采样 {within}/256。'))
        else:
            print('当前控制阶段：' + str(s['controller']))
        print(f"开发完赛：{s['evaluation']['development']['completed']}/384；独立验收完赛：{s['evaluation']['acceptance']['completed']}/4096。")
        print(f"监督状态：{s['training_supervisor']}；训练/控制器错误日志字节：{s['training_error_bytes']}/{s['controller_error_bytes']}。")
