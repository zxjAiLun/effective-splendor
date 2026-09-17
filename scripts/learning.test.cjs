'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { grade, ppo } = require('../assets/learning.js');

test('empty answer asks for a choice, without awarding completion', () => {
  assert.equal(grade(null, '1', '解释').state, 'empty');
});
test('right and wrong answers include useful feedback; each retry is independent', () => {
  assert.equal(grade('0', '1', '解释').state, 'incorrect');
  const right = grade('1', '1', '解释');
  assert.equal(right.state, 'correct');
  assert.ok(right.text.includes('解释'));
  assert.ok(right.text.includes('不等于长期掌握'));
  assert.equal(grade('2', '1', '解释').state, 'incorrect');
});
test('positive advantage stops receiving extra incentive beyond upper clip', () => {
  const x = ppo(0.2, 0.3, 1, 0.2);
  assert.ok(Math.abs(x.ratio - 1.5) < 1e-12);
  assert.equal(x.objective, 1.2);
  assert.equal(ppo(0.2, 0.5, 1, 0.2).objective, 1.2);
});
test('negative advantage stops receiving extra incentive below lower clip', () => {
  assert.equal(ppo(0.2, 0.1, -1, 0.2).objective, -0.8);
  assert.equal(ppo(0.2, 0.02, -1, 0.2).objective, -0.8);
});
test('movement in the wrong direction is not protected by clipping', () => {
  assert.equal(ppo(0.2, 0.1, 1, 0.2).objective, 0.5);
  assert.equal(ppo(0.2, 0.4, -1, 0.2).objective, -2);
});
test('unchanged ratio, clip boundaries and zero advantage behave correctly', () => {
  assert.equal(ppo(0.2, 0.2, 1, 0.2).objective, 1);
  assert.equal(ppo(0.2, 0.24, 1, 0.2).objective, 1.2);
  assert.equal(ppo(0.2, 0.16, -1, 0.2).objective, -0.8);
  assert.equal(ppo(0.2, 0.4, 0, 0.2).objective, 0);
});
test('reject invalid probabilities, epsilon and non-finite inputs', () => {
  for (const inputs of [[0, .2, 1, .2], [-.1, .2, 1, .2], [1.1, .2, 1, .2], [.2, -.1, 1, .2], [.2, 1.1, 1, .2], [.2, .2, NaN, .2], [.2, .2, 1, 1], [.2, .2, 1, -.1]]) {
    assert.throws(() => ppo(...inputs), RangeError);
  }
});
