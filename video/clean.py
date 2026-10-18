"""Optional non-generative cleanup with auditable source-time mapping."""
from __future__ import annotations

import json
from urllib.request import urlopen

import cv2
import numpy as np

from .common import encode, epoch_at, fit, frame_at, frames, info, provenance, save_provenance, stamp, text_bar, write_json


def motion_report(source, threshold=.6, min_idle_s=2):
    details = info(source)
    previous, scores = None, []
    for _t, frame in frames(source):
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160,120))
        scores.append(255.0 if previous is None else float(cv2.absdiff(gray, previous).mean()))
        previous = gray
    idle, start = [], None
    for n, score in enumerate(scores+[255]):
        if score < threshold and start is None:
            start = n
        elif score >= threshold and start is not None:
            if (n-start)/details["fps"] >= min_idle_s:
                idle.append({"start":start/details["fps"], "end":n/details["fps"]})
            start = None
    return {"threshold_mean_abs_px":threshold, "minimum_idle_s":min_idle_s, "candidates":idle,
            "warning":"Low pixel motion is not proof the robot is idle. Review before compression/cutting."}


def stabilization(source):
    previous, cumulative, trajectory = None, np.eye(3), []
    for _t, frame in frames(source):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if previous is not None:
            points = cv2.goodFeaturesToTrack(previous, maxCorners=200, qualityLevel=.02, minDistance=15)
            if points is None or len(points) < 12:
                raise ValueError("Insufficient background texture for stabilization")
            nxt, valid, _ = cv2.calcOpticalFlowPyrLK(previous, gray, points, None)
            if nxt is None or np.count_nonzero(valid) < 10:
                raise ValueError("Stabilization tracking failed")
            valid = valid.ravel().astype(bool)
            affine, mask = cv2.estimateAffinePartial2D(points[valid], nxt[valid], method=cv2.RANSAC)
            if affine is None or mask is None or mask.mean() < .5:
                raise ValueError("Stabilization model unreliable; keep locked original")
            transform = np.vstack([affine,[0,0,1]])
            if not .9 < np.linalg.det(transform[:2,:2]) < 1.1:
                raise ValueError("Camera scale changed too much")
            cumulative = transform @ cumulative
        trajectory.append([cumulative[0,2], cumulative[1,2], np.arctan2(cumulative[1,0], cumulative[0,0])])
        previous = gray
    values = np.asarray(trajectory)
    smooth = np.stack([np.convolve(np.pad(values[:,i], (15,15), mode='edge'), np.ones(31)/31, mode='valid') for i in range(3)],axis=1)
    return smooth-values


class Faces:
    def __init__(self, ws):
        import mediapipe as mp
        self.mp = mp
        model = ws.out("models/blaze_face_short_range.tflite")
        if not model.exists():
            url = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
            with urlopen(url, timeout=60) as response:
                model.write_bytes(response.read())
        options = mp.tasks.vision.FaceDetectorOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(model)), min_detection_confidence=.4)
        self.detector = mp.tasks.vision.FaceDetector.create_from_options(options)
        self.trusted = []

    def boxes(self, image):
        result = self.detector.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(image, cv2.COLOR_BGR2RGB)))
        return [[d.bounding_box.origin_x,d.bounding_box.origin_y,d.bounding_box.width,d.bounding_box.height] for d in result.detections]

    def choose_team(self, image):
        boxes = self.boxes(image)
        kept = set()
        name = "Scrub privacy: click TEAM faces to keep; Enter accepts; Esc cancels"
        def click(event,x,y,_flags,_param):
            if event == cv2.EVENT_LBUTTONDOWN:
                for i,(bx,by,w,h) in enumerate(boxes):
                    if bx <= x <= bx+w and by <= y <= by+h:
                        if i in kept:
                            kept.remove(i)
                        else:
                            kept.add(i)
        cv2.namedWindow(name)
        cv2.setMouseCallback(name,click)
        try:
            while True:
                preview = image.copy()
                for i,(x,y,w,h) in enumerate(boxes):
                    cv2.rectangle(preview,(x,y),(x+w,y+h),(0,200,0) if i in kept else (0,0,255),3)
                cv2.imshow(name,preview)
                key=cv2.waitKey(30)&255
                if key in (10,13):
                    self.trusted=[boxes[i] for i in kept]
                    return
                if key==27 or cv2.getWindowProperty(name,cv2.WND_PROP_VISIBLE)<1:
                    raise ValueError("Team face selection cancelled")
        finally:
            cv2.destroyWindow(name)

    def apply(self, image):
        detected = self.boxes(image)
        new_trusted = []
        for x,y,w,h in detected:
            trusted = False
            for bx,by,bw,bh in self.trusted:
                intersection=max(0,min(x+w,bx+bw)-max(x,bx))*max(0,min(y+h,by+bh)-max(y,by))
                if intersection/max(1,w*h+bw*bh-intersection)>.5:
                    trusted=True
                    break
            if trusted:
                new_trusted.append([x,y,w,h])
            else:
                margin=round(max(w,h)*.25)
                x0,y0=max(0,x-margin),max(0,y-margin)
                x1,y1=min(image.shape[1],x+w+margin),min(image.shape[0],y+h+margin)
                if x1>x0 and y1>y0:
                    image[y0:y1,x0:x1]=cv2.GaussianBlur(image[y0:y1,x0:x1],(0,0),max(w,h)/5)
        # Never recognize reappearing/unknown faces as team automatically.
        self.trusted=new_trusted
        return image

    def close(self):
        self.detector.close()


def clean(ws, source, output, stabilize=False, reference=None, deflicker=False,
          denoise=False, faces=False, keep_team=False, idle_speed=None, cut_idle=False,
          idle_confirmed=False, analyze_only=False, audio_clean=False, upscale=False):
    source,output=ws.source(source),ws.out(output)
    if source==output:
        raise ValueError("Never replace an original")
    details,meta=info(source),provenance(source)
    if details['media']!='video':
        raise ValueError("clean expects video")
    if keep_team and not faces:
        raise ValueError("--keep-team requires --faces")
    report=motion_report(source) if idle_speed or cut_idle or analyze_only else None
    if analyze_only:
        write_json(ws.out("analysis/idle.json"),report)
        return report
    if (idle_speed or cut_idle) and not idle_confirmed:
        raise ValueError("Review clean --analyze-only, then supply --idle-confirmed; low motion is not proof of idle")
    if meta.get('time_map') and (idle_speed or cut_idle):
        raise ValueError("Do not stack time edits; apply idle edits once to the original")
    fps=details['fps']
    ranges=[]
    cursor=0.0
    for interval in (report or {}).get('candidates',[]):
        if interval['start']>cursor:
            ranges.append({'start':cursor,'end':interval['start'],'speed':1})
        if not cut_idle:
            ranges.append({**interval,'speed':idle_speed or 1})
        cursor=interval['end']
    if cursor<details['duration_s']:
        ranges.append({'start':cursor,'end':details['duration_s'],'speed':1})
    if not ranges:
        raise ValueError("Idle cut would remove the entire clip")
    correction=stabilization(source) if stabilize else None
    face_tool=Faces(ws) if faces else None
    first=next(frames(source))[1]
    if face_tool and keep_team:
        face_tool.choose_team(first)
    ref=cv2.imread(str(ws.source(reference))) if reference else None
    if reference and ref is None:
        raise ValueError("Exposure reference cannot be read")
    reference_mean=ref.reshape(-1,3).mean(axis=0) if ref is not None else None
    baseline=None
    timeline=[]
    previews=[]
    def images():
        nonlocal baseline
        output_index=0
        try:
            for segment in ranges:
                start_out=output_index/fps
                for n,(t,original) in enumerate(frames(source,segment['start'],segment['end'])):
                    if n%segment['speed']:
                        continue
                    image=original.copy()
                    stages=[]
                    if correction is not None:
                        dx,dy,angle=correction[min(round(t*fps),len(correction)-1)]
                        transform=np.float32([[np.cos(angle),-np.sin(angle),dx],[np.sin(angle),np.cos(angle),dy]])
                        image=cv2.warpAffine(image,transform,(image.shape[1],image.shape[0]),borderMode=cv2.BORDER_CONSTANT)
                        stages.append(('stabilize',image.copy()))
                    if reference_mean is not None:
                        gain=np.clip(reference_mean/np.maximum(1,image.reshape(-1,3).mean(axis=0)),.6,1.6)
                        image=np.clip(image.astype(float)*gain,0,255).astype(np.uint8)
                        stages.append(('exposure-white-balance',image.copy()))
                    if deflicker:
                        level=max(1,float(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).mean()))
                        baseline=level if baseline is None else baseline*.97+level*.03
                        image=np.clip(image.astype(float)*np.clip(baseline/level,.8,1.25),0,255).astype(np.uint8)
                        stages.append(('deflicker',image.copy()))
                    if face_tool:
                        image=face_tool.apply(image)
                        stages.append(('face-privacy',image.copy()))
                    if output_index==0:
                        for name,stage in stages:
                            comparison=np.hstack([fit(original,480,360),fit(stage,480,360)])
                            comparison=text_bar(comparison,['BEFORE | AFTER: '+name.upper()],bottom=True)
                            preview=ws.out('previews/'+output.stem+'-'+name+'.png')
                            cv2.imwrite(str(preview),stamp(comparison,meta))
                            previews.append(str(preview))
                    yield stamp(image,meta,segment['speed'])
                    output_index+=1
                if meta.get('start_time') is not None:
                    timeline.append({'output_start':start_out,'output_end':output_index/fps,
                        'epoch_start':epoch_at(meta,segment['start']),'speed':segment['speed']})
        finally:
            if face_tool:
                face_tool.close()
    encoded=encode(ws,output,images(),fps,audio=source,segments=ranges,audio_clean=audio_clean,
                   video_filter='hqdn3d=1.5:1.5:6:6' if denoise else None)
    comparison=np.hstack([fit(first,480,360),fit(frame_at(output),480,360)])
    preview=ws.out('previews/'+output.stem+'-final-before-after.png')
    cv2.imwrite(str(preview),stamp(text_bar(comparison,['BEFORE | AFTER ALL ENABLED FILTERS'],bottom=True),meta))
    previews.append(str(preview))
    operation={'command':'clean','stabilize':stabilize,'reference':str(reference) if reference else None,
        'deflicker':deflicker,'denoise':'hqdn3d' if denoise else False,'faces':faces,'keep_team_click_list':keep_team,
        'privacy_warning':'Detector misses remain possible. Review every frame before publication.' if faces else None,
        'idle_segments_reviewed':idle_confirmed,'source_segments':ranges,'audio_noise_reduction':audio_clean,
        'audio_target_lufs':-16,'audio_original_present':details['audio'],'previews':previews,
        'neural_upscale':'SKIPPED: no supported model configured; no generative pixel replacement' if upscale else 'off'}
    return save_provenance(output,source,**encoded,time_map=timeline or meta.get('time_map'),
        operations=meta.get('operations',[])+[operation],continuous=meta.get('continuous',True) and not (idle_speed or cut_idle),
        time_altered=bool(meta.get('time_altered') or idle_speed or cut_idle),
        temporal_kind='compressed' if idle_speed else 'cut' if cut_idle else meta.get('temporal_kind','unchanged'))
