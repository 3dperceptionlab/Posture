import unittest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError

from fastapi import HTTPException
from starlette.requests import Request

from backend import auth
from backend.vision import download_export, exports, available_exports, new_export, ExportSelection
from backend.vision_exports import overlay_events, draw_pose, metrics_record
from backend.vision_export_common import folder_name, public_export, request_export, validate_job_ids, laboratory_export_jobs


class VisionExportTests(unittest.TestCase):
    def export_jobs(self):
        return [{'job_id':f'job-{i}','name':f'Run {i}','status':status}
                for i,status in enumerate(('completed','running','failed','completed'))]

    def test_only_requested_runs_are_snapshotted_once(self):
        database=MagicMock();database.vision_exports.find_one.return_value=None
        with patch('backend.vision_export_common.db',database),patch('backend.vision_export_common.initialize_exports'),patch(
                'backend.vision_export_common.laboratory_export_jobs',return_value=self.export_jobs()):
            result=request_export({'username':'tester'},['job-3','job-0','job-3'])
        inserted=database.vision_exports.insert_one.call_args.args[0]
        self.assertEqual(inserted['job_ids'],['job-0','job-3'])
        self.assertEqual((result['total_runs'],result['scope']),(2,'selection'))
        self.assertNotIn('job_ids',result)

    def test_empty_or_invalid_selection_never_becomes_export_all(self):
        for value in ([], 'job-0', [None], [4], [''], ['x'*129]):
            with self.subTest(value=value),self.assertRaises(HTTPException):validate_job_ids(value)
        for body in ({'job_ids':[]},{'job_ids':[4]},{'wrong_field':['job-0']}):
            with self.subTest(body=body),self.assertRaises(ValidationError):ExportSelection.model_validate(body)

    def test_unavailable_or_active_requested_run_rejects_entire_selection(self):
        for selected in (['job-0','missing'],['job-0','job-1']):
            database=MagicMock();database.vision_exports.find_one.return_value=None
            with patch('backend.vision_export_common.db',database),patch('backend.vision_export_common.initialize_exports'),patch(
                    'backend.vision_export_common.laboratory_export_jobs',return_value=self.export_jobs()),self.assertRaises(HTTPException) as error:
                request_export({'username':'tester'},selected)
            self.assertEqual(error.exception.status_code,409)
            database.vision_exports.insert_one.assert_not_called()

    def test_different_active_archive_is_not_returned_as_selected_archive(self):
        database=MagicMock();database.vision_exports.find_one.return_value={
            'job_ids':['job-0'],'export_id':'active','active':True}
        with patch('backend.vision_export_common.db',database),patch('backend.vision_export_common.initialize_exports'),patch(
                'backend.vision_export_common.laboratory_export_jobs',return_value=self.export_jobs()):
            self.assertEqual(request_export({'username':'tester'},['job-0'])['export_id'],'active')
            with self.assertRaises(HTTPException) as error:request_export({'username':'tester'},['job-3'])
            self.assertEqual(error.exception.status_code,409)
        database.vision_exports.insert_one.assert_not_called()

    def test_export_all_still_skips_incomplete_runs(self):
        database=MagicMock();database.vision_exports.find_one.return_value=None
        with patch('backend.vision_export_common.db',database),patch('backend.vision_export_common.initialize_exports'),patch(
                'backend.vision_export_common.laboratory_export_jobs',return_value=self.export_jobs()):
            result=request_export({'username':'tester'})
        self.assertEqual(result['scope'],'all')
        self.assertEqual(result['total_runs'],3)
        self.assertEqual(result['skipped_runs'][0]['job_id'],'job-1')

    def test_candidate_source_excludes_missing_sessions_and_deleted_assets(self):
        database=MagicMock()
        database.vision_jobs.find.return_value.sort.return_value=[
            {'job_id':'keep','session_id':'s','asset_id':'a'},
            {'job_id':'deleted-session','session_id':'gone','asset_id':'a'},
            {'job_id':'deleted-asset','session_id':'s','asset_id':'gone'}]
        database.sessions.find.return_value=[{'_id':'s'}]
        database.vision_assets.find.return_value=[{'_id':'a','capture':{'camera_index':2}}]
        with patch('backend.vision_export_common.db',database):rows=laboratory_export_jobs()
        self.assertEqual([(r['job_id'],r['camera_index']) for r in rows],[('keep',2)])
        self.assertEqual(database.vision_jobs.find.call_args.args[0]['origin'],{'$ne':'real'})

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
            for fn,args in ((exports,(request,)),(download_export,('any-id',request)),(available_exports,(request,)),(new_export,(request,))):
                with self.assertRaises(HTTPException) as error:fn(*args)
                self.assertEqual(error.exception.status_code,401)
        with patch.object(auth,'principal',return_value={'username':'reader','role':'viewer'}):
            with self.assertRaises(HTTPException) as error:download_export('any-id',request)
            self.assertEqual(error.exception.status_code,403)


if __name__=='__main__':unittest.main()
