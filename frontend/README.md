# Settlement Review

A local-first post-game replay and coaching interface for Colonist recordings.

## Run locally

```sh
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`, then load the JSON produced by the WebM analyzer.

Use the arrow buttons, the timeline slider, or the left and right keyboard arrows
to move through the replay. Uploaded data stays in the browser tab.

Analyzer schema `1.0` reports receive a timeline and coaching review. Schema `1.2`
also includes board snapshots inferred from the sampled recording frames and snapped
to stable tile, corner, and edge indices before rendering.

## Checks

```sh
npm run lint
npm test
```
