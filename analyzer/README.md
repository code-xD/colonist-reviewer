# Post-game WebM analyzer

This standalone script samples completed recorder videos, sends selected screenshots
to a vision-capable OpenAI model, and writes a strict JSON timeline and review. It is
not part of the browser extension and does nothing while a match is running.

## Requirements

- Python 3.10+
- Dependencies: `python3 -m pip install -r analyzer/requirements.txt`
- An OpenAI API key in `analyzer/.env` or the `OPENAI_API_KEY` environment variable

`imageio-ffmpeg` supplies a private FFmpeg binary, so a system-wide FFmpeg install is
optional. If a working system binary is present, the script uses it.

Create the private environment file once:

```sh
cp analyzer/.env.example analyzer/.env
```

Then edit `analyzer/.env` and set `OPENAI_API_KEY` and `COLONIST_USERNAME`. The
username makes the review player-specific. If the username is temporarily unreadable,
the analyzer uses the largest or expanded player container as a lower-confidence cue
for the local player. The real `.env` is ignored by Git; only the empty example is
committed. Existing shell environment variables take precedence over values in the file.

The video frames sent for analysis can contain usernames and chat. API requests set
`store: false`, but you should still review what is visible before processing a file.

## Run

For a single recording:

```sh
python3 analyzer/analyze_game.py ~/Downloads/colonist-review-...-part-01.webm \
  --output ~/Downloads/colonist-review.json
```

For a game split across multiple 30-minute files, pass every part in order:

```sh
python3 analyzer/analyze_game.py \
  ~/Downloads/colonist-review-...-part-01.webm \
  ~/Downloads/colonist-review-...-part-02.webm \
  --output ~/Downloads/colonist-review.json
```

The default model is `gpt-5.6-terra`. Override it with `--model MODEL` or the
`OPENAI_MODEL` environment variable. You can override the configured username for one
run with `--player USERNAME`.

## Test frame extraction without an API key

```sh
python3 analyzer/analyze_game.py recording.webm \
  --extract-only --frames-dir extracted-frames
```

This writes selected JPEGs plus `extracted-frames/frames.json`. No frame is uploaded.

## Cost and accuracy controls

- `--sample-every 4` samples one candidate frame every four seconds.
- `--max-frames 96` caps the total images sent to the model.
- `--batch-size 6` controls images per vision request (maximum 10).
- `--frames-dir DIR` keeps the exact selected evidence frames alongside a normal run.

The selector keeps time coverage and prioritizes visually changed frames. Video-only
analysis cannot perfectly reconstruct quick trades or hidden information, so the JSON
includes confidence scores and limitations. Treat coaching as retrospective guidance,
not as an authoritative game log.
