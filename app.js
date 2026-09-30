const localVideo = document.querySelector('#localVideo');
const cameraPlaceholder = document.querySelector('#cameraPlaceholder');
const cameraButton = document.querySelector('#cameraButton');
const cameraState = document.querySelector('#cameraState');
const micButton = document.querySelector('#micButton');
const transcriptText = document.querySelector('#transcriptText');
const signTiles = document.querySelector('#signTiles');
const listenButton = document.querySelector('#listenButton');
const speechSupport = document.querySelector('#speechSupport');
const toast = document.querySelector('#toast');
const videoLightbox = document.querySelector('#videoLightbox');
const lightboxVideo = document.querySelector('#lightboxVideo');
const lightboxLabel = document.querySelector('#lightboxLabel');
let cameraStream;
let micOn = false;
let recognition;
let inferenceTimer;
let activeGesture = '';
let missingGestureFrames = 0;
let sentencePauseTimer;
let pendingSpeechSentence = '';
let lastCompletedSentence = '';
let speechRequestId = 0;
let speechStartTimer;
let speechOutputEnabled = false;
let inferenceInProgress = false;
const sentenceSigns = [];
const completedSignPhrases = [];
const SIGN_CONFIDENCE_THRESHOLD = 0.5;
let signVideoMap = new Map();
const frameCanvas = document.createElement('canvas');
const roomUrl = new URL(window.location.href);
const roomId = roomUrl.searchParams.get('room') || Math.random().toString(36).slice(2, 10);
const peerConnections = new Map();
const remoteCards = new Map();
let signalingSocket;
let currentName = 'Participant';
let inCall = false;
let leavingCall = false;
let screenStream;
let cameraTrack;
let resolveConferenceJoin;
let rejectConferenceJoin;

roomUrl.searchParams.set('room', roomId);
window.history.replaceState(null, '', roomUrl);
document.querySelector('#roomCode').textContent = roomId.toUpperCase();

function resolveTextWords(text) {
  return GesturelinkSignUtils.resolveDisplayWords(text, signVideoMap);
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 2600);
}

function addActivity(author, label, message, kind) {
  const item = document.createElement('article');
  item.className = 'activity-item';
  const icon = document.createElement('div');
  icon.className = `activity-icon ${kind}`;
  icon.textContent = author[0] || '?';
  const copy = document.createElement('div');
  copy.className = 'activity-copy';
  const heading = document.createElement('strong');
  heading.textContent = author;
  const tag = document.createElement('span');
  tag.className = `tag ${kind === 'coral' ? 'speech-tag' : 'sign-tag'}`;
  tag.textContent = label;
  heading.append(' ', tag);
  const text = document.createElement('p');
  text.textContent = message;
  copy.append(heading, text);
  const time = document.createElement('time');
  time.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  item.append(icon, copy, time);
  const activityList = document.querySelector('#activityList');
  activityList.querySelector('.activity-empty')?.remove();
  activityList.prepend(item);
}

function updateRoomStatus() {
  if (!inCall) return;
  const connected = [...peerConnections.values()].filter(peer => peer.connectionState === 'connected').length;
  document.querySelector('#roomStatus').textContent = connected
    ? `In call - ${connected + 1} participant${connected === 1 ? '' : 's'}`
    : 'In room · waiting for others';
}

function setConferenceControls(enabled) {
  document.querySelector('#shareButton').disabled = !enabled;
  document.querySelector('#joinCall').hidden = enabled;
  document.querySelector('#leaveRoom').hidden = !enabled;
}

function updateCameraButton() {
  const enabled = cameraTrack?.enabled ?? false;
  cameraButton.textContent = enabled ? 'Camera on' : 'Camera off';
  cameraButton.classList.toggle('on', enabled);
  cameraButton.setAttribute('aria-label', enabled ? 'Turn camera off' : 'Turn camera on');
  cameraState.textContent = enabled ? 'Camera on' : 'Camera off';
}

async function ensureLocalMedia() {
  if (cameraStream) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.isSecureContext) {
    throw new Error('Camera and microphone need a secure HTTPS link on your phone.');
  }
  cameraStream = await navigator.mediaDevices.getUserMedia({
    audio: true,
    video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
  });
  cameraTrack = cameraStream.getVideoTracks()[0];
  micOn = cameraStream.getAudioTracks()[0]?.enabled ?? false;
  setLocalVideoStream(cameraStream);
  updateCameraButton();
  startInferencePreview();
  micButton.textContent = micOn ? 'Mic on' : 'Mic muted';
  micButton.classList.toggle('on', micOn);
  micButton.setAttribute('aria-label', micOn ? 'Mute microphone' : 'Unmute microphone');
}

cameraButton.addEventListener('click', async () => {
  try {
    if (!cameraStream) {
      await ensureLocalMedia();
      return;
    }
    if (!cameraTrack) return;
    cameraTrack.enabled = !cameraTrack.enabled;
    updateCameraButton();
  } catch (error) {
    showToast(error.message || 'Could not access the camera and microphone.');
  }
});

micButton.addEventListener('click', async () => {
  try {
    if (!cameraStream) {
      await ensureLocalMedia();
      return;
    }
    const audioTrack = cameraStream.getAudioTracks()[0];
    if (!audioTrack) return;
    audioTrack.enabled = !audioTrack.enabled;
    micOn = audioTrack.enabled;
    micButton.textContent = micOn ? 'Mic on' : 'Mic muted';
    micButton.classList.toggle('on', micOn);
    micButton.setAttribute('aria-label', micOn ? 'Mute microphone' : 'Unmute microphone');
  } catch (error) {
    showToast(error.message || 'Could not access the camera and microphone.');
  }
});

function setLocalVideoStream(stream) {
  localVideo.srcObject = stream;
  localVideo.style.display = 'block';
  cameraPlaceholder.style.display = 'none';
  localVideo.play().catch(() => {});
}

function ensureRemoteCard(peer) {
  if (remoteCards.has(peer.id)) return remoteCards.get(peer.id);
  const card = document.createElement('article');
  card.className = 'video-card remote-card';
  const header = document.createElement('div');
  header.className = 'video-header';
  const identity = document.createElement('div');
  const live = document.createElement('span');
  live.className = 'live-pill';
  live.textContent = 'LIVE';
  const name = document.createElement('span');
  name.className = 'video-name';
  name.textContent = peer.name;
  identity.append(live, name);
  const role = document.createElement('span');
  role.className = 'video-role';
  role.textContent = 'Participant';
  header.append(identity, role);
  const stage = document.createElement('div');
  stage.className = 'remote-stage';
  const video = document.createElement('video');
  video.autoplay = true;
  video.playsInline = true;
  const overlay = document.createElement('div');
  overlay.className = 'video-overlay';
  const state = document.createElement('span');
  state.textContent = 'Connecting';
  const quality = document.createElement('span');
  quality.textContent = 'LIVE';
  overlay.append(state, quality);
  stage.append(video, overlay);
  card.append(header, stage);
  document.querySelector('#remoteParticipants').append(card);
  const remoteEmpty = document.querySelector('.remote-empty');
  if (remoteEmpty) remoteEmpty.remove();
  remoteCards.set(peer.id, { card, video, state });
  return remoteCards.get(peer.id);
}

function ensurePeerConnection(peer, shouldOffer) {
  if (peerConnections.has(peer.id)) return peerConnections.get(peer.id);
  const card = ensureRemoteCard(peer);
  const connection = new RTCPeerConnection({
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
  });
  cameraStream.getTracks().forEach(track => {
    if (track.kind === 'video' && screenStream) connection.addTrack(screenStream.getVideoTracks()[0], screenStream);
    else connection.addTrack(track, cameraStream);
  });
  connection.ontrack = event => {
    card.video.srcObject = event.streams[0] || new MediaStream([event.track]);
    card.video.play().catch(() => {});
  };
  connection.onconnectionstatechange = () => {
    card.state.textContent = connection.connectionState;
    updateRoomStatus();
    if (connection.connectionState === 'failed') {
      showToast(`Could not connect to ${peer.name}. Try the same Wi-Fi network.`);
    }
  };
  peerConnections.set(peer.id, connection);
  updateRoomStatus();
  if (shouldOffer) createAndSendOffer(peer.id, connection);
  return connection;
}

function sendSignal(peerId, signal) {
  if (signalingSocket?.readyState !== WebSocket.OPEN) {
    throw new Error('Conference signaling is disconnected.');
  }
  signalingSocket.send(JSON.stringify({ to: peerId, signal }));
}

function waitForIceGathering(connection) {
  if (connection.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise(resolve => {
    const timeout = window.setTimeout(finish, 10000);
    function finish() {
      window.clearTimeout(timeout);
      connection.removeEventListener('icegatheringstatechange', onStateChange);
      resolve();
    }
    function onStateChange() {
      if (connection.iceGatheringState === 'complete') finish();
    }
    connection.addEventListener('icegatheringstatechange', onStateChange);
  });
}

async function createAndSendOffer(peerId, connection) {
  try {
    await connection.setLocalDescription(await connection.createOffer());
    await waitForIceGathering(connection);
    sendSignal(peerId, { type: connection.localDescription.type, sdp: connection.localDescription.sdp });
  } catch (error) {
    showToast(error.message || 'Could not start the video connection.');
  }
}

async function handleConferenceMessage(message) {
  if (message.type === 'joined') {
    message.peers.forEach(peer => ensurePeerConnection(peer, false));
    resolveConferenceJoin?.();
    resolveConferenceJoin = null;
    rejectConferenceJoin = null;
    updateRoomStatus();
    return;
  }
  if (message.type === 'peer-joined') {
    ensurePeerConnection(message.peer, true);
    addActivity(message.peer.name, 'JOINED', 'Joined the conference', 'teal');
    return;
  }
  if (message.type === 'peer-left') {
    closePeerConnection(message.peerId);
    addActivity('Gesturelink', 'LEFT', 'A participant left the conference', 'teal');
    updateRoomStatus();
    return;
  }
  if (message.type !== 'signal') return;
  const connection = ensurePeerConnection({ id: message.from, name: message.name }, false);
  const remoteDescription = new RTCSessionDescription(message.signal);
  await connection.setRemoteDescription(remoteDescription);
  if (remoteDescription.type === 'offer') {
    await connection.setLocalDescription(await connection.createAnswer());
    await waitForIceGathering(connection);
    sendSignal(message.from, {
      type: connection.localDescription.type,
      sdp: connection.localDescription.sdp,
    });
  }
}

function closePeerConnection(peerId) {
  peerConnections.get(peerId)?.close();
  peerConnections.delete(peerId);
  remoteCards.get(peerId)?.card.remove();
  remoteCards.delete(peerId);
  if (!remoteCards.size) {
    const empty = document.createElement('p');
    empty.className = 'remote-empty';
    empty.textContent = 'Share the invite link to bring others into this room.';
    document.querySelector('#remoteParticipants').append(empty);
  }
}

async function joinConference() {
  if (!navigator.mediaDevices?.getUserMedia || !window.isSecureContext) {
    showToast('Camera and microphone need a secure HTTPS link on your phone.');
    return;
  }
  const joinButton = document.querySelector('#joinCall');
  currentName = document.querySelector('#displayName').value.trim().slice(0, 30) || 'Participant';
  document.querySelector('#localName').textContent = currentName;
  document.querySelector('#profileName').textContent = currentName;
  joinButton.disabled = true;
  joinButton.textContent = 'Joining...';
  try {
    await ensureLocalMedia();
    setConferenceControls(true);
    inCall = true;
    document.querySelector('#roomStatus').textContent = 'Connecting...';
    startInferencePreview();

    const socketUrl = new URL(window.location.href);
    socketUrl.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socketUrl.pathname = `/signal/${encodeURIComponent(roomId)}`;
    socketUrl.search = new URLSearchParams({ name: currentName }).toString();
    const socket = new WebSocket(socketUrl);
    signalingSocket = socket;
    await new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('Conference server did not respond.')), 12000);
      resolveConferenceJoin = () => {
        window.clearTimeout(timeout);
        resolve();
      };
      rejectConferenceJoin = error => {
        window.clearTimeout(timeout);
        reject(error);
      };
      socket.onopen = () => {
        document.querySelector('#roomStatus').textContent = 'Connected - waiting for participants';
      };
      socket.onmessage = event => {
        handleConferenceMessage(JSON.parse(event.data)).catch(error => {
          showToast(error.message || 'Could not update the conference connection.');
        });
      };
      socket.onerror = () => rejectConferenceJoin?.(new Error('Could not connect to the conference server.'));
      socket.onclose = () => {
        if (leavingCall || signalingSocket !== socket) return;
        if (!inCall) {
          rejectConferenceJoin?.(new Error('Conference connection closed.'));
          return;
        }
        if (resolveConferenceJoin) {
          rejectConferenceJoin?.(new Error('Conference connection closed.'));
          return;
        }
        endConference(false);
        showToast('The conference connection ended.');
      };
    });
    setConferenceControls(true);
  } catch (error) {
    endConference(false);
    showToast(error.message || 'Could not join the conference.');
  } finally {
    joinButton.disabled = false;
    joinButton.textContent = 'Join conference';
  }
}

function endConference(closeSocket = true) {
  leavingCall = true;
  rejectConferenceJoin?.(new Error('You left the conference.'));
  if (closeSocket && signalingSocket && signalingSocket.readyState < WebSocket.CLOSING) {
    signalingSocket.close(1000, 'Participant left');
  }
  signalingSocket = null;
  resolveConferenceJoin = null;
  rejectConferenceJoin = null;
  inCall = false;
  window.clearInterval(inferenceTimer);
  if (screenStream) {
    screenStream.getTracks().forEach(track => {
      track.onended = null;
      track.stop();
    });
    screenStream = null;
  }
  peerConnections.forEach(connection => connection.close());
  peerConnections.clear();
  remoteCards.clear();
  document.querySelector('#remoteParticipants').replaceChildren();
  const empty = document.createElement('p');
  empty.className = 'remote-empty';
  empty.textContent = 'Share the invite link to bring others into this room.';
  document.querySelector('#remoteParticipants').append(empty);
  cameraStream?.getTracks().forEach(track => track.stop());
  cameraStream = null;
  cameraTrack = null;
  micOn = false;
  localVideo.srcObject = null;
  localVideo.style.display = 'none';
  cameraPlaceholder.style.display = 'flex';
  cameraPlaceholder.querySelector('strong').textContent = 'Not in the call';
  cameraPlaceholder.querySelector('small').textContent = 'Select Camera to enable your camera and microphone, or join the conference';
  cameraButton.textContent = 'Camera off';
  cameraButton.classList.remove('on');
  micButton.textContent = 'Mic off';
  micButton.classList.remove('on');
  const shareButton = document.querySelector('#shareButton');
  shareButton.textContent = 'Share screen';
  shareButton.classList.remove('on');
  cameraState.textContent = 'Camera off';
  document.querySelector('#roomStatus').textContent = 'Not connected';
  setConferenceControls(false);
  leavingCall = false;
}

document.querySelector('#joinCall').addEventListener('click', joinConference);
document.querySelector('#leaveRoom').addEventListener('click', () => endConference());
document.querySelector('#displayName').addEventListener('input', event => {
  if (!inCall) {
    document.querySelector('#localName').textContent = event.target.value.trim() || 'Participant';
    document.querySelector('#profileName').textContent = event.target.value.trim() || 'Participant';
  }
});

document.querySelector('#shareButton').addEventListener('click', async () => {
  const shareButton = document.querySelector('#shareButton');
  if (screenStream) {
    screenStream.getTracks().forEach(track => track.stop());
    return;
  }
  if (!navigator.mediaDevices?.getDisplayMedia) {
    showToast('Screen sharing is not supported in this browser.');
    return;
  }
  try {
    screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
    const screenTrack = screenStream.getVideoTracks()[0];
    const senders = [...peerConnections.values()]
      .map(connection => connection.getSenders().find(sender => sender.track?.kind === 'video'))
      .filter(Boolean);
    await Promise.all(senders.map(sender => sender.replaceTrack(screenTrack)));
    setLocalVideoStream(screenStream);
    shareButton.textContent = 'Stop sharing';
    shareButton.classList.add('on');
    screenTrack.onended = () => {
      const stream = cameraStream;
      const cameraSenders = [...peerConnections.values()]
        .map(connection => connection.getSenders().find(sender => sender.track?.kind === 'video'))
        .filter(Boolean);
      Promise.all(cameraSenders.map(sender => sender.replaceTrack(cameraTrack))).then(() => {
        screenStream = null;
        shareButton.textContent = 'Share screen';
        shareButton.classList.remove('on');
        if (stream) setLocalVideoStream(stream);
      });
    };
  } catch (error) {
    screenStream?.getTracks().forEach(track => {
      track.onended = null;
      track.stop();
    });
    screenStream = null;
    showToast(error.message || 'Screen sharing was cancelled.');
  }
});

function renderSentencePreview() {
  document.querySelector('#sentencePreview').textContent = sentenceSigns.length
    ? GesturelinkSignUtils.buildSpokenSentence(sentenceSigns)
    : lastCompletedSentence || 'Your signs will build a sentence here.';
  const recognizedText = [
    ...completedSignPhrases,
    sentenceSigns.join(' '),
  ].filter(Boolean).join('. ');
  document.querySelector('#recognizedWords').textContent = recognizedText
    ? `${recognizedText}${completedSignPhrases.length && !sentenceSigns.length ? '.' : ''}`
    : 'Recognized signs will appear here as you sign.';
  document.querySelector('#speakButton').disabled = sentenceSigns.length === 0 && !pendingSpeechSentence;
}

function scheduleSentencePause() {
  window.clearTimeout(sentencePauseTimer);
  if (sentenceSigns.length) {
    sentencePauseTimer = window.setTimeout(finishSignSentence, 5000);
  }
}

function addSignToSentence(label) {
  const normalizedLabel = GesturelinkSignUtils.normalizeGloss(label);
  if (!normalizedLabel) return;
  activeGesture = normalizedLabel;
  sentenceSigns.push(normalizedLabel);
  renderSentencePreview();
  document.querySelector('#sentenceStatus').textContent = 'Signing... pause briefly to speak the whole sentence.';
  scheduleSentencePause();
  speakRecognizedSign(normalizedLabel);
}

function speakRecognizedSign(label) {
  if (!speechOutputEnabled || !('speechSynthesis' in window)) return;
  const utterance = new SpeechSynthesisUtterance(label);
  utterance.lang = 'en-US';
  utterance.onerror = event => {
    document.querySelector('#sentenceStatus').textContent = `Word detected, but speech failed (${event.error}).`;
  };
  window.speechSynthesis.speak(utterance);
}

function speakSentence(sentence, fromUserGesture = false) {
  if (!('speechSynthesis' in window)) {
    document.querySelector('#sentenceStatus').textContent = 'Speech output is not supported in this browser.';
    return;
  }
  if (!speechOutputEnabled && !fromUserGesture) {
    document.querySelector('#sentenceStatus').textContent = 'Sentence ready. Tap Enable speech once to allow automatic voice output.';
    return;
  }
  if (fromUserGesture) speechOutputEnabled = true;

  const requestId = ++speechRequestId;
  const button = document.querySelector('#speakButton');
  const isPendingSentence = sentence === pendingSpeechSentence;
  const utterance = new SpeechSynthesisUtterance(sentence);
  utterance.lang = 'en-US';
  utterance.onstart = () => {
    if (requestId !== speechRequestId) return;
    window.clearTimeout(speechStartTimer);
    speechOutputEnabled = true;
    document.querySelector('#sentenceStatus').textContent = 'Speaking sentence...';
    button.disabled = true;
    button.textContent = 'Speaking...';
  };
  utterance.onend = () => {
    if (requestId !== speechRequestId) return;
    window.clearTimeout(speechStartTimer);
    if (isPendingSentence) pendingSpeechSentence = '';
    document.querySelector('#sentenceStatus').textContent = isPendingSentence
      ? 'Sentence spoken.'
      : 'Speech enabled. Sign when ready.';
    document.querySelector('#enableSpeechButton').textContent = 'Speech enabled';
    button.disabled = sentenceSigns.length === 0 && !pendingSpeechSentence;
    button.textContent = 'Speak sentence';
  };
  utterance.onerror = event => {
    if (requestId !== speechRequestId) return;
    window.clearTimeout(speechStartTimer);
    document.querySelector('#sentenceStatus').textContent = pendingSpeechSentence
      ? `Speech failed (${event.error}). Select “Try speech again”.`
      : `Speech setup failed (${event.error}). Tap Enable speech to retry.`;
    button.disabled = !pendingSpeechSentence;
    button.textContent = pendingSpeechSentence ? 'Try speech again' : 'Speak sentence';
    document.querySelector('#enableSpeechButton').textContent = 'Enable speech';
    speechOutputEnabled = false;
  };

  window.speechSynthesis.resume();
  window.speechSynthesis.speak(utterance);
  document.querySelector('#sentenceStatus').textContent = 'Sending sentence to speech output...';
  button.disabled = true;
  button.textContent = 'Speaking...';
  window.clearTimeout(speechStartTimer);
  speechStartTimer = window.setTimeout(() => {
    if (requestId !== speechRequestId) return;
    document.querySelector('#sentenceStatus').textContent = pendingSpeechSentence
      ? 'No audio started. Check device volume, then select Try speech again.'
      : 'Speech did not start. Tap Enable speech to retry.';
    button.disabled = !pendingSpeechSentence;
    button.textContent = pendingSpeechSentence ? 'Try speech again' : 'Speak sentence';
    document.querySelector('#enableSpeechButton').textContent = 'Enable speech';
    speechOutputEnabled = false;
  }, 8000);
}

function finishSignSentence() {
  window.clearTimeout(sentencePauseTimer);
  sentencePauseTimer = undefined;
  const sentence = GesturelinkSignUtils.buildSpokenSentence(sentenceSigns);
  if (!sentence) return;

  completedSignPhrases.push(sentenceSigns.join(' '));
  sentenceSigns.length = 0;
  lastCompletedSentence = sentence;
  pendingSpeechSentence = sentence;
  renderSentencePreview();
  addActivity('You', 'SENTENCE', sentence, 'teal');
  document.querySelector('#sentenceStatus').textContent =
    'Sentence ready. Detected words were spoken individually; select Speak sentence to hear them together.';
}

function startInferencePreview() {
  window.clearInterval(inferenceTimer);
  inferenceTimer = window.setInterval(async () => {
    const status = document.querySelector('#signRecognitionStatus');
    if (document.querySelector('#signView').classList.contains('hidden')) return;
    if (!localVideo.videoWidth || !cameraTrack?.enabled) {
      status.textContent = 'Turn on your camera to recognize signs.';
      return;
    }
    if (inferenceInProgress) return;
    inferenceInProgress = true;
    frameCanvas.width = 320;
    frameCanvas.height = 240;
    frameCanvas.getContext('2d').drawImage(localVideo, 0, 0, 320, 240);
    try {
      const response = await fetch('/infer-posture', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: frameCanvas.toDataURL('image/jpeg', 0.65) })
      });
      if (!response.ok) throw new Error(`Recognizer returned HTTP ${response.status}.`);
      const result = await response.json();
      if (result.label && result.confidence >= SIGN_CONFIDENCE_THRESHOLD) {
        missingGestureFrames = 0;
        status.textContent = `Recognizing signs in real time. Latest: ${result.label} (${Math.round(result.confidence * 100)}%).`;
        document.querySelector('#gestureLabel').textContent = result.label;
        document.querySelector('.gesture-symbol').textContent = result.label[0];
        const label = GesturelinkSignUtils.normalizeGloss(result.label);
        if (label && label !== activeGesture) {
          addSignToSentence(label);
        }
      } else {
        missingGestureFrames++;
        if (missingGestureFrames >= 2) activeGesture = '';
        status.textContent = result.landmarks_found
          ? 'Hand found, but no sign passed the confidence threshold.'
          : 'No hand detected. Keep your hands visible in the camera.';
      }
    } catch (error) {
      status.textContent = `Sign recognition unavailable: ${error.message}`;
    } finally {
      inferenceInProgress = false;
    }

  }, 400);
}

document.querySelector('#copyInvite').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(window.location.href);
    showToast('Conference invite copied');
  } catch {
    window.prompt('Copy this conference invite:', window.location.href);
  }
});

document.querySelectorAll('.mode').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.mode').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  document.querySelector('#speechView').classList.toggle('hidden', button.dataset.mode !== 'speech');
  document.querySelector('#signView').classList.toggle('hidden', button.dataset.mode !== 'sign');
}));

function escapeHtml(value) {
  return value.replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]);
}

function renderSigns(text) {
  const words = resolveTextWords(text);
  if (!words.length) {
    signTiles.innerHTML = '<div class="sign-tile"><span>NO MATCHING SIGNS</span><strong>No sign videos are available for these words.</strong></div>';
    return;
  }
  signTiles.innerHTML = words.map(gloss => {
    const video = signVideoMap.get(gloss);
    const label = escapeHtml(gloss.toUpperCase());
    return `<div class="sign-tile"><span>${label}</span><video src="${video}" autoplay loop muted playsinline controls preload="metadata" aria-label="ASL sign for ${label}"></video><small class="video-playback-status" aria-live="polite"></small></div>`;
  }).join('');
  signTiles.querySelectorAll('video').forEach(video => {
    video.play().catch(() => {
      video.parentElement.querySelector('.video-playback-status').textContent = 'Select play to view this sign.';
    });
  });
}

signTiles.addEventListener('error', event => {
  if (event.target.tagName !== 'VIDEO') return;
  const unavailable = document.createElement('strong');
  unavailable.className = 'video-unavailable';
  unavailable.textContent = 'This sign video could not be played.';
  event.target.replaceWith(unavailable);
}, true);

signTiles.addEventListener('click', event => {
  if (event.target.tagName !== 'VIDEO') return;
  lightboxVideo.src = event.target.currentSrc || event.target.src;
  lightboxLabel.textContent = event.target.getAttribute('aria-label') || 'Sign language video';
  videoLightbox.hidden = false;
  lightboxVideo.play().catch(() => {});
});
document.querySelector('#closeLightbox').addEventListener('click', () => {
  videoLightbox.hidden = true;
  lightboxVideo.pause();
  lightboxVideo.removeAttribute('src');
});
videoLightbox.addEventListener('click', event => {
  if (event.target === videoLightbox) document.querySelector('#closeLightbox').click();
});

async function loadSignVideos() {
  try {
    const response = await fetch('/dataset/sign-videos', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Sign video list request failed (${response.status}).`);
    const samples = await response.json();
    signVideoMap = GesturelinkSignUtils.buildSignVideoMap(samples);
    renderSigns(transcriptText.textContent);
  } catch (error) {
    showToast(error.message || 'Sign videos are unavailable until the dataset is loaded.');
  }
}

function updateTranscript(text) {
  transcriptText.textContent = text;
  renderSigns(text);
  addActivity('Gesturelink', 'SIGN OUTPUT', text, 'teal');
}

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
loadSignVideos();
if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = 'en-US';
  recognition.onstart = () => {
    listenButton.innerHTML = 'Listening continuously <span>||</span>';
    listenButton.classList.add('on');
  };
  recognition.onend = () => {
    if (listenButton.classList.contains('on')) {
      try { recognition.start(); } catch {}
      return;
    }
    listenButton.innerHTML = 'Start listening <span>-></span>';
  };
  recognition.onresult = event => {
    let text = '';
    for (let index = 0; index < event.results.length; index++) {
      text += event.results[index][0].transcript + ' ';
    }
    text = text.trim();
    transcriptText.textContent = text;
    renderSigns(text);
    if (event.results[event.results.length - 1].isFinal) addActivity('You', 'SPEECH', text, 'coral');
  };
  recognition.onerror = () => showToast('Speech recognition could not hear that.');
} else {
  speechSupport.textContent = 'Demo mode: press the button to load a sample transcript.';
}

function startSpeechRecognition() {
  if (!recognition) return;
  try { recognition.start(); } catch {}
}

function stopSpeechRecognition() {
  if (!recognition) return;
  listenButton.classList.remove('on');
  recognition.stop();
}

listenButton.addEventListener('click', () => {
  if (recognition) {
    if (listenButton.classList.contains('on')) {
      stopSpeechRecognition();
    } else {
      startSpeechRecognition();
    }
  } else {
    updateTranscript('Can everyone see my signs clearly?');
    showToast('Demo transcript added');
  }
});

document.querySelectorAll('[data-gesture]').forEach(button => button.addEventListener('click', () => {
  const label = button.dataset.gesture;
  document.querySelector('#gestureLabel').textContent = label;
  document.querySelector('.gesture-symbol').textContent = label[0];
  addSignToSentence(label);
}));
document.querySelector('#speakButton').addEventListener('click', () => {
  if (pendingSpeechSentence) {
    speakSentence(pendingSpeechSentence, true);
  } else {
    if (sentenceSigns.length) {
      finishSignSentence();
    } else {
      document.querySelector('#sentenceStatus').textContent = 'No recognized words to speak yet. Keep your hand visible and check the recognition status.';
    }
  }
});
document.querySelector('#enableSpeechButton').addEventListener('click', () => {
  speakSentence('Speech output is ready.', true);
});
document.querySelector('#clearSentence').addEventListener('click', () => {
  window.clearTimeout(sentencePauseTimer);
  sentenceSigns.length = 0;
  completedSignPhrases.length = 0;
  lastCompletedSentence = '';
  pendingSpeechSentence = '';
  activeGesture = '';
  missingGestureFrames = 0;
  speechRequestId++;
  window.speechSynthesis?.cancel();
  document.querySelector('#speakButton').textContent = 'Speak sentence';
  document.querySelector('#sentenceStatus').textContent = 'Sentence cleared.';
  renderSentencePreview();
});
renderSentencePreview();
document.querySelector('#clearActivity').addEventListener('click', () => {
  document.querySelector('#activityList').innerHTML = '';
  showToast('Conversation history cleared');
});
