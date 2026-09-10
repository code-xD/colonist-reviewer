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

const mode = <T,>(values: T[]) => {
  const counts = new Map<T, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1])[0]?.[0];
};

function stabilizeSnapshots(input: VisualSnapshot[]) {
  const snapshots = [...input].sort((a, b) => a.timestamp_seconds - b.timestamp_seconds);
  const tileResources = new Map<number, string>();
  const tileNumbers = new Map<number, number | null>();
  const playerColors = new Map<string, string>();
  const roadOwners = new Map<number, string>();
  const buildingOwners = new Map<number, string>();

  for (let index = 0; index < 19; index += 1) {
    const tiles = snapshots.flatMap((snapshot) => snapshot.tiles.filter((tile) => tile.tile_index === index));
    const resource = mode(tiles.map((tile) => tile.resource));
    const diceNumber = mode(tiles.map((tile) => tile.dice_number));
    if (resource !== undefined) tileResources.set(index, resource);
    if (diceNumber !== undefined) tileNumbers.set(index, diceNumber);
  }
  for (const username of new Set(snapshots.flatMap((snapshot) => snapshot.players.map((player) => player.username)))) {
    const color = mode(snapshots.flatMap((snapshot) => snapshot.players.filter((player) => player.username === username).map((player) => player.color)));
    if (color) playerColors.set(username, color);
  }
  for (let index = 0; index < 72; index += 1) {
    const owner = mode(snapshots.flatMap((snapshot) => snapshot.roads.filter((road) => road.edge_index === index).map((road) => road.owner)));
    if (owner) roadOwners.set(index, owner);
  }
  for (let index = 0; index < 54; index += 1) {
    const owner = mode(snapshots.flatMap((snapshot) => snapshot.buildings.filter((building) => building.corner_index === index).map((building) => building.owner)));
    if (owner) buildingOwners.set(index, owner);
  }

  const roads = new Map<number, VisualRoad>();
  const buildings = new Map<number, VisualBuilding>();
  return snapshots.map((snapshot) => {
    for (const road of snapshot.roads) {
      const owner = roadOwners.get(road.edge_index) ?? road.owner;
      roads.set(road.edge_index, { ...road, owner, color: playerColors.get(owner) ?? road.color });
    }
    for (const building of snapshot.buildings) {
      const owner = buildingOwners.get(building.corner_index) ?? building.owner;
      const previous = buildings.get(building.corner_index);
      buildings.set(building.corner_index, {
        ...building,
        owner,
        color: playerColors.get(owner) ?? building.color,
        kind: previous?.kind === "city" ? "city" : building.kind,
      });
    }
    return {
      ...snapshot,
      players: snapshot.players.map((player) => ({ ...player, color: playerColors.get(player.username) ?? player.color })),
      tiles: snapshot.tiles.map((tile) => ({ ...tile, resource: tileResources.get(tile.tile_index) ?? tile.resource, dice_number: tileNumbers.has(tile.tile_index) ? tileNumbers.get(tile.tile_index)! : tile.dice_number })),
      roads: [...roads.values()],
      buildings: [...buildings.values()],
    };
  });
}

export function parseAnalyzer(input: unknown): AnalyzerReview {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new Error("Analyzer JSON must be an object.");
  }
  const root = input as Record<string, unknown>;
  const review = (root.review ?? root.analysis ?? root) as Record<string, unknown>;
  const timeline = Array.isArray(review.timeline) ? review.timeline : [];
  const decisions = Array.isArray(review.key_decisions) ? review.key_decisions : [];
  const snapshots = stabilizeSnapshots(Array.isArray(root.board_snapshots) ? root.board_snapshots as VisualSnapshot[] : []);
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
