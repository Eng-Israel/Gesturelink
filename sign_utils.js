function normalizeGloss(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function encodeVideoPath(gloss, videoId) {
  const normalizedGloss = normalizeGloss(gloss);
  const encodedGloss = encodeURIComponent(normalizedGloss);
  return `dataset/videos/${encodedGloss}_${videoId}.mp4`;
}

function buildSignVideoMap(samples) {
  const map = new Map();
  for (const sample of [...(samples || [])].sort((left, right) => {
    const glossOrder = normalizeGloss(left.gloss).localeCompare(normalizeGloss(right.gloss));
    return glossOrder || String(left.video_id).localeCompare(String(right.video_id));
  })) {
    const gloss = normalizeGloss(sample.gloss);
    if (!gloss || !sample.video_id) continue;
    if (!map.has(gloss)) map.set(gloss, sample.url || encodeVideoPath(gloss, sample.video_id));
  }
  return map;
}

function resolveDisplayWords(text, signVideoMap) {
  const words = normalizeGloss(text).split(' ').filter(Boolean);
  const glosses = [...signVideoMap.keys()].sort((left, right) => {
    const wordCountOrder = right.split(' ').length - left.split(' ').length;
    return wordCountOrder || right.length - left.length;
  });
  const matched = [];
  for (let index = 0; index < words.length;) {
    const gloss = glosses.find(candidate => {
      const parts = candidate.split(' ');
      return parts.every((part, offset) => words[index + offset] === part);
    });
    if (gloss) {
      matched.push(gloss);
      index += gloss.split(' ').length;
    } else {
      index++;
    }
  }
  return matched;
}

function buildSpokenSentence(signs) {
  const words = normalizeGloss((signs || []).join(' ')).split(' ').filter(Boolean);
  const compactWords = words.filter((word, index) => word !== words[index - 1]);
  if (!compactWords.length) return '';

  const actionWords = new Set(['want', 'need', 'go', 'eat', 'drink', 'help']);
  if (
    ['what', 'where', 'who'].includes(compactWords[0]) &&
    compactWords[1] === 'you' &&
    actionWords.has(compactWords[2])
  ) {
    compactWords.splice(1, 0, 'do');
  } else if (actionWords.has(compactWords[0]) && !['i', 'you'].includes(compactWords[0])) {
    compactWords.unshift('i');
  }

  const sentence = compactWords.join(' ');
  const capitalized = sentence[0].toUpperCase() + sentence.slice(1);
  return `${capitalized}${['what', 'where', 'who'].includes(compactWords[0]) ? '?' : '.'}`;
}

const GesturelinkSignUtils = {
  normalizeGloss,
  buildSignVideoMap,
  resolveDisplayWords,
  encodeVideoPath,
  buildSpokenSentence,
};

if (typeof window !== 'undefined') window.GesturelinkSignUtils = GesturelinkSignUtils;
if (typeof module !== 'undefined') module.exports = GesturelinkSignUtils;
