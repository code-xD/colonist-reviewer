export type ReviewMoment = {
  time?: number;
  title: string;
  detail: string;
  rating?: string;
  suggestion?: string;
};

export type VisualPlayer = {
  username: string;
  color: string;
  public_points: number | null;
  resource_count: number | null;
};

export type VisualTile = {
  tile_index: number;
  resource: string;
  dice_number: number | null;
};

export type VisualBuilding = {
  corner_index: number;
  owner: string;
  color: string;
  kind: "settlement" | "city";
};

export type VisualRoad = {
  edge_index: number;
  owner: string;
  color: string;
};

export type VisualSnapshot = {
  timestamp_seconds: number;
  active_player: string;
  players: VisualPlayer[];
  tiles: VisualTile[];
  buildings: VisualBuilding[];
  roads: VisualRoad[];
  robber_tile_index: number | null;
  confidence: number;
};

export type AnalyzerReview = {
  reviewedPlayer?: string;
  moments: ReviewMoment[];
  snapshots: VisualSnapshot[];
};

const clean = (value: unknown) => String(value ?? "").replace(/\s+/g, " ").trim();

const numberValue = (value: unknown, fallback = 0) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

const humanize = (value: unknown) => {
  const text = clean(value).replace(/[_-]+/g, " ");
  return text ? text[0].toUpperCase() + text.slice(1) : "Game event";
};

export function parseAnalyzer(input: unknown): AnalyzerReview {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new Error("Analyzer JSON must be an object.");
  }
  const root = input as Record<string, unknown>;
  const review = (root.review ?? root.analysis ?? root) as Record<string, unknown>;
  const timeline = Array.isArray(review.timeline) ? review.timeline : [];
  const decisions = Array.isArray(review.key_decisions) ? review.key_decisions : [];
  const snapshots = Array.isArray(root.board_snapshots) ? root.board_snapshots as VisualSnapshot[] : [];
  const moments: ReviewMoment[] = timeline.map((item) => {
    const value = item as Record<string, unknown>;
    const time = numberValue(value.timestamp_seconds ?? value.time_seconds ?? value.time, -1);
    const decision = decisions
      .map((candidate) => candidate as Record<string, unknown>)
      .find((candidate) => Math.abs(numberValue(candidate.timestamp_seconds ?? candidate.time, -9999) - time) <= 20);
    return {
      time: time >= 0 ? time : undefined,
      title: humanize(value.action ?? value.event ?? value.title),
      detail: clean(value.observation ?? value.detail ?? value.description),
      rating: decision ? clean(decision.rating ?? decision.classification) || "Review" : undefined,
      suggestion: decision ? clean(decision.suggestion ?? decision.better_action ?? decision.recommendation ?? decision.alternative) : undefined,
    };
  });
  for (const item of decisions) {
    const value = item as Record<string, unknown>;
    const time = numberValue(value.timestamp_seconds ?? value.time, -1);
    if (moments.some((moment) => time >= 0 && moment.time !== undefined && Math.abs(moment.time - time) <= 20)) continue;
    moments.push({
      time: time >= 0 ? time : undefined,
      title: humanize(value.decision ?? value.action ?? value.title ?? "Decision"),
      detail: clean(value.analysis ?? value.reasoning ?? value.detail ?? value.assessment),
      rating: clean(value.rating ?? value.classification) || "Review",
      suggestion: clean(value.suggestion ?? value.better_action ?? value.recommendation ?? value.alternative),
    });
  }
  if (!moments.length && !snapshots.length) {
    throw new Error("No timeline, decisions, or board snapshots were found in this analyzer file.");
  }
  moments.sort((a, b) => (a.time ?? 0) - (b.time ?? 0));
  return {
    reviewedPlayer: clean(root.reviewed_player ?? review.reviewed_player ?? root.player_username) || undefined,
    moments,
    snapshots,
  };
}
