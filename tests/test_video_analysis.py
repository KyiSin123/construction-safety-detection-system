import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from routes import video_analysis


def unknown_identity():
    return SimpleNamespace(to_dict=lambda: {
        'worker_number': None,
        'worker_name': None,
        'team': None,
        'identity_confidence': 0,
        'identity_status': 'pending_review',
        'identity_source': 'test',
        'visible_location': None,
        'raw_response': None,
        'error': None,
    })


def candidate(bbox):
    return {
        'bbox': bbox,
        'missing_ppe': ['helmet'],
        'detected_ppe': [],
        'crop': np.zeros((40, 20, 3), dtype=np.uint8),
        'sharpness': 1,
    }


class BatchAlertTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.log_instance_snapshot.return_value = True
        self.identity_reader = Mock()
        self.identity_reader.identify_worker.side_effect = lambda *_: unknown_identity()
        self.snapshot_manager = Mock()
        self.snapshot_manager.save_snapshot.return_value = 'snapshots/test.jpg'
        self.notification = [{
            'supervisor_id': 1,
            'supervisor_name': 'Supervisor',
            'status': 'sent',
            'error': None,
        }]

    def extension_patches(self):
        return (
            patch.object(video_analysis.extensions, 'db', self.db),
            patch.object(video_analysis.extensions, 'identity_reader', self.identity_reader),
            patch.object(video_analysis.extensions, 'snapshot_manager', self.snapshot_manager),
            patch.object(
                video_analysis.extensions,
                'send_mobile_supervisor_notifications',
                return_value=self.notification,
            ),
        )

    def test_three_unknown_people_in_first_batch_create_three_alerts(self):
        self.db.claim_unknown_alert_batch.return_value = True
        patches = self.extension_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            results = video_analysis._persist_alerts(
                [candidate([0, 0, 20, 40]), candidate([30, 0, 50, 40]),
                 candidate([60, 0, 80, 40])],
                'firstbatch',
            )

        self.assertEqual(['alerted', 'alerted', 'alerted'], [item['status'] for item in results])
        self.assertEqual(3, self.db.log_instance_snapshot.call_count)
        self.assertEqual(1, self.db.claim_unknown_alert_batch.call_count)
        self.db.find_blocking_violation.assert_not_called()

    def test_later_unknown_batch_is_suppressed(self):
        self.db.claim_unknown_alert_batch.return_value = False
        self.db.find_blocking_violation.return_value = 'existing-case'
        patches = self.extension_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            results = video_analysis._persist_alerts(
                [candidate([0, 0, 20, 40])],
                'laterbatch',
            )

        self.assertEqual('duplicate_skipped', results[0]['status'])
        self.assertEqual('existing-case', results[0]['existing_instance_id'])
        self.db.log_instance_snapshot.assert_not_called()

    def test_repeated_video_person_updates_one_track(self):
        tracks = []
        video_analysis._update_tracks(tracks, [candidate([0, 0, 20, 40])], 1, 0.5)
        video_analysis._update_tracks(tracks, [candidate([1, 0, 21, 40])], 2, 1.0)
        video_analysis._update_tracks(tracks, [candidate([2, 0, 22, 40])], 3, 1.5)
        self.assertEqual(1, len(tracks))
        self.assertEqual(1.5, tracks[0]['end_seconds'])

    def test_three_video_people_remain_three_tracks(self):
        tracks = []
        people = [
            candidate([0, 0, 20, 40]),
            candidate([30, 0, 50, 40]),
            candidate([60, 0, 80, 40]),
        ]
        video_analysis._update_tracks(tracks, people, 1, 0.5)
        video_analysis._update_tracks(tracks, people, 2, 1.0)
        self.assertEqual(3, len(tracks))

    def test_ppe_is_evaluated_per_person(self):
        frame = np.zeros((100, 120, 3), dtype=np.uint8)
        detections = [
            {'class': 'person', 'bbox': [0, 0, 50, 100], 'confidence': 1},
            {'class': 'person', 'bbox': [70, 0, 120, 100], 'confidence': 1},
            {'class': 'helmet', 'bbox': [10, 5, 30, 25], 'confidence': 1},
            {'class': 'no-helmet', 'bbox': [80, 5, 105, 25], 'confidence': 1},
        ]
        with patch.object(
            video_analysis.extensions,
            'current_settings',
            {'required_ppe': {'helmet': True, 'vest': False, 'mask': False}},
        ):
            results = video_analysis._person_candidates(frame, detections)

        self.assertEqual([], results[0]['missing_ppe'])
        self.assertEqual(['helmet'], results[1]['missing_ppe'])


if __name__ == '__main__':
    unittest.main()
