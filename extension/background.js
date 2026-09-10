const OFFSCREEN_DOCUMENT = "offscreen.html";

let creatingOffscreenDocument = null;

async function ensureOffscreenDocument() {
  const url = chrome.runtime.getURL(OFFSCREEN_DOCUMENT);
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [url],
  });

  if (contexts.length > 0) return;

  if (!creatingOffscreenDocument) {
    creatingOffscreenDocument = chrome.offscreen
      .createDocument({
        url: OFFSCREEN_DOCUMENT,
        reasons: ["USER_MEDIA"],
        justification: "Record the user-selected tab to a local WebM video.",
      })
      .finally(() => {
        creatingOffscreenDocument = null;
      });
  }

  await creatingOffscreenDocument;
}

function isColonistUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return (
      url.protocol === "https:" &&
      (url.hostname === "colonist.io" || url.hostname.endsWith(".colonist.io"))
    );
  } catch {
    return false;
  }
}

async function getStatus() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [chrome.runtime.getURL(OFFSCREEN_DOCUMENT)],
  });

  if (contexts.length === 0) {
    return { recording: false };
  }

  return chrome.runtime.sendMessage({
    target: "offscreen",
    type: "GET_STATUS",
  });
}

async function startRecording(tab) {
  if (!tab?.id || !isColonistUrl(tab.url)) {
    throw new Error("Open a Colonist.io tab before starting the recorder.");
  }

  const current = await getStatus();
  if (current.recording) {
    throw new Error("A recording is already in progress.");
  }

  await ensureOffscreenDocument();

  const streamId = await chrome.tabCapture.getMediaStreamId({
    targetTabId: tab.id,
  });

  const result = await chrome.runtime.sendMessage({
    target: "offscreen",
    type: "START_RECORDING",
    streamId,
    tabId: tab.id,
  });

  if (!result?.ok) {
    throw new Error(result?.error || "Chrome could not start the recording.");
  }

  await chrome.action.setBadgeBackgroundColor({ color: "#c73e1d" });
  await chrome.action.setBadgeText({ text: "REC" });
  return result;
}

async function stopRecording() {
  const result = await chrome.runtime.sendMessage({
    target: "offscreen",
    type: "STOP_RECORDING",
  });

  await chrome.action.setBadgeText({ text: "" });
  return result;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target === "offscreen") return undefined;

  const handle = async () => {
    switch (message.type) {
      case "START_RECORDING":
        return startRecording(message.tab);
      case "STOP_RECORDING":
        return stopRecording();
      case "GET_STATUS":
        return getStatus();
      case "RECORDING_ENDED":
        await chrome.action.setBadgeText({ text: "" });
        return { ok: true };
      default:
        throw new Error("Unknown recorder command.");
    }
  };

  handle()
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));

  return true;
});

chrome.runtime.onStartup.addListener(() => {
  chrome.action.setBadgeText({ text: "" });
});
