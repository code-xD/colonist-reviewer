const startButton = document.querySelector("#start");
const stopButton = document.querySelector("#stop");
const statusBox = document.querySelector("#status");
const statusText = document.querySelector("#status-text");
const messageBox = document.querySelector("#message");

let timer = null;
let startedAt = null;

function formatElapsed(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return [hours, minutes, remainder]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

function render(recording, startTime = null) {
  clearInterval(timer);
  timer = null;
  startedAt = startTime;

  startButton.disabled = recording;
  stopButton.disabled = !recording;
  statusBox.classList.toggle("recording", recording);

  if (!recording) {
    statusText.textContent = "Ready to record";
    return;
  }

  const updateElapsed = () => {
    statusText.textContent = `Recording · ${formatElapsed(Date.now() - startedAt)}`;
  };
  updateElapsed();
  timer = setInterval(updateElapsed, 1000);
}

async function send(message) {
  const response = await chrome.runtime.sendMessage(message);
  if (!response?.ok) throw new Error(response?.error || "Recorder request failed.");
  return response;
}

async function refresh() {
  try {
    const state = await send({ type: "GET_STATUS" });
    render(state.recording, state.startedAt);
  } catch (error) {
    messageBox.textContent = error.message;
  }
}

startButton.addEventListener("click", async () => {
  messageBox.textContent = "";
  startButton.disabled = true;

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const result = await send({ type: "START_RECORDING", tab });
    render(true, result.startedAt);
  } catch (error) {
    render(false);
    messageBox.textContent = error.message;
  }
});

stopButton.addEventListener("click", async () => {
  messageBox.textContent = "Saving the final segment…";
  stopButton.disabled = true;

  try {
    await send({ type: "STOP_RECORDING" });
    render(false);
    messageBox.textContent = "Saved to your Downloads folder.";
  } catch (error) {
    messageBox.textContent = error.message;
    await refresh();
  }
});

refresh();
