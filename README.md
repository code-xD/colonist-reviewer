# Colonist Review Recorder

A deliberately passive Chrome extension for recording the **visible pixels** of a
Colonist.io tab so you can review your own decisions after a match.

Unlike ColonyHistorian, this recorder does not replace `window.WebSocket`, inspect
game packets, inject scripts into Colonist, or request access to the Colonist site.
It uses Chrome's user-initiated tab capture API and saves local `.webm` files.

## Install

1. Open `chrome://extensions` in Chrome.
2. Enable **Developer mode**.
3. Click **Load unpacked** and select the `extension` folder.
4. Open `https://colonist.io`, click the extension, and choose **Start recording**.
5. After the game, click **Stop & save**. Open the downloaded `.webm` file in
   Chrome, VLC, or another video player.

Chrome 116 or newer is required.

## How it behaves

- Recording starts only after an explicit click in the extension popup.
- Only a `colonist.io` tab can be started.
- Capture is video-only; it does not mute or reroute game audio.
- Long recordings are saved in 30-minute parts to limit memory use.
- A red `REC` badge remains on the extension icon while capture is active.
- Closing the recorded tab stops and saves the current segment.
- All processing is local. There is no analytics, server, upload, or account access.

## Fair-play boundary

This tool is intended for post-game review. It does not provide live advice, infer
cards, expose hidden information, or automate gameplay. Colonist's current
community guidelines prohibit extensions or third-party tools that play for a user
or show hidden information. If Colonist staff interpret recording more broadly,
follow their ruling and disable the extension for ranked play.

## Privacy

The recording contains everything visibly rendered inside the captured tab,
including chat and usernames. Review before sharing it. Files stay in Chrome's
configured Downloads location unless you move or upload them yourself.

## Development checks

```sh
node --check extension/background.js
node --check extension/offscreen.js
node --check extension/popup.js
```

## Optional post-game AI analysis

The standalone [WebM analyzer](analyzer/README.md) can turn completed recordings into
a structured JSON timeline and retrospective suggestions. It is separate from the
extension and runs only when you invoke it after a match.

## Replay and coaching UI

The [frontend](frontend/README.md) is a local-first replay workspace for this
repository's analyzer JSON. It presents timestamped observations, decision
assessments, suggested alternatives, and visual board snapshots when the report
contains them. The report is read inside the browser and is not uploaded.
