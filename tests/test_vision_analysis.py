import unittest

from fastapi import HTTPException

from backend.vision_metadata import title_metadata, metadata, height_value
from backend.vision_analysis import aggregate, distribution, date_bound, robot_condition


class LaboratoryAnalysisTests(unittest.TestCase):
    def test_correct_unit_typo_without_converting_height_or_robot_model(self):
        self.assertEqual(title_metadata('Con UR10 - Mesa 120mm · Cámara 2'),
                         ('Con UR10 - Mesa 120cm · Cámara 2',120))
        self.assertEqual(title_metadata('Sin Robot - Mesa 75 MM'),('Sin Robot - Mesa 75cm',75))
        for title in ('UR10','camara-2026-10-22.webm','Mesa 175mm','Pieza 1000mm','Mesa 75.100mm'):
            self.assertEqual(title_metadata(title),(title,None))
        self.assertIsNone(title_metadata('Comparación 75cm y 120cm')[1])

    def test_unknown_and_manual_height_override_title_inference(self):
        self.assertEqual(metadata('Mesa 100mm',{})['table_height_cm'],100)
        self.assertIsNone(metadata('Mesa 100mm',{'table_height_cm':None})['table_height_cm'])
        self.assertEqual(metadata('Mesa 100mm',{'table_height_cm':75})['table_height_source'],'manual')
        for invalid in (True,'75',0,201,75.5,float('nan'),float('inf')):
            with self.subTest(value=invalid),self.assertRaises(HTTPException):height_value(invalid)

    def test_ordinal_distribution_excludes_missing_and_invalid_scores(self):
        result=distribution({None:50,0:2,3:3,6:1,8:2},7,5)
        self.assertEqual(result['valid_samples'],4)
        self.assertEqual(result['median'],3)
        self.assertEqual(result['peak'],6)
        self.assertEqual(result['above_threshold_pct'],25)
        self.assertEqual(sum(result['counts']),4)
        self.assertIsNone(distribution({},7,5)['above_threshold_pct'])

    def jobs(self):
        return [{'job_id':f'j{i}','asset_id':f'a{i}','name':'Robot - 75cm','created_at':'2026-11-12T10:00:00Z',
                 'operator_id':f'o{i%2}','table_height_cm':75,'context':{'revision':1,'force':0},
                 'options':{'sample_fps':5,'confidence':.5},'estimator':'test'} for i in range(4)]

    def buckets(self):
        return [{'_id':{'job_id':f'j{i}','rula':r,'reba':2,'revision':1,'algorithm':'v1','geometry':'2d'},'count':n}
                for i,r,n in ((0,3,3),(1,6,1),(2,None,7),(3,4,1))]

    def test_two_cameras_are_one_capture_but_separate_analyses(self):
        jobs=self.jobs()[:2]
        assets={f'a{i}':{'capture':{'group_id':'paired','camera_index':i+1}} for i in range(2)}
        runs,groups=aggregate(jobs,assets,self.buckets()[:2],['table_height_cm'])
        self.assertEqual(len(runs),2)
        self.assertEqual(len(groups),1)
        group=groups[0]
        self.assertEqual((group['captures'],group['analyses'],group['samples']),(1,2,4))
        self.assertEqual(group['rula']['above_threshold_pct'],25)
        self.assertEqual(group['rula']['median'],3)
        _,groups=aggregate(jobs,assets,self.buckets()[:2],['table_height_cm','operator_id'])
        self.assertEqual(len(groups),2)

    def test_changed_context_or_sampling_never_silently_pool_results(self):
        jobs=self.jobs()
        jobs[1]['context']['force']=2  # same revision, different snapshot
        jobs[2]['options']['sample_fps']=10
        buckets=self.buckets();buckets[3]['_id']['algorithm']='v2'
        runs,groups=aggregate(jobs,{},buckets,['table_height_cm'])
        self.assertEqual(len(groups),4)
        self.assertEqual(sum(r['samples'] for r in runs),12)
        self.assertIsNone(next(r for r in runs if r['job_id']=='j2')['rula']['median'])

    def test_day_bounds_and_explicit_robot_labels(self):
        self.assertEqual(date_bound('2026-11-12',True),'2026-11-13T00:00:00.000Z')
        with self.assertRaises(HTTPException):date_bound('2026-02-31')
        self.assertEqual(robot_condition('Sin Robot - Mesa 75cm'),'without_robot')
        self.assertEqual(robot_condition('Con UR10'),'with_robot')
        self.assertEqual(robot_condition('Vídeo de prueba'),'unknown')


if __name__=='__main__':unittest.main()
