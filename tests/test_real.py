import copy
import json
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from backend.store import ROOT
from backend.real_models import Sample, ShiftStart, FormDefinition
from backend.real import encoded, check_assessment, DEFAULT_FORM
from backend.real_processing import ros_metrics


def sample_fixture():
    old=json.loads((ROOT/'examples/telemetry.json').read_text())['pose']
    return {'sequence':0,'captured_at':'2026-10-26T12:00:00Z','frame_id':'synthetic-0','video_time_s':0,
        'image_width':1920,'image_height':1080,'pose':{'estimator_name':'synthetic','estimator_version':'1',
            'space':{'kind':'unknown','frame_id':'unknown','unit':'unknown','axes':'unknown',
                     'rotation_unit':'unknown','rotation_convention':'unknown'},
            'joints':{name:{'status':j['status'],'position':([j['image_xy_px'][0],j['image_xy_px'][1],0]
                        if j['image_xy_px'] else None),'rotation_xyz':None,'confidence':j['confidence'],
                        'image_xy_px':j['image_xy_px']} for name,j in old['joints'].items()}}}


class RealContractTests(unittest.TestCase):
    def context(self):
        return json.loads((ROOT/'examples/task-context.provisional.json').read_text())

    def test_full_body33_and_unknown_conventions_can_be_stored(self):
        row=encoded(Sample.model_validate(sample_fixture()))
        self.assertEqual(len(row['pose']['joints']),33)
        self.assertEqual(row['pose']['space']['unit'],'unknown')
        self.assertEqual(row['captured_at'],'2026-10-26T12:00:00.000000Z')

    def test_timestamps_are_aware_and_canonical_at_equal_instants(self):
        first=sample_fixture();second=sample_fixture()
        second['captured_at']='2026-10-26T14:00:00.000000+02:00'
        self.assertEqual(encoded(Sample.model_validate(first)),encoded(Sample.model_validate(second)))
        first['captured_at']='2026-10-26T12:00:00'
        with self.assertRaises(ValidationError): Sample.model_validate(first)

    def test_rejects_incomplete_body_infinity_and_fake_missing_coordinates(self):
        row=sample_fixture();del row['pose']['joints']['nose']
        with self.assertRaises(ValidationError): Sample.model_validate(row)
        row=sample_fixture();row['pose']['joints']['nose']['position'][0]=float('inf')
        with self.assertRaises(ValidationError): Sample.model_validate(row)
        row=sample_fixture();row['pose']['joints']['nose']['status']='missing'
        with self.assertRaises(ValidationError): Sample.model_validate(row)
        row=sample_fixture();row['metadata']={'nested':{'value':float('nan')}}
        with self.assertRaises(HTTPException): encoded(Sample.model_validate(row))

    def test_unknown_3d_without_image_coordinates_never_produces_score(self):
        row=sample_fixture()
        for joint in row['pose']['joints'].values(): joint['image_xy_px']=None
        result=ros_metrics(encoded(Sample.model_validate(row)),self.context())
        self.assertIsNone(result['rula']);self.assertIsNone(result['reba'])
        self.assertEqual(result['geometry'],'unknown_3d_convention')
        self.assertTrue(result['reason'])

    def test_ros_axis_conversion_and_mm_preserve_angles_without_mutating_input(self):
        optical=sample_fixture()
        optical['pose']['space'].update(kind='camera_metric',axes='optical',unit='m')
        for j in optical['pose']['joints'].values():
            if j['position']: j['position']=[v/1000 for v in j['position']]
        native=copy.deepcopy(optical);native['pose']['space'].update(kind='world_metric',axes='ros',unit='mm')
        for j in native['pose']['joints'].values():
            if j['position']:
                x,y,z=j['position'];j['position']=[z*1000,-x*1000,-y*1000]
        snapshot=copy.deepcopy(native)
        a=ros_metrics(encoded(Sample.model_validate(optical)),self.context())
        b=ros_metrics(encoded(Sample.model_validate(native)),self.context())
        self.assertEqual(a['angles'],b['angles']);self.assertEqual(a['rula'],b['rula'])
        self.assertEqual(native,snapshot)
        self.assertEqual(b['geometry'],'ros_3d_axis_converted_unvalidated')

    def test_form_definition_and_answers_are_versioned_and_bounded(self):
        form=FormDefinition.model_validate(DEFAULT_FORM).model_dump(mode='json')
        answer={'form_id':form['form_id'],'answers':{'fatigue':3,'comment':'Previo'}}
        check_assessment(answer,form,'pre')
        for answers in ({'fatigue':11},{'fatigue':True},{'unknown':1},{'comment':5}):
            with self.assertRaises(HTTPException): check_assessment({**answer,'answers':answers},form,'pre')
        with self.assertRaises(HTTPException): check_assessment({**answer,'form_id':'another'},form,'pre')


if __name__=='__main__': unittest.main()
