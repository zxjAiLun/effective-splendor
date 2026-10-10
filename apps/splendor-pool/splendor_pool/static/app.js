// Splendor Arena Pool Web Client (Vanilla JS)

let isPaused = false;
let countdown = 3;

async function fetchOverview() {
  try {
    const res = await fetch('/api/overview');
    const data = await res.json();
    isPaused = data.is_paused;

    const badge = document.getElementById('poolStatus');
    const btn = document.getElementById('togglePauseBtn');
    if (isPaused) {
      badge.textContent = '已暂停';
      badge.className = 'badge badge-paused';
      btn.textContent = '恢复对局';
      btn.className = 'btn btn-success';
    } else {
      badge.textContent = '运行中';
      badge.className = 'badge badge-active';
      btn.textContent = '暂停对局';
      btn.className = 'btn btn-warning';
    }

    document.getElementById('activeModels').textContent = data.active_models;
    document.getElementById('totalModels').textContent = data.total_models;
    document.getElementById('totalMatches').textContent = data.completed_matches;

    if (data.top_model) {
      document.getElementById('topModelName').textContent = data.top_model.name;
      document.getElementById('topModelElo').textContent = `Elo: ${data.top_model.elo.toFixed(1)}`;
    }
  } catch (err) {
    console.error('Failed to fetch overview:', err);
  }
}

async function fetchModels() {
  try {
    const res = await fetch('/api/models');
    const models = await res.json();

    // Compute top highlights
    let bestWinRate = { name: '-', wr: 0 };
    let bestScore = { name: '-', score: 0 };
    let bestRedeem = { name: '-', rate: 0 };

    for (const m of models) {
      if (m.games > 0) {
        const wr = ((m.wins + 0.5 * m.ties) / m.games) * 100.0;
        if (wr > bestWinRate.wr) bestWinRate = { name: m.name, wr };

        const avgScore = m.stats.avg_score || 0;
        if (avgScore > bestScore.score) bestScore = { name: m.name, score: avgScore };

        const redeem = m.stats.reserves_redemption_rate_pct || 0;
        if (redeem > bestRedeem.rate) bestRedeem = { name: m.name, rate: redeem };
      }
    }

    document.getElementById('bestWinRateModel').textContent = bestWinRate.name;
    document.getElementById('bestWinRateValue').textContent = bestWinRate.wr > 0 ? `胜率: ${bestWinRate.wr.toFixed(1)}%` : '-';

    document.getElementById('bestScoreModel').textContent = bestScore.name;
    document.getElementById('bestScoreValue').textContent = bestScore.score > 0 ? `局均分: ${bestScore.score.toFixed(1)}` : '-';

    document.getElementById('bestRedeemModel').textContent = bestRedeem.name;
    document.getElementById('bestRedeemValue').textContent = bestRedeem.rate > 0 ? `兑现率: ${bestRedeem.rate.toFixed(1)}%` : '-';

    // 1. Leaderboard Table
    const tbodyLead = document.querySelector('#leaderboardTable tbody');
    tbodyLead.innerHTML = '';
    models.forEach((m, idx) => {
      const tr = document.createElement('tr');
      const rank = idx + 1;
      const rankBadge = rank <= 3 ? `<span class="rank-pill rank-${rank}">${rank}</span>` : `<span class="rank-pill">${rank}</span>`;
      const wr = m.games > 0 ? (((m.wins + 0.5 * m.ties) / m.games) * 100.0).toFixed(1) + '%' : '-';
      const s0 = m.stats.seat0_win_rate_pct !== undefined && m.stats.seat0_games > 0 ? `${m.stats.seat0_win_rate_pct.toFixed(1)}%` : '-';
      const s1 = m.stats.seat1_win_rate_pct !== undefined && m.stats.seat1_games > 0 ? `${m.stats.seat1_win_rate_pct.toFixed(1)}%` : '-';
      const avgSc = m.stats.avg_score !== undefined ? m.stats.avg_score.toFixed(1) : '-';
      const margin = m.stats.avg_margin !== undefined ? (m.stats.avg_margin > 0 ? `+${m.stats.avg_margin.toFixed(1)}` : m.stats.avg_margin.toFixed(1)) : '-';
      const marginClass = m.stats.avg_margin > 0 ? 'pos-val' : m.stats.avg_margin < 0 ? 'neg-val' : '';

      tr.innerHTML = `
        <td align="center">${rankBadge}</td>
        <td><strong>${m.name}</strong></td>
        <td align="center"><span style="color:#94a3b8">${m.model_type}</span></td>
        <td align="right" class="elo-val">${m.elo.toFixed(1)}</td>
        <td align="right">${m.games}</td>
        <td align="center">${m.wins} - ${m.ties} - ${m.losses}</td>
        <td align="right"><strong>${wr}</strong></td>
        <td align="right">${s0}</td>
        <td align="right">${s1}</td>
        <td align="right">${avgSc}</td>
        <td align="right" class="${marginClass}">${margin}</td>
        <td align="center"><input type="number" step="0.1" min="0" max="100" style="width:55px;background:#1f2a3c;border:1px solid #2b3a50;color:#fff;padding:2px 4px;border-radius:4px;" value="${m.weight}" onchange="updateModelWeight(${m.id}, this.value)" /></td>
        <td align="center"><button class="btn ${m.enabled ? 'btn-success' : 'btn-warning'}" style="padding:2px 8px;font-size:11px;" onclick="toggleModelEnabled(${m.id}, ${!m.enabled})">${m.enabled ? '已启用' : '已停用'}</button></td>
      `;
      tbodyLead.appendChild(tr);
    });

    // 2. Tactical Table
    const tbodyTact = document.querySelector('#tacticalTable tbody');
    tbodyTact.innerHTML = '';
    models.forEach(m => {
      const tr = document.createElement('tr');
      const st = m.stats;
      if (m.games === 0) {
        tr.innerHTML = `
          <td><strong>${m.name}</strong></td>
          <td colspan="8" align="center" style="color:#64748b">暂无对局数据</td>
        `;
      } else {
        const vpTurn = st.avg_vp_turn ? st.avg_vp_turn.toFixed(3) : '-';
        const vpPly = st.avg_vp_ply ? st.avg_vp_ply.toFixed(3) : '-';
        const avgTurns = st.avg_turns ? st.avg_turns.toFixed(1) : '-';
        const avgPlies = st.avg_plies ? st.avg_plies.toFixed(1) : '-';
        const avgCards = st.avg_cards ? st.avg_cards.toFixed(2) : '-';
        const resAcq = st.avg_reserves_acquired ? st.avg_reserves_acquired.toFixed(1) : '0.0';
        const resBought = st.avg_reserves_bought ? st.avg_reserves_bought.toFixed(1) : '0.0';
        const resStrand = st.avg_reserves_stranded ? st.avg_reserves_stranded.toFixed(1) : '0.0';
        const resRedeem = st.reserves_redemption_rate_pct !== undefined ? `${st.reserves_redemption_rate_pct.toFixed(1)}%` : '-';
        const avgNobles = st.avg_nobles ? st.avg_nobles.toFixed(2) : '0.00';

        tr.innerHTML = `
          <td><strong>${m.name}</strong></td>
          <td align="right" class="pos-val">${vpTurn}</td>
          <td align="right">${vpPly}</td>
          <td align="right">${avgTurns}</td>
          <td align="right">${avgPlies}</td>
          <td align="right">${avgCards}</td>
          <td align="center">${resAcq} / ${resBought} / ${resStrand}</td>
          <td align="right">${resRedeem}</td>
          <td align="right">${avgNobles}</td>
        `;
      }
      tbodyTact.appendChild(tr);
    });

    // 3. Head-to-Head Table
    const tbodyH2H = document.querySelector('#h2hTable tbody');
    tbodyH2H.innerHTML = '';
    let hasH2H = false;
    models.forEach(m => {
      const h2h = m.stats.head_to_head || {};
      for (const [oppName, rec] of Object.entries(h2h)) {
        hasH2H = true;
        const tr = document.createElement('tr');
        const diffStr = rec.score_diff > 0 ? `+${rec.score_diff}` : `${rec.score_diff}`;
        const diffClass = rec.score_diff > 0 ? 'pos-val' : rec.score_diff < 0 ? 'neg-val' : '';
        tr.innerHTML = `
          <td><strong>${m.name}</strong> vs ${oppName}</td>
          <td align="right">${rec.games}</td>
          <td align="center">${rec.wins}-${rec.ties}-${rec.losses}</td>
          <td align="right"><strong>${rec.win_rate_pct.toFixed(1)}%</strong></td>
          <td align="right" class="${diffClass}">${diffStr}</td>
        `;
        tbodyH2H.appendChild(tr);
      }
    });
    if (!hasH2H) {
      tbodyH2H.innerHTML = `<tr><td colspan="5" align="center" style="color:#64748b">暂无对阵数据</td></tr>`;
    }
  } catch (err) {
    console.error('Failed to fetch models:', err);
  }
}

async function fetchMatches() {
  try {
    const res = await fetch('/api/matches?limit=12');
    const matches = await res.json();
    const tbody = document.querySelector('#recentMatchesTable tbody');
    tbody.innerHTML = '';

    if (matches.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" align="center" style="color:#64748b">暂无比赛记录</td></tr>`;
      return;
    }

    matches.forEach(m => {
      const tr = document.createElement('tr');
      const wName = m.winner_name || (m.status === 'completed' ? '平局' : m.status);
      const isDraw = wName === '平局' || !m.winner_name;
      const winnerCell = isDraw ? `<span style="color:#f59e0b">平局</span>` : `<strong style="color:#10b981">${wName}</strong>`;
      
      let deltaStr = '-';
      if (m.p0_elo_delta !== undefined && m.p1_elo_delta !== undefined) {
        const d0 = m.p0_elo_delta >= 0 ? `+${m.p0_elo_delta.toFixed(1)}` : `${m.p0_elo_delta.toFixed(1)}`;
        const d1 = m.p1_elo_delta >= 0 ? `+${m.p1_elo_delta.toFixed(1)}` : `${m.p1_elo_delta.toFixed(1)}`;
        deltaStr = `${d0} / ${d1}`;
      }

      tr.innerHTML = `
        <td align="center">#${m.id}</td>
        <td>${m.p0_name}</td>
        <td align="center"><strong>${m.p0_score} : ${m.p1_score}</strong></td>
        <td>${m.p1_name}</td>
        <td align="center">${winnerCell}</td>
        <td align="center"><small>${deltaStr}</small></td>
        <td align="right">${m.completed_plies || '-'}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to fetch matches:', err);
  }
}

async function togglePause() {
  try {
    await fetch('/api/pause', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paused: !isPaused }),
    });
    fetchOverview();
  } catch (err) {
    console.error('Failed to toggle pause:', err);
  }
}

async function updateModelWeight(modelId, weight) {
  try {
    await fetch(`/api/models/${modelId}/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ weight: parseFloat(weight) }),
    });
    fetchModels();
  } catch (err) {
    console.error('Failed to update weight:', err);
  }
}

async function toggleModelEnabled(modelId, enabled) {
  try {
    await fetch(`/api/models/${modelId}/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled }),
    });
    fetchModels();
  } catch (err) {
    console.error('Failed to toggle model:', err);
  }
}

async function refreshAll() {
  await Promise.all([fetchOverview(), fetchModels(), fetchMatches()]);
}

// Initial load & Polling
refreshAll();
setInterval(() => {
  countdown -= 1;
  if (countdown <= 0) {
    countdown = 3;
    refreshAll();
  }
  const timerElem = document.getElementById('refreshTimer');
  if (timerElem) {
    timerElem.textContent = `${countdown}秒后自动刷新`;
  }
}, 1000);
