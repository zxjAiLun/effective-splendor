"""Result-bound M79 wrapper around the shared offline Prism reading template."""
from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training.prism_portable.common import digest, read, write


def _path(root: Path, value: str) -> Path:
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"M79 reading path escapes report root: {value}") from error
    return path


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid M79 reading count: {label}")
    return value


def _expected_pairs(contract: dict[str, Any]) -> set[tuple[str, str]]:
    evaluation = contract["evaluation"]
    pairs = {(actor, opponent)
             for actor in evaluation["common_actors"]
             for opponent in evaluation["common_seed_by_opponent"]}
    pairs.update((actor, opponent)
                 for actor in evaluation["coverage_actors"]
                 for opponent in evaluation["coverage_seed_by_opponent"])
    pairs.add((evaluation["direct"]["candidate"], "parent"))
    return pairs


def validate(spec_path: str | Path, root: str | Path | None = None):
    """Validate every reading input and ensure displayed pairs match the frozen grid."""
    root = Path(root or ROOT).resolve()
    spec_path = _path(root, str(spec_path))
    spec = read(spec_path)
    if spec.get("format") != "prism-m79-bounded-reading-v1":
        raise ValueError("invalid M79 result-bound reading schema")

    bound = {
        "result": ("result", "result_sha256"),
        "markdown": ("markdown", "markdown_sha256"),
        "contract": ("contract", "contract_sha256"),
        "candidate_registry": ("candidate_registry", "candidate_registry_sha256"),
        "evaluation_plan": ("evaluation_plan", "evaluation_plan_sha256"),
        "evaluation_completion": ("evaluation_completion", "evaluation_completion_sha256"),
    }
    paths = {}
    for key, (path_key, hash_key) in bound.items():
        path = _path(root, spec[path_key])
        if not path.is_file() or digest(path) != spec.get(hash_key):
            raise ValueError(f"M79 reading input hash drift: {key}")
        paths[key] = path

    result = read(paths["result"])
    contract = read(paths["contract"])
    evaluation_plan = read(paths["evaluation_plan"])
    completion = read(paths["evaluation_completion"])
    if result.get("format") != "prism-m79-mainline-result-v1" or result.get("round") != "M79":
        raise ValueError("unsupported M79 result schema")
    if result.get("result_source_hashes", {}).get("report_builder") != digest(root / "scripts/prism_m79_report.py"):
        raise ValueError("M79 report source binding drift")
    if result.get("result_source_hashes", {}).get("reading_adapter") != digest(Path(__file__)):
        raise ValueError("M79 reading adapter source binding drift")
    sources = result.get("result_source_hashes", {})
    for key, source_key in (("contract", "execution_plan"),
                            ("candidate_registry", "candidate_registry"),
                            ("evaluation_plan", "evaluation_plan"),
                            ("evaluation_completion", "evaluation_completion")):
        if sources.get(source_key) != digest(paths[key]):
            raise ValueError(f"M79 result source hash mismatch: {key}")
    if (evaluation_plan.get("plan_sha256") != digest(paths["contract"])
            or evaluation_plan.get("candidate_registry_sha256") != digest(paths["candidate_registry"])
            or completion.get("plan_sha256") != digest(paths["evaluation_plan"])):
        raise ValueError("M79 reading plan or completion binding drift")

    planned = _integer(result.get("planned_games"), "planned")
    completed = _integer(result.get("completed_games"), "completed")
    truncated = _integer(result.get("truncated_games"), "truncated")
    grid = result.get("grid", {})
    missing = result.get("missing", [])
    caps = result.get("caps", [])
    if not isinstance(missing, list) or not isinstance(caps, list):
        raise ValueError("M79 missing/cap identities are not lists")
    if (grid.get("planned_games") != planned or grid.get("completed_games") != completed
            or grid.get("truncated_games") != truncated
            or grid.get("missing_games") != len(missing)
            or truncated != len(caps) or completed + truncated + len(missing) != planned):
        raise ValueError("M79 result counts do not balance")
    if (evaluation_plan.get("total_games") != planned
            or completion.get("completed_games") != completed
            or completion.get("truncated_games") != truncated
            or result.get("completion_receipt") != completion):
        raise ValueError("M79 result and evaluation completion counts differ")

    missing_ids = {(item["candidate"], item["opponent"], item["seed"], item["candidate_seat"])
                   for item in missing}
    cap_ids = {(item["candidate"], item["opponent"], item["seed"], item["candidate_seat"])
               for item in caps}
    if len(missing_ids) != len(missing) or len(cap_ids) != len(caps) or missing_ids & cap_ids:
        raise ValueError("duplicate or overlapping M79 incomplete identities")

    pairs = result.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("M79 result pairs are missing")
    pair_ids = [(item.get("candidate"), item.get("opponent")) for item in pairs]
    if len(pair_ids) != len(set(pair_ids)) or set(pair_ids) != _expected_pairs(contract):
        raise ValueError("M79 result opponent pair coverage drift")
    if sum(_integer(item.get("planned_games"), "pair planned") for item in pairs) != planned:
        raise ValueError("M79 per-opponent planned counts do not balance")
    completed_sum = 0
    for pair in pairs:
        pair_planned = _integer(pair.get("planned_games"), "pair planned")
        pair_completed = _integer(pair.get("completed_games"), "pair completed")
        pair_missing = _integer(pair.get("missing_games"), "pair missing")
        if pair_completed + pair_missing != pair_planned:
            raise ValueError("M79 per-opponent completed/missing counts do not balance")
        if pair.get("candidate_metrics") is None:
            if pair_completed or pair.get("opponent_metrics") is not None:
                raise ValueError("M79 empty pair has inconsistent side metrics")
        else:
            completed_sum += _integer(pair["candidate_metrics"].get("games"), "pair metric games")
            for side in ("candidate_metrics", "opponent_metrics"):
                metrics = pair[side]
                if (metrics["wins"] + metrics["ties"] + metrics["losses"] != metrics["games"]
                        or not math.isclose((metrics["wins"] + 0.5 * metrics["ties"]) / metrics["games"],
                                            metrics["score_rate"], abs_tol=1e-12)):
                    raise ValueError(f"M79 {side} WDL/score drift")
        seat_games = 0
        seat_ids = set()
        for seat in pair.get("seats", []):
            seat_id = seat.get("candidate_seat")
            if seat_id not in (0, 1) or seat_id in seat_ids:
                raise ValueError("M79 opponent pair seat identity drift")
            seat_ids.add(seat_id)
            seat_games += _integer(seat.get("games"), "seat games")
        if seat_games != pair_completed or (pair_completed and seat_ids != {0, 1}):
            raise ValueError("M79 per-opponent seat count drift")
    if completed_sum != completed:
        raise ValueError("M79 result and pair completed-game counts differ")

    story = spec.get("story", {})
    if [item.get("label") for item in story.get("conclusions", [])] != ["产物", "竞技", "风格"]:
        raise ValueError("M79 reading page must lead with artifact, competition, and style verdicts")
    if story.get("conclusions") != result.get("conclusions"):
        raise ValueError("M79 reading conclusions differ from frozen result")
    if not story.get("next") or "授权" in story["next"] and "继续已授权" not in story["next"]:
        raise ValueError("M79 reading next action is missing or incorrectly deferred")

    output = _path(root, spec["output"])
    markdown = paths["markdown"]
    return spec, result, contract, paths, output, markdown


def _payload(spec: dict[str, Any], result: dict[str, Any], output: Path,
             markdown: Path, result_sha256: str) -> dict[str, Any]:
    return {
        "format": "prism-m79-human-reading-payload-v1",
        "story": spec["story"],
        "names": spec["names"],
        "result": result,
        "result_sha256": result_sha256,
        "links": {
            "evidence": os.path.relpath(markdown, output.parent).replace(os.sep, "/"),
            "audit": os.path.relpath(output.with_suffix(".audit.html"), output.parent).replace(os.sep, "/"),
            "reading_markdown": os.path.relpath(output.with_suffix(".reading.md"), output.parent).replace(os.sep, "/"),
        },
    }


_JS = r'''\
'use strict';
const d=JSON.parse(document.getElementById('report-data').textContent),r=d.result,S=d.story;
const E=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=(v,k=3)=>Number.isFinite(v)?v.toFixed(k):'NOT_MEASURED';
const pct=v=>Number.isFinite(v)?(v*100).toFixed(2)+'%':'NOT_MEASURED';
const name=k=>d.names[k]||k;
const conclusions=S.conclusions.map(c=>`<article class="card warn"><small>${E(c.label)}</small><b>${E(c.value)}</b><p>${E(c.explanation)}</p></article>`).join('');
const endpointRows=Object.entries(r.statistics.endpoints).map(([k,v])=>`<tr><td>${E(k)}</td><td>${E(v.status)}</td><td>${pct(v.estimate)}</td><td>${E(JSON.stringify(v.interval??'NOT_MEASURED'))}</td><td>${E(JSON.stringify(v.gates??{}))}</td></tr>`).join('');
const higher=(v,other,format)=>{if(!Number.isFinite(v))return '<span class="metric-value">NOT_MEASURED</span>';const shown=format(v);if(!Number.isFinite(other)||shown===format(other))return '<span class="metric-value">'+E(shown)+'</span>';return v>other?'<strong class="metric-win better" title="本组显示值较高">'+E(shown)+'</strong>':'<span class="metric-value">'+E(shown)+'</span>';};
const pairRows=r.pairs.map(p=>{const a=p.candidate_metrics,b=p.opponent_metrics;const side=(m,other)=>m?`${m.wins}/${m.ties}/${m.losses} · 半平 ${higher(m.score_rate,other?.score_rate,pct)} · 最终VP/局 ${higher(m.mean_prestige,other?.mean_prestige,v=>n(v,2))}`:'NOT_MEASURED';return `<tr><td>${E(name(p.candidate))}</td><td>${E(name(p.opponent))}</td><td>${E(p.status)}</td><td>${p.completed_games}/${p.planned_games}</td><td>${side(a,b)}</td><td>${side(b,a)}</td><td>${E(p.seats.map(s=>`座${s.candidate_seat}:${s.games}`).join('；')||'NOT_MEASURED')}</td></tr>`;}).join('');
document.getElementById('app').innerHTML=`<header><div class="eyebrow">PRISM · ${E(S.round)} · 独立评测阅读页</div><h1>${E(S.title)}</h1><p class="headline">${E(S.headline)}</p><p>${E(S.identity)}</p><p class="goal">${E(S.interpretation)}</p></header><div class="conclusions">${conclusions}</div><section><h2>冻结竞技端点</h2><div class="scroll"><table><thead><tr><th>端点</th><th>状态</th><th>估计</th><th>普通区间</th><th>冻结门</th></tr></thead><tbody>${endpointRows}</tbody></table></div></section><section><h2>逐对手与双方分母</h2><p>半平得分=(胜+0.5×平)/已完成局数。缺失与科学截断单独保留，不替换为胜、平或负。粗体只标出同组显示值较大的一侧；半平得分和最终VP的较高值有利。显示持平不强调，高亮不判定冻结门。</p><div class="scroll"><table><thead><tr><th>模型本人</th><th>对手</th><th>状态</th><th>终局/计划</th><th>模型本人 W/D/L · 半平得分 · 最终VP/局</th><th>对手本人 W/D/L · 半平得分 · 最终VP/局</th><th>座位</th></tr></thead><tbody>${pairRows}</tbody></table></div><p>完整双方指标、逐座位表、全部预期缺失身份、截断、来源SHA和Rust审计见<a href="${E(d.links.evidence)}">完整证据Markdown</a>及<a href="${E(d.links.audit)}">HTML审计页</a>。</p></section><section><h2>下一步</h2><p class="next">${E(S.next)}</p></section><footer class="foot"><a href="${E(d.links.reading_markdown)}">本页Markdown</a></footer>`;
'''


def build(spec_path: str | Path, root: str | Path | None = None,
          templates: str | Path | None = None) -> dict[str, Any]:
    root = Path(root or ROOT).resolve()
    templates = Path(templates or root / "scripts" / "templates").resolve()
    spec, result, _, paths, output, markdown_path = validate(spec_path, root)
    targets = (output, output.with_suffix(".audit.html"),
               output.with_suffix(".reading.md"), output.with_suffix(".reading-receipt.json"))
    if any(path.exists() for path in targets):
        raise FileExistsError("preserve existing M79 reading revision")
    if not (templates / "prism-reading.html").is_file() or not (templates / "prism-reading.css").is_file():
        raise FileNotFoundError("shared Prism reading template is unavailable")

    payload = _payload(spec, result, output, markdown_path, digest(paths["result"]))
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    document = (templates / "prism-reading.html").read_text(encoding="utf-8")
    document = document.replace("@@TITLE@@", html.escape(spec["story"]["title"]))
    document = document.replace("@@CSS@@", (templates / "prism-reading.css").read_text(encoding="utf-8"))
    document = document.replace("@@DATA@@", encoded).replace("@@JS@@", _JS)
    if "@@" in document or "</script><script>" in encoded:
        raise ValueError("M79 reading template has an unfilled or unsafe payload token")

    audit_path = output.with_suffix(".audit.html")
    try:
        import markdown
    except ImportError as error:
        raise RuntimeError("Markdown is required for the shared Prism audit renderer") from error
    audit = "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><body>"
    audit += markdown.markdown(markdown_path.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
    audit += "</body></html>"
    readme = ("# " + spec["story"]["title"] + "\n\n" + spec["story"]["headline"] + "\n\n"
              + "\n\n".join(f"**{item['label']}：{item['value']}。** {item['explanation']}"
                              for item in spec["story"]["conclusions"])
              + "\n\n" + spec["story"]["identity"] + "\n\n下一步：" + spec["story"]["next"]
              + "\n\n完整双方表格和所有缺失身份见 [完整证据](" + payload["links"]["evidence"] + ").\n")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    audit_path.write_text(audit, encoding="utf-8")
    output.with_suffix(".reading.md").write_text(readme, encoding="utf-8")
    receipt = {
        "format": "prism-m79-reading-receipt-v1",
        "adapter_sha256": digest(Path(__file__)),
        "spec_sha256": digest(_path(root, str(spec_path))),
        "result_sha256": digest(paths["result"]),
        "contract_sha256": digest(paths["contract"]),
        "markdown_sha256": digest(markdown_path),
        "html_sha256": digest(output),
        "audit_html_sha256": digest(audit_path),
        "reading_markdown_sha256": digest(output.with_suffix(".reading.md")),
        "pair_rows": len(result["pairs"]),
        "conclusions": [item["label"] for item in spec["story"]["conclusions"]],
        "games_dispatched": 0,
        "model_forward_calls": 0,
        "pixel_visual": "NOT_VERIFIED",
    }
    write(output.with_suffix(".reading-receipt.json"), receipt)
    return receipt


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--templates", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(build(args.spec, args.root, args.templates), ensure_ascii=False, indent=2))
