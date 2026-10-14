document.documentElement.classList.add('js');
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{
  const filter=button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  document.querySelectorAll('#opponent-table tbody tr').forEach(row=>row.hidden=filter!=='all'&&row.dataset.group!==filter);
  document.getElementById('filter-summary').textContent=filter==='all'?'显示 8 个对手 · 每个模型对每个对手 512 局':filter==='common'?'显示 6 个共同对手 · 用于共同池判定':'显示 2 个新增对手 · 用于覆盖面保留判定';
}));
document.querySelectorAll('[data-reference]').forEach(button=>button.addEventListener('click',()=>{
  const key=button.dataset.reference;
  document.querySelectorAll('[data-reference]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  document.querySelectorAll('[data-profile-panel]').forEach(panel=>panel.hidden=panel.dataset.profilePanel!==key);
}));
