import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi import HTTPException
from backend.vision_common import inside, options, telemetry, server_path, BODY33, capture_settings
from backend.validation import validate


class VisionContractTests(unittest.TestCase):
    def test_capture_settings_preserve_intent_without_creating_work(self):
        for mode in ('manual', 'record', 'live'):
            capture = capture_settings({'mode':mode,'analysis_options':{
                'sample_fps':2,'confidence':.7,'name':'Acabado','operator_id':'operator-test','capture_fps':25}})
            self.assertEqual(capture['mode'], mode)
            self.assertEqual(capture['analysis_options']['operator_id'], 'operator-test')
            self.assertEqual(capture['analysis_options']['sample_fps'], 2)
        for capture in (None, {}, {'mode':'unknown'}, {'mode':'manual','analysis_options':[]},
                        {'mode':'manual','analysis_options':{'capture_fps':float('nan')}},
                        {'mode':'manual','analysis_options':{'sample_fps':26}}):
            with self.subTest(capture=capture), self.assertRaises(HTTPException):
                capture_settings(capture)

    def test_paths_confine_parent_and_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'allowed';root.mkdir()
            (root/'escape').symlink_to(root.parent,target_is_directory=True)
            self.assertEqual(inside(root,'clip.mp4'),root/'clip.mp4')
            for relative in ('../secret','escape/secret','/etc/passwd'):
                with self.assertRaises(HTTPException): inside(root,relative)

    def test_options_reject_nonfinite_or_unbounded_work(self):
        for body in ({'sample_fps':float('nan')},{'sample_fps':26},{'confidence':.1},{'confidence':float('inf')}):
            with self.assertRaises(HTTPException): options(body)
        self.assertEqual(options({}),{'sample_fps':5.,'confidence':.5})

    def test_project_import_root_excludes_credentials_backups_and_runtime(self):
        with tempfile.TemporaryDirectory() as folder, patch('backend.vision_common.PROJECT',Path(folder)):
            self.assertEqual(server_path('project','clip.mp4'),Path(folder)/'clip.mp4')
            for relative in ('.env','.runtime/clip.mp4','data/vision/clip.mp4','backups/clip.mp4'):
                with self.assertRaises(HTTPException): server_path('project',relative)

    def job(self):
        return {'job_id':'vision-test','session_id':'session-test','operator_id':'operator-test',
            'study_id':'study-test','created_at':'2026-10-22T10:00:00.000Z',
            'source_fps':5,'options':{'sample_fps':2,'confidence':.5}}

    def test_wholebody_mapping_preserves_hand_tips_and_missing_eyes(self):
        points=[[float(i),float(i+10)] for i in range(133)]
        payload=telemetry(self.job(),1,.4,points,[.9]*133)
        validate(payload)
        joints=payload['pose']['joints']
        self.assertEqual(joints['left_index']['image_xy_px'],points[99])
        self.assertEqual(joints['right_index']['image_xy_px'],points[120])
        self.assertEqual(joints['left_eye_inner']['status'],'missing')
        self.assertTrue(all(j['point_3d_m'] is None for j in joints.values()))
        self.assertEqual(payload['frame']['capture_fps'],5)
        self.assertEqual(payload['pose']['observed_at'],'2026-10-22T10:00:00.400Z')
        self.assertIsNone(payload['robot'])

    def test_no_person_or_occluded_hands_never_fabricates_points(self):
        payload=telemetry(self.job(),0,0,[],[])
        validate(payload)
        self.assertTrue(all(j['status']=='missing' for j in payload['pose']['joints'].values()))
        points=[[100,100] for _ in range(133)];scores=[.9]*133
        scores[BODY33['left_index']]=.1
        points[BODY33['right_wrist']]=[-5,100]
        payload=telemetry(self.job(),1,.5,points,scores)
        validate(payload)
        self.assertIsNone(payload['pose']['joints']['left_index']['image_xy_px'])
        self.assertIsNone(payload['pose']['joints']['right_wrist']['image_xy_px'])


if __name__=='__main__': unittest.main()
