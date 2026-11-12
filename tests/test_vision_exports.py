import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from backend import auth
from backend.vision import download_export, exports
from backend.vision_exports import overlay_events, draw_pose, metrics_record
from backend.vision_export_common import folder_name, public_export


class VisionExportTests(unittest.TestCase):
    def test_variable_frame_times_never_use_future_samples_and_missing_clears(self):
        first={'offset_s':.03,'keypoints':[[100,100]],'scores':[1]}
        missing={'offset_s':.12,'keypoints':[],'scores':[]}
        future={'offset_s':5.,'keypoints':[[300,300]],'scores':[1]}
        times=[0,.04,.081,.13,.2]
        events=overlay_events(times,[first,missing,future])
        self.assertEqual(events,[(0,None),(1,first),(3,missing)])
        for index,row in events:
            if row:self.assertLessEqual(row['offset_s'],times[index]+1e-6)
        self.assertIsNone(draw_pose(missing,.5).getbbox())
        self.assertIsNotNone(draw_pose(first,.5).getbbox())

    def test_same_presentation_frame_uses_latest_eligible_sample(self):
        a={'offset_s':.021};b={'offset_s':.031}
        self.assertEqual(overlay_events([0,.04,.1],[a,b]),[(0,None),(1,b)])

    def test_csv_keeps_metric_components_nulls_and_provenance(self):
        row={'sequence':2,'offset_s':.4,'metrics':{'rula':None,'angles':{'elbow_left':90},'assumptions':['provisional']}}
        value=metrics_record(row)
        self.assertIsNone(value['metrics.rula'])
        self.assertEqual(value['metrics.angles.elbow_left'],90)
        self.assertEqual(value['metrics.assumptions'],'["provisional"]')

    def test_export_paths_and_public_metadata_do_not_leak_storage_details(self):
        job={'name':'../../clip / similar name','job_id':'vision-123'}
        name=folder_name(1,job)
        self.assertNotIn('/',name)
        self.assertNotIn('..',name)
        self.assertTrue(name.endswith('vision-123'))
        self.assertEqual(public_export({'path':'private','job_ids':['x'],'active':True,'export_id':'e'}),{'export_id':'e'})

    def test_strict_anonymous_and_viewer_cannot_list_or_download_archives(self):
        import os
        request=Request({'type':'http','headers':[]})
        with patch.dict(os.environ,{'POSTURE_AUTH_MODE':'strict'}):
            for fn,args in ((exports,(request,)),(download_export,('any-id',request))):
                with self.assertRaises(HTTPException) as error:fn(*args)
                self.assertEqual(error.exception.status_code,401)
        with patch.object(auth,'principal',return_value={'username':'reader','role':'viewer'}):
            with self.assertRaises(HTTPException) as error:download_export('any-id',request)
            self.assertEqual(error.exception.status_code,403)


if __name__=='__main__':unittest.main()
