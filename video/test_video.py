"""Offline fixtures only: python -m unittest video.test_video -v."""
from __future__ import annotations

import shutil
import unittest
import uuid

import cv2
import numpy as np

from video.common import BASE, Workspace, info, provenance, stamp


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.root = BASE / "tests" / uuid.uuid4().hex
        self.ws = Workspace(self.root)
        self.addCleanup(lambda: shutil.rmtree(self.root))

    def test_workspace_never_escapes_or_overwrites_raw(self):
        for name in ("../escape.mp4", "raw/original.mp4", "photos/original.png"):
            with self.assertRaises(ValueError):
                self.ws.out(name)
        with self.assertRaises(ValueError):
            Workspace(BASE.parent / "wrong")

    def test_disclosures_change_pixels_and_do_not_mutate_input(self):
        image = np.full((480, 640, 3), 100, np.uint8)
        for kind in ("simulation", "reconstructed", "unknown"):
            labeled = stamp(image, {"kind": kind})
            self.assertFalse(np.array_equal(image, labeled))
        self.assertTrue(np.all(image == 100))

    def test_demo_assets_real_encoding_and_mujoco(self):
        from video.synthetic import demo_assets
        result = demo_assets(self.ws, seconds=2)
        details = info(result["clip"])
        self.assertEqual(details["frames"], 60)
        self.assertTrue(details["audio"])
        self.assertTrue(provenance(result["clip"])["synthetic"])
        self.assertEqual(provenance(self.root / "raw-sim/so101.mp4")["kind"], "reconstructed")

    def test_markerless_corners_and_homography_under_two_mm(self):
        from video.geometry import detect_corners, homography
        image = np.full((480, 640, 3), (155, 70, 15), np.uint8)
        truth = np.float32([[90, 95], [552, 110], [580, 390], [55, 375]])
        cv2.fillConvexPoly(image, truth.astype(np.int32), (220, 225, 230))
        detected = detect_corners(image)
        matrix, size = homography(detected, 300, 180)
        got = cv2.perspectiveTransform(truth[None], matrix)[0]
        expected = np.float32([[0, 0], [599, 0], [599, 359], [0, 359]])
        error_mm = np.linalg.norm(got-expected, axis=1)/2
        self.assertLess(float(error_mm.max()), 2)
        self.assertEqual(size, (600, 360))

    def test_bad_geometry_is_refused(self):
        from video.geometry import order_corners, homography, detect_corners
        with self.assertRaises(ValueError):
            order_corners([[0,0]]*4)
        with self.assertRaises(ValueError):
            homography([[0,0],[100,0],[100,100],[0,100]], -1, 100)
        with self.assertRaises(ValueError):
            detect_corners(np.zeros((480,640,3), np.uint8))

    def test_ingest_does_not_invent_sync_or_downgrade_simulation(self):
        from video.common import save_provenance, read_json
        from video.ingest import ingest
        folder = self.root/'photos'
        folder.mkdir()
        path = folder/'tray.png'
        cv2.imwrite(str(path), np.full((240,320,3), 100, np.uint8))
        ingest(self.ws, kind='real')
        asset = read_json(self.root/'manifest.json')['assets'][0]
        self.assertIsNone(asset['start_time'])
        self.assertEqual(provenance(path)['kind'], 'real')
        save_provenance(path, kind='simulation', synthetic=True)
        with self.assertRaises(ValueError):
            ingest(self.ws, kind='real')

    def test_photo_sift_alignment_has_low_error(self):
        from video.topdown import align_photo
        rng = np.random.default_rng(17)
        image = rng.integers(0,255,(240,320,3), dtype=np.uint8)
        reference = cv2.warpAffine(image, np.float32([[1,0,4],[0,1,-3]]), (320,240))
        matrix, report = align_photo(image, reference)
        self.assertLess(report['median_error_px'], 1)
        np.testing.assert_allclose(matrix[:2,2], [4,-3], atol=.5)

    def test_invalid_joint_units_are_rejected_not_silently_converted(self):
        from video.common import write_json
        from video.reconstruction import load_joints
        path = self.ws.out('joints.json')
        write_json(path, {'units':'radians','fps':30,'states':[[0]*6]})
        with self.assertRaises(ValueError):
            load_joints(path)

    def test_idle_speed_requires_review_and_preserves_source_clock(self):
        from video.clean import clean
        from video.common import encode, save_provenance, epoch_at, frame_at
        source=self.root/'static.mp4'
        image=np.full((240,320,3),80,np.uint8)
        encode(self.ws,source,(image for _ in range(90)))
        save_provenance(source,kind='simulation',synthetic=True,start_time=100.0)
        with self.assertRaises(ValueError):
            clean(self.ws,source,'clean/out.mp4',idle_speed=2)
        doc=clean(self.ws,source,'clean/out.mp4',idle_speed=2,idle_confirmed=True)
        self.assertTrue(doc['time_altered'])
        self.assertLess(info(self.root/'clean/out.mp4')['frames'],90)
        self.assertGreater(epoch_at(doc,1),101)
        image=frame_at(self.root/'clean/out.mp4',1)
        # The mandatory disclosure panel, including speed, survives encoding.
        self.assertGreater(float(image[:20].mean()),100)

    def test_take_selection_excludes_failure_retries_and_wrong_order(self):
        from video.takes import successful_trials
        rows=[{'type':'command','action':'handover','t':1,'command_id':'a'},
              {'type':'handed','retries':0,'t':2,'command_id':'a'},
              {'type':'released','t':3,'command_id':'a'}]
        self.assertEqual(len(successful_trials(rows)[0]),1)
        for change in ({'retries':1},{'retries':None},{'t':4}):
            copy=[dict(row) for row in rows]
            copy[1].update(change)
            self.assertEqual(len(successful_trials(copy)[0]),0)
        self.assertEqual(len(successful_trials(rows+[{'type':'error','t':2.5,'command_id':'a'}])[0]),0)

    def _caption(self, **over):
        row={'case_id':'c','item':'hemostat','event_type':'handed','timestamp':10.0,'label':'arm holds a hemostat out',
             'label_source':'perceptron','caption_item':'hemostat','caption_action':'handed','agrees':True}
        row.update(over)
        return row

    def test_agreeing_and_disagreeing_captions_reorder_takes(self):
        from video.captions import assess
        from video.takes import rank
        trial={'command_id':'a','case_id':'c','item':'hemostat','start':9.0,'end':12.0}
        good=assess(trial,[self._caption()])
        self.assertEqual(good['caption_score'],1)
        self.assertEqual(good['captions'],['arm holds a hemostat out'])
        wrong=assess(trial,[self._caption(agrees=False,caption_item='scalpel',label='arm holds a scalpel')])
        self.assertEqual(wrong['caption_score'],-1)
        self.assertEqual(wrong['caption_reasons'],['camera disagrees: saw scalpel, controller said hemostat'])
        words=assess(trial,[self._caption(label='the hemostat is dropped',agrees=None)])
        self.assertEqual(words['caption_score'],-1)
        empty=assess(trial,[self._caption(label='empty gripper over the tray',agrees=None)])
        self.assertEqual(empty['caption_score'],-1)
        takes=[{'id':'wrong','framing_score_laplacian':900,**wrong},{'id':'none','framing_score_laplacian':500,
               'caption_score':0},{'id':'good','framing_score_laplacian':100,**good}]
        self.assertEqual([t['id'] for t in rank(takes)],['good','none','wrong'])

    def test_fallback_labels_and_other_trials_are_ignored(self):
        from video.captions import assess
        trial={'command_id':'a','case_id':'c','item':'hemostat','start':9.0,'end':12.0}
        fallback=self._caption(label_source='fallback',label='hemostat dropped',agrees=False)
        elsewhere=self._caption(timestamp=99.0,agrees=False)
        other_case=self._caption(case_id='other',agrees=False)
        result=assess(trial,[fallback,elsewhere,other_case])
        self.assertEqual((result['caption_score'],result['captions']),(0,[]))

    def test_qa_report_flags_lower_a_training_take(self):
        from video.captions import assess
        trial={'command_id':'a','item':'hemostat','start':1,'end':2,'episode':3}
        qa={3:{'episode':3,'flags':['dropped'],'caption':'the tool falls'},4:{'episode':4,'flags':[]}}
        result=assess(trial,[],qa)
        self.assertEqual(result['caption_score'],-1)
        self.assertEqual(result['captions'],['the tool falls'])
        self.assertEqual(assess({**trial,'episode':4},[],qa)['caption_score'],0)

    def test_find_shows_captions_tolerates_missing_metadata_and_flag_off(self):
        import json
        from video.common import write_json
        from video.ingest import ingest
        from video.synthetic import demo_assets
        from video.takes import find
        from unittest import mock
        with mock.patch('video.reconstruction.render_joints'):  # the MuJoCo replay is not needed to rank takes
            demo_assets(self.ws,2)
        ingest(self.ws)
        clips=self.root/'clips'
        missing=find(self.ws,'demo/events.jsonl',clips_dir=clips)
        self.assertEqual(missing['takes'][0]['captions'],[])
        (clips/'demo-case').mkdir(parents=True)
        t=1792285200.0+1
        (clips/'demo-case'/'metadata.json').write_text(json.dumps([self._caption(case_id='demo-case',timestamp=t,
            agrees=False,caption_item='scalpel',label='arm holds a scalpel')]))
        report=find(self.ws,'demo/events.jsonl',clips_dir=clips)
        take=report['takes'][0]
        self.assertEqual(take['captions'],['arm holds a scalpel'])
        self.assertIn('camera disagrees: saw scalpel, controller said hemostat',take['caption_reasons'])
        off=find(self.ws,'demo/events.jsonl',clips_dir=clips,captions=False)
        self.assertEqual((off['takes'][0]['caption_score'],off['takes'][0]['captions'],off['captions_used']),(0,[],False))
        (clips/'demo-case'/'metadata.json').write_text('not json')
        self.assertEqual(find(self.ws,'demo/events.jsonl',clips_dir=clips)['takes'][0]['captions'],[])

    def test_caption_records_in_a_ledger_export_are_read(self):
        import json
        from video.captions import load_captions
        path=self.root/'ledger.jsonl'
        row={'type':'caption','t':10.0,**self._caption()}
        path.write_text(json.dumps({'kind':'event','doc':row})+'\n')
        rows=load_captions([{'case_id':'c'}],path,self.root/'none')
        self.assertEqual(len(rows),1)

    def test_overlay_never_shows_a_future_measurement_or_count(self):
        from video.overlay import display_state
        rows=[{'type':'command','action':'handover','heard':'kelly','command_id':'a','t':10,'out':[]},
              {'type':'handed','command_id':'a','t':16.4,'request_to_hand_s':6.4,'out':['hemostat']}]
        self.assertIsNone(display_state(rows,9)['out'])
        self.assertIsNone(display_state(rows,12)['seconds'])
        self.assertEqual(display_state(rows,12)['out'],[])
        self.assertEqual(display_state(rows,17)['seconds'],6.4)
        self.assertEqual(display_state(rows,17)['out'],['hemostat'])

    def test_actual_ledger_buffer_envelopes_are_supported(self):
        from video.common import events,ledger_rows
        path=self.ws.out('buffer.jsonl')
        path.write_text('{"kind":"event","doc":{"type":"count","t":2}}\n{"kind":"test","doc":{"success":false,"t":3}}\n')
        self.assertEqual(len(events(path)),1)
        self.assertEqual(len(ledger_rows(path)),2)

    def test_rates_use_test_denominator_including_failures_not_selected_takes(self):
        from video.cards import trial_table
        rows=[{'_record_kind':'test','success':True,'seconds':6.4,'item':'hemostat'},
              {'_record_kind':'test','success':False,'seconds':None,'item':'hemostat'},
              {'_record_kind':'event','type':'handed','item':'hemostat'}]
        table=trial_table(rows)
        self.assertEqual((table[0]['successes'],table[0]['attempts']),(1,2))
        self.assertEqual(table[0]['median_s'],6.4)
        self.assertLess(table[0]['low'],.5)
        self.assertGreater(table[0]['high'],.5)

    def make_short_edit(self,kind='simulation'):
        from video.common import save_provenance,write_json
        path=self.ws.out('fixture.png')
        cv2.imwrite(str(path),np.zeros((240,320,3),np.uint8))
        save_provenance(path,kind=kind,synthetic=kind=='simulation')
        bindings=self.ws.out('edit.json')
        write_json(bindings,{'ONE':{'source':'fixture.png'},'TWO':{'source':'fixture.png'}})
        edl=self.ws.out('edit.yaml')
        edl.write_text('version: 1\nwidth: 1920\nheight: 1080\nfps: 30\nduration_s: 1\nshots:\n - {slot: ONE, duration_s: 0.4}\n - {slot: TWO, duration_s: 0.6}\n')
        return edl,bindings

    def test_render_matches_edl_frames_and_burns_simulation_on_every_shot(self):
        from video.edit import render
        from video.common import frame_at
        edl,bindings=self.make_short_edit()
        report=render(self.ws,edl,bindings,'renders/test.mp4',demo=True)
        self.assertEqual(report['frames'],30)
        self.assertEqual(report['duration_s'],1)
        self.assertEqual([s['frames'] for s in report['shots']],[12,18])
        for t in (0,.4,.9):
            frame=frame_at(self.root/'renders/test.mp4',t)
            self.assertGreater(float(frame[:18].mean()),100)
            self.assertLess(float(frame[-20:].mean()),10)
        self.assertTrue(info(self.root/'renders/test.mp4')['audio'])

    def test_production_render_refuses_synthetic_or_missing_bindings(self):
        from video.edit import resolve_plan
        from video.common import write_json
        edl,bindings=self.make_short_edit()
        with self.assertRaises(ValueError):
            resolve_plan(self.ws,edl,bindings,demo=False)
        write_json(bindings,{})
        with self.assertRaises(ValueError):
            resolve_plan(self.ws,edl,bindings,demo=True)

    def test_reader_never_loops_an_unlabelled_or_real_clip(self):
        from video.common import encode,save_provenance
        from video.edit import Reader
        path=self.ws.out('fixture.mp4')
        encode(self.ws,path,(np.zeros((120,160,3),np.uint8) for _ in range(3)))
        save_provenance(path,kind='real')
        reader=Reader(path,demo=True)
        self.addCleanup(reader.close)
        with self.assertRaises(ValueError):
            reader.get(1)

    def test_preview_keeps_the_edl_duration_at_low_resolution(self):
        from video.edit import render
        edl,bindings=self.make_short_edit()
        report=render(self.ws,edl,bindings,'renders/preview.mp4',demo=True,preview=True)
        self.assertEqual((report['width'],report['height'],report['fps']),(640,360,15))
        self.assertEqual(report['duration_s'],1)
        self.assertEqual(report['frames'],15)

    def test_pose_logs_preserve_observations_and_public_gripper_convention(self):
        import json
        from video.reconstruction import load_joints
        path=self.ws.out('pose.jsonl')
        rows=[{'t':100+i*.1,'joints_deg':[1,2,3,4,5],'gripper':i*.5} for i in range(3)]
        path.write_text('\n'.join(json.dumps(r) for r in rows))
        states,fps,doc=load_joints(path)
        np.testing.assert_array_equal(states[:,5],[100,50,0])
        self.assertAlmostEqual(fps,10)
        self.assertEqual(doc['start_time'],100)
        rows[-1]['t']=101
        path.write_text('\n'.join(json.dumps(r) for r in rows))
        with self.assertRaises(ValueError):
            load_joints(path)

    def test_texture_optical_flow_tracks_plane_not_four_ambiguous_pixels(self):
        from video.geometry import tracked_points
        rng=np.random.default_rng(41)
        previous=rng.integers(0,255,(240,320),dtype=np.uint8)
        current=cv2.warpAffine(previous,np.float32([[1,0,2],[0,1,1]]),(320,240))
        points=np.float32([[30,30],[290,30],[290,210],[30,210]])
        result=tracked_points(previous,current,points)
        np.testing.assert_allclose(result,points+[2,1],atol=.5)

    def test_clap_detection_uses_the_actual_audio_peak(self):
        from video.ingest import detect_clap
        from video.common import encode,run_ffmpeg
        path=self.ws.out('quiet.mp4')
        frame=np.zeros((120,160,3),np.uint8)
        encode(self.ws,path,(frame for _ in range(60)))
        output=self.ws.out('clap.mp4')
        run_ffmpeg(self.ws,['-i',path,'-f','lavfi','-i',"aevalsrc=if(between(t\\,0.4\\,0.42)\\,0.8*sin(2*PI*1000*t)\\,0):s=16000:d=2",'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac',output])
        second,ratio=detect_clap(output)
        self.assertAlmostEqual(second,.41,delta=.03)
        self.assertGreater(ratio,6)

    def test_appearance_cleanup_preserves_an_existing_compressed_time_map(self):
        from video.clean import clean
        from video.common import encode,save_provenance,epoch_at
        source=self.ws.out('fixture.mp4')
        encode(self.ws,source,(np.full((120,160,3),50,np.uint8) for _ in range(90)))
        save_provenance(source,kind='simulation',synthetic=True,start_time=100)
        first=clean(self.ws,source,'clean/fast.mp4',idle_speed=2,idle_confirmed=True)
        second=clean(self.ws,'clean/fast.mp4','clean/appearance.mp4',denoise=True)
        self.assertEqual(first['time_map'],second['time_map'])
        self.assertEqual(epoch_at(first,1),epoch_at(second,1))

    def test_lerobot_v3_reader_preserves_measured_states_and_order(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from video.common import write_json
        from video.reconstruction import load_joints
        root=self.ws.out('dataset/meta/info.json').parents[1]
        names=['shoulder_pan.pos','shoulder_lift.pos','elbow_flex.pos','wrist_flex.pos','wrist_roll.pos','gripper.pos']
        write_json(root/'meta/info.json',{'fps':30,'data_path':'data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet',
            'features':{'observation.state':{'names':names}}})
        eps=root/'meta/episodes/chunk-000/file-000.parquet'
        eps.parent.mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist([{'episode_index':0,'length':2,'data/chunk_index':0,'data/file_index':0,'tasks':['pick the hemostat']}]),eps)
        data=root/'data/chunk-000/file-000.parquet'
        data.parent.mkdir(parents=True)
        expected=[[1,2,3,4,5,40],[2,3,4,5,6,60]]
        pq.write_table(pa.Table.from_pylist([{'observation.state':state,'action':[0]*6,'episode_index':0,'frame_index':i}
                                           for i,state in enumerate(expected)]),data)
        states,fps,doc=load_joints(root)
        np.testing.assert_array_equal(states,expected)
        self.assertEqual(fps,30)
        self.assertEqual(doc['instruction'],'pick the hemostat')

    def test_unedited_roll_refuses_a_previously_cut_source(self):
        from video.edit import resolve_plan
        from video.common import encode,save_provenance,write_json
        path=self.ws.out('cut.mp4')
        encode(self.ws,path,(np.zeros((120,160,3),np.uint8) for _ in range(3)))
        save_provenance(path,kind='real',continuous=False)
        binding=self.ws.out('arm-bindings.json')
        write_json(binding,{'ARM_ROLL':{'source':'cut.mp4'}})
        edl=self.ws.out('arm-edit.yaml')
        edl.write_text('version: 1\nwidth: 1920\nheight: 1080\nfps: 30\nmode: continuous_arm\n')
        with self.assertRaises(ValueError):
            resolve_plan(self.ws,edl,binding)

    def test_face_privacy_blurs_unknown_and_forgets_lost_team_faces(self):
        from video.clean import Faces
        tool=Faces.__new__(Faces)
        tool.trusted=[[10,10,40,40]]
        tool.boxes=lambda image:[[10,10,40,40],[90,10,40,40]]
        rng=np.random.default_rng(12)
        original=rng.integers(0,255,(100,160,3),dtype=np.uint8)
        result=tool.apply(original.copy())
        np.testing.assert_array_equal(original[10:50,10:50],result[10:50,10:50])
        self.assertLess(float(result[10:50,90:130].var()),float(original[10:50,90:130].var()))
        tool.boxes=lambda image:[]
        tool.apply(original.copy())
        self.assertEqual(tool.trusted,[])

    def test_default_events_and_dataset_paths(self):
        import json
        from unittest import mock
        import ledger
        from video import __main__ as cli
        from video.common import default_events, events, export_ledger
        with self.assertRaises(ValueError):
            default_events(self.ws)
        with mock.patch.object(ledger, "warm"), mock.patch.object(ledger, "stored_rows", return_value=([], [])):
            with self.assertRaises(ValueError):
                export_ledger(self.ws)
        rows = ([{"type": "count", "t": 2.0, "when": object()}], [{"success": True, "t": 3.0}])
        with mock.patch.object(ledger, "warm"), mock.patch.object(ledger, "stored_rows", return_value=rows):
            self.assertEqual(export_ledger(self.ws)["tests"], 1)
        self.assertEqual(default_events(self.ws), self.root / "events.jsonl")
        self.assertEqual(len(events(default_events(self.ws))), 1)
        self.assertEqual(json.loads((self.root / "events.jsonl").read_text().splitlines()[1])["kind"], "test")
        seen = {}
        with mock.patch("video.reconstruction.render_joints", lambda ws, source, *a, **k: seen.setdefault("source", source) and {}), \
                mock.patch.object(cli, "DEFAULT_DATASET", self.root / "scrub-dataset"):
            self.assertEqual(cli.main(["--root", str(self.root), "topdown", "--mode", "reconstruction", "--output", "x.mp4"]), 0)
        self.assertEqual(seen["source"], self.root / "scrub-dataset")

    def test_every_command_on_markerless_synthetic_assets(self):
        import yaml
        from video.synthetic import demo_assets
        from video.geometry import corners
        from video.ingest import ingest
        from video.topdown import warp,photo_plate
        from video.reconstruction import render_joints
        from video.clean import clean
        from video.takes import find
        from video.overlay import overlay
        from video.cards import cards
        from video.edit import render
        from video.common import write_json
        demo_assets(self.ws,2)
        ingest(self.ws)
        corners(self.ws,'raw/demo.mp4','side',300,180,headless=True,accept_auto=True)
        corners(self.ws,'photos/demo-00.png','photo',300,180,headless=True,accept_auto=True)
        warp(self.ws,'raw/demo.mp4','side','topdown/plane.mp4')
        photo_plate(self.ws,'photos/demo-00.png','photos','photo','topdown/plate.png',True)
        render_joints(self.ws,self.root/'demo/joints.json',self.ws.out('topdown/reconstruction.mp4'),
            width=640,height=480,plate=self.root/'topdown/plate.png',alignment=self.root/'demo/plate-alignment.json')
        clean(self.ws,'raw/demo.mp4','clean/demo.mp4',stabilize=True,deflicker=True,denoise=True,audio_clean=True)
        report=find(self.ws,'demo/events.jsonl',cut=True)
        self.assertEqual(len(report['takes']),1)
        overlay(self.ws,'clean/demo.mp4','demo/events.jsonl','overlays/demo.mp4',allow_synthetic=True)
        report=cards(self.ws,'demo/events.jsonl',allow_synthetic=True)
        self.assertEqual(report['table'][0]['attempts'],2)
        edl=self.ws.out('short.yaml')
        edl.write_text(yaml.safe_dump({'version':1,'width':1920,'height':1080,'fps':30,'duration_s':2,
            'shots':[{'slot':'A','duration_s':1},{'slot':'B','duration_s':.5,'treatment':'side-by-side'},
                     {'slot':'C','duration_s':.5}]}))
        bindings=self.ws.out('short.json')
        write_json(bindings,{'A':{'source':'overlays/demo.mp4'},'B':{'source':'topdown/reconstruction.mp4','secondary':'clean/demo.mp4'},
                             'C':{'source':'cards/end.png'},'ARM_ROLL':{'source':'raw/demo.mp4'}})
        result=render(self.ws,edl,bindings,'renders/test.mp4',demo=True)
        self.assertEqual(result['frames'],60)
        result=render(self.ws,edl,bindings,'renders/preview.mp4',demo=True,preview=True)
        self.assertEqual(result['duration_s'],2)
        arm=self.ws.out('arm.yaml')
        arm.write_text(yaml.safe_dump({'version':1,'width':1920,'height':1080,'fps':30,'mode':'continuous_arm','end_card_s':1}))
        result=render(self.ws,arm,bindings,'renders/arm.mp4',demo=True)
        self.assertEqual(result['frames'],90)


if __name__ == "__main__":
    unittest.main()
