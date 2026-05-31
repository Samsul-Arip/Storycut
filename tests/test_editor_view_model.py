from __future__ import annotations

import unittest

from app.viewmodels import (
    EditorHistory,
    EditorViewModel,
    TimelineDurationConfig,
    safe_project_filename,
    time_for_filename,
)


class EditorViewModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.view_model = EditorViewModel()

    def test_safe_project_filename_removes_unsafe_characters(self) -> None:
        self.assertEqual(safe_project_filename(" My: Video / Cut "), "My__Video___Cut")
        self.assertEqual(safe_project_filename("   "), "StoryCut_Project")

    def test_time_for_filename_uses_fixed_width_clock_parts(self) -> None:
        self.assertEqual(time_for_filename(3661.4), "01-01-01")

    def test_clip_duration_uses_source_range_by_default(self) -> None:
        clip = {"start": "00:00:05.000", "end": "00:00:12.500"}
        self.assertAlmostEqual(self.view_model.clip_source_duration(clip), 7.5)
        self.assertAlmostEqual(self.view_model.timeline_total_duration([clip]), 7.5)

    def test_clip_duration_respects_slow_motion_and_photo_defaults(self) -> None:
        slow_clip = {"start": 10.0, "end": 14.0, "slowmo_factor": 1.5}
        photo_clip = {"kind": "photo", "image_path": "frame.jpg"}

        self.assertAlmostEqual(self.view_model.clip_output_duration(slow_clip), 6.0)
        self.assertAlmostEqual(self.view_model.clip_output_duration(photo_clip), 3.0)

    def test_rough_timeline_fills_output_durations_from_config(self) -> None:
        clips = [
            {"id": "hook", "kind": "rough", "timeline_role": "hook", "start": 0, "end": 3},
            {"id": "scene", "kind": "rough", "timeline_role": "scene", "start": 5, "end": 8},
        ]
        normalized = self.view_model.timeline_with_output_durations(
            clips,
            TimelineDurationConfig(
                target_final_seconds=9,
                hook_seconds=4,
                scene_output_seconds=12,
                clip_seconds=5,
            ),
        )

        self.assertEqual([item["output_duration"] for item in normalized], [4.0, 5.0])

    def test_history_returns_copied_snapshots_for_undo_and_redo(self) -> None:
        history = EditorHistory(limit=3)
        first = {"manual_clips": [{"id": "a"}], "timeline_clips": []}
        second = {"manual_clips": [{"id": "b"}], "timeline_clips": []}

        history.reset(first)
        history.push(second)
        second["manual_clips"][0]["id"] = "mutated"

        undone = history.undo()
        redone = history.redo()

        self.assertEqual(undone, first)
        self.assertEqual(redone, {"manual_clips": [{"id": "b"}], "timeline_clips": []})


if __name__ == "__main__":
    unittest.main()
