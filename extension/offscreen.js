const SEGMENT_DURATION_MS = 30 * 60 * 1000;
const VIDEO_BITS_PER_SECOND = 1_200_000;

let mediaStream = null;
let mediaRecorder = null;
let chunks = [];
let recordingStartedAt = null;
let sessionStamp = null;
let segmentNumber = 0;
let segmentTimer = null;
let stoppingSession = false;

function preferredMimeType() {
  const choices = [
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ];
  return choices.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function timestampForFilename(date = new Date()) {
  return date.toISOString().replace(/[:.]/g, "-");
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.hidden = true;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function startSegment() {
  chunks = [];
  segmentNumber += 1;

  const mimeType = preferredMimeType();
  mediaRecorder = new MediaRecorder(mediaStream, {
    ...(mimeType ? { mimeType } : {}),
    videoBitsPerSecond: VIDEO_BITS_PER_SECOND,
  });

  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data?.size) chunks.push(event.data);
  });

  mediaRecorder.addEventListener("stop", () => {
    const completedChunks = chunks;
    chunks = [];

    if (completedChunks.length > 0) {
      const blob = new Blob(completedChunks, {
        type: mediaRecorder.mimeType || "video/webm",
      });
      const part = String(segmentNumber).padStart(2, "0");
      downloadBlob(blob, `colonist-review-${sessionStamp}-part-${part}.webm`);
    }

    if (!stoppingSession && mediaStream?.active) {
      startSegment();
    } else {
      finishSession();
    }
  });

  mediaRecorder.start(1000);
  clearTimeout(segmentTimer);
  segmentTimer = setTimeout(() => {
    if (mediaRecorder?.state === "recording") mediaRecorder.stop();
  }, SEGMENT_DURATION_MS);
}

function finishSession() {
  clearTimeout(segmentTimer);
  segmentTimer = null;

  if (mediaStream) {
    for (const track of mediaStream.getTracks()) track.stop();
  }

  mediaStream = null;
  mediaRecorder = null;
  chunks = [];
  recordingStartedAt = null;
  sessionStamp = null;
  segmentNumber = 0;
  stoppingSession = false;

  chrome.runtime.sendMessage({ type: "RECORDING_ENDED" }).catch(() => {});
}

async function startRecording(streamId) {
  if (mediaStream?.active) {
    throw new Error("A recording is already in progress.");
  }

  stoppingSession = false;
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
        maxWidth: 1920,
        maxHeight: 1080,
        maxFrameRate: 24,
      },
    },
  });

  const videoTrack = mediaStream.getVideoTracks()[0];
  videoTrack.addEventListener("ended", () => {
    if (!stoppingSession) stopRecording();
  });

  recordingStartedAt = Date.now();
  sessionStamp = timestampForFilename();
  segmentNumber = 0;
  startSegment();

  return { recording: true, startedAt: recordingStartedAt };
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") {
    finishSession();
    return { recording: false };
  }

  stoppingSession = true;
  clearTimeout(segmentTimer);
  mediaRecorder.stop();
  return { recording: false, saving: true };
}

function status() {
  return {
    recording: Boolean(mediaStream?.active && mediaRecorder?.state === "recording"),
    startedAt: recordingStartedAt,
    segment: segmentNumber,
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== "offscreen") return undefined;

  const handle = async () => {
    switch (message.type) {
      case "START_RECORDING":
        return startRecording(message.streamId);
      case "STOP_RECORDING":
        return stopRecording();
      case "GET_STATUS":
        return status();
      default:
        throw new Error("Unknown offscreen command.");
    }
  };

  handle()
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) => {
      finishSession();
      sendResponse({ ok: false, error: error.message });
    });

  return true;
});
