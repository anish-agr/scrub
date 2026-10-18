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


if __name__ == "__main__":
    unittest.main()
