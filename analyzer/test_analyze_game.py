import unittest

from analyze_game import stabilize_snapshots


PLAYER = {
    "username": "Goines8463",
    "color": "red",
    "public_points": 2,
    "resource_count": 3,
}
TILES = [
    {"tile_index": index, "resource": "wood", "dice_number": 5}
    for index in range(19)
]
BUILDING = {
    "corner_index": 0,
    "owner": "Goines8463",
    "color": "red",
    "kind": "settlement",
}


def snapshot(timestamp, roads):
    return {
        "timestamp_seconds": timestamp,
        "active_player": "Goines8463",
        "players": [PLAYER],
        "tiles": TILES,
        "roads": roads,
        "buildings": [BUILDING],
        "robber_tile_index": 0,
        "confidence": 0.9,
    }


def road(edge_index):
    return {
        "edge_index": edge_index,
        "owner": "Goines8463",
        "color": "red",
    }


class StabilizeSnapshotsTest(unittest.TestCase):
    def test_rejects_a_single_frame_road(self):
        result = stabilize_snapshots(
            [
                snapshot(0, [road(0), road(71)]),
                snapshot(4, [road(0)]),
                snapshot(8, [road(0)]),
            ]
        )

        self.assertEqual([item["edge_index"] for item in result[-1]["roads"]], [0])

    def test_rejects_a_repeated_disconnected_road(self):
        result = stabilize_snapshots(
            [
                snapshot(0, [road(0), road(71)]),
                snapshot(4, [road(0), road(71)]),
                snapshot(8, [road(0), road(71)]),
            ]
        )

        self.assertEqual([item["edge_index"] for item in result[-1]["roads"]], [0])


if __name__ == "__main__":
    unittest.main()
