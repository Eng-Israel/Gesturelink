const test = require('node:test');
const assert = require('node:assert/strict');
const {
  normalizeGloss,
  buildSignVideoMap,
  resolveDisplayWords,
  buildSpokenSentence,
} = require('../sign_utils.js');

test('normalizeGloss collapses punctuation and whitespace', () => {
  assert.equal(normalizeGloss('Thank you!'), 'thank you');
  assert.equal(normalizeGloss('  Hello, world  '), 'hello world');
});

test('buildSignVideoMap keeps one exact video reference for each gloss', () => {
  const map = buildSignVideoMap([{ gloss: 'thank you', video_id: '69502' }]);
  assert.equal(map.get('thank you'), 'dataset/videos/thank%20you_69502.mp4');
  assert.equal(map.has('thank'), false);
  assert.equal(map.has('you'), false);
});

test('resolveDisplayWords matches available signs across the full transcript', () => {
  const map = buildSignVideoMap([
    { gloss: 'hello', video_id: '1' },
    { gloss: 'thank you', video_id: '69502' },
    { gloss: 'yes', video_id: '2' },
    { gloss: 'water', video_id: '3' },
    { gloss: 'help', video_id: '4' },
    { gloss: 'go', video_id: '5' },
    { gloss: 'eat', video_id: '6' },
    { gloss: 'drink', video_id: '7' },
  ]);
  assert.deepEqual(
    resolveDisplayWords('Hello, thank you! Unknown yes water help go eat drink.', map),
    ['hello', 'thank you', 'yes', 'water', 'help', 'go', 'eat', 'drink'],
  );
  assert.deepEqual(resolveDisplayWords('Good morning', map), []);
});

test('buildSpokenSentence adds basic English grammar to sign sequences', () => {
  assert.equal(buildSpokenSentence(['want', 'water']), 'I want water.');
  assert.equal(buildSpokenSentence(['you', 'want', 'water']), 'You want water.');
  assert.equal(buildSpokenSentence(['what', 'you', 'want']), 'What do you want?');
  assert.equal(buildSpokenSentence(['thank you']), 'Thank you.');
  assert.equal(buildSpokenSentence(['go', 'go', 'home']), 'I go home.');
});
