/* Shared, offline-only lesson interactions. No storage, requests or mastery state. */
(function (root) {
  'use strict';
  function grade(selected, correct, explanation) {
    if (selected === null) return { state: 'empty', text: '先选一个判断，再查看反馈。猜错也能帮助定位问题。' };
    if (String(selected) === String(correct)) return { state: 'correct', text: '这题判断正确。' + explanation + ' 请再用自己的话解释原因；一次答对不等于长期掌握。' };
    return { state: 'incorrect', text: '这个判断需要调整。' + explanation + ' 可以重新选择，再试一次。' };
  }
  function ppo(oldProbability, newProbability, advantage, epsilon) {
    if (![oldProbability, newProbability, advantage, epsilon].every(Number.isFinite) || oldProbability <= 0 || oldProbability > 1 || newProbability < 0 || newProbability > 1 || epsilon < 0 || epsilon >= 1) throw new RangeError('Invalid PPO teaching inputs');
    const ratio = newProbability / oldProbability;
    const clippedRatio = Math.max(1 - epsilon, Math.min(1 + epsilon, ratio));
    return { ratio, clippedRatio, raw: ratio * advantage, clipped: clippedRatio * advantage, objective: Math.min(ratio * advantage, clippedRatio * advantage) };
  }
  function init(document) {
    document.querySelectorAll('[data-quiz]').forEach(function (form) {
      const feedback = form.querySelector('[data-feedback]');
      form.querySelector('button[type="submit"]').disabled = false;
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        const selected = form.querySelector('input:checked');
        const result = grade(selected ? selected.value : null, form.dataset.correct, form.dataset.explanation);
        feedback.dataset.state = result.state;
        feedback.textContent = result.text;
      });
      form.addEventListener('reset', function () {
        feedback.textContent = '';
        delete feedback.dataset.state;
      });
    });
    document.querySelectorAll('[data-ppo-lab]').forEach(function (lab) {
      const probability = lab.querySelector('[data-probability]');
      const advantage = lab.querySelector('[data-advantage]');
      const output = lab.querySelector('output');
      function render() {
        const p = Number(probability.value), a = Number(advantage.value);
        const result = ppo(0.2, p, a, 0.2);
        output.textContent = '新概率 = ' + p.toFixed(2) + '；旧概率 = 0.20\n比率 r = ' + result.ratio.toFixed(2) + '；clip(r) = ' + result.clippedRatio.toFixed(2) + '\n原项 r×A = ' + result.raw.toFixed(2) + '；截断项 = ' + result.clipped.toFixed(2) + '\n本样本目标 min = ' + result.objective.toFixed(2) + '\n' + (a > 0 ? 'A 为正：超过上沿后，本样本不再奖励继续提高概率。' : 'A 为负：低于下沿后，本样本不再奖励继续降低概率；往坏方向提高概率仍受惩罚。');
      }
      probability.addEventListener('input', render);
      advantage.addEventListener('change', render);
      render();
    });
  }
  const api = { grade, ppo, init };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root.document) init(root.document);
})(typeof globalThis !== 'undefined' ? globalThis : this);
