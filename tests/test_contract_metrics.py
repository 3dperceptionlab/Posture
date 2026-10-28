import copy
import json
import unittest
from fastapi import HTTPException
from jsonschema import Draft202012Validator, FormatChecker
from backend.store import ROOT
from backend.validation import validate
from backend.metrics import compute, score_rula, score_reba


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.message=json.loads((ROOT/'examples/telemetry.json').read_text())
        self.context=json.loads((ROOT/'examples/task-context.provisional.json').read_text())

    def test_examples_match_json_schema(self):
        schema=json.loads((ROOT/'schemas/messages.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        validator=Draft202012Validator(schema,format_checker=FormatChecker())
        for filename in ('telemetry.json','profile-application.json','phase-started.json','cycle-completed.json','shift-assessment.json'):
            with self.subTest(filename=filename):
                validator.validate(json.loads((ROOT/'examples'/filename).read_text()))
        Draft202012Validator(json.loads((ROOT/'schemas/operator-profile.schema.json').read_text()),format_checker=FormatChecker()).validate(json.loads((ROOT/'examples/operator-profile.json').read_text()))

    def test_33_points_with_missing_feet_are_valid(self):
        validate(self.message)
        self.assertEqual(len(self.message['pose']['joints']),33)
        self.assertEqual(self.message['pose']['joints']['left_ankle']['status'],'missing')

    def test_mismatched_frame_is_rejected(self):
        self.message['frame']['frame_id']='other'
        with self.assertRaises(HTTPException): validate(self.message)

    def test_missing_points_cannot_have_fake_coordinates(self):
        self.message['pose']['joints']['left_ankle']['image_xy_px']=[0,0]
        with self.assertRaises(HTTPException): validate(self.message)

    def test_invalid_robot_orientation_rejected(self):
        self.message['robot']['tcp_pose']['orientation_xyzw']=[0,0,0,0]
        with self.assertRaises(HTTPException): validate(self.message)

    def test_unlabelled_depth_rejected(self):
        self.message['pose']['joints']['nose']['point_3d_m']=[0,1,2]
        with self.assertRaises(HTTPException): validate(self.message)

    def test_vacuum_feedback_not_invented(self):
        self.message['robot']['suction']['measured_active']=True
        with self.assertRaises(HTTPException): validate(self.message)

    def test_nonfinite_values_rejected(self):
        self.message['robot']['joint_positions_rad'][0]=float('nan')
        with self.assertRaises(HTTPException): validate(self.message)

    def test_partial_application_cannot_be_complete(self):
        ack=json.loads((ROOT/'examples/profile-application.json').read_text())
        ack['table']['applied_revision']=2
        with self.assertRaises(HTTPException): validate(ack)

    def test_known_rula_table_cases(self):
        self.assertEqual(score_rula(1,1,1,1,1,1,1,0,0),1)
        self.assertEqual(score_rula(6,3,4,2,6,6,2,1,3),7)
        self.assertEqual(score_rula(1,1,1,1,1,1,1,1,2),4)

    def test_known_reba_table_cases(self):
        self.assertEqual(score_reba(1,1,1,1,1,1,0,0,0),1)
        self.assertEqual(score_reba(6,2,3,3,5,4,3,3,3),15)
        self.assertEqual(score_reba(3,2,2,2,3,2,0,1,1),8)

    def test_preliminary_status_and_context_preserved(self):
        result=compute(self.message,self.context)
        self.assertEqual(result['status'],'preliminary_assumed')
        self.assertEqual(result['geometry'],'projected_2d')
        self.assertLess(result['coverage'],1)
        self.assertEqual(result['context_snapshot'],self.context)
        self.assertTrue(result['assumptions'])

    def test_mass_threshold_is_not_rounded(self):
        high=compute(self.message,self.context)
        self.context['phases']['manual_finishing']['human_load_proxy_kg']['value']=1.99
        low=compute(self.message,self.context)
        self.assertEqual(high['sides']['left']['components']['load_rula'],2)
        self.assertEqual(low['sides']['left']['components']['load_rula'],0)

    def test_missing_upper_body_does_not_produce_score(self):
        for j in self.message['pose']['joints'].values():
            j.update(status='missing',confidence=None,image_xy_px=None,point_3d_m=None)
        result=compute(self.message,self.context)
        self.assertIsNone(result['rula'])
        self.assertIsNone(result['reba'])
        self.assertEqual(result['status'],'not_evaluable')

    def test_zero_length_segment_does_not_crash(self):
        for name in ('left_shoulder','left_elbow','left_wrist'):
            self.message['pose']['joints'][name]['image_xy_px']=[500,500]
        result=compute(self.message,self.context)
        self.assertIsNone(result['sides']['left']['rula'])


if __name__=='__main__':
    unittest.main()
