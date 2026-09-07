#!/usr/bin/env python3
"""ebo-vision — the game's perception worker.

Reads the robot's RTSP stream, detects animals (→ bosses) and objects (→ NPC houses) with
open-vocabulary segmentation, estimates metric depth, tracks + (optionally) re-identifies each
subject, and POSTs a frame of detections to the control API's game endpoint. The API resolves
persistent entities (boss HP/status) and the game frontend renders the world.

Stack (from the 2026 research): YOLOE-26s-seg (open-vocab seg) + YOLO26n-depth (metric) +
BoT-SORT tracking + DINOv2-small re-id embeddings.

Two modes:
  MODE=real  → load the models and run on the live RTSP frames (needs the weights + torch).
  MODE=fake  → no models; emit moving synthetic detections so you can test the whole pipeline
               (API + game frontend) before pulling gigabytes of weights.

Config is via env — see the compose service / README.
"""
from __future__ import annotations

import math
import os
import time

import numpy as np
import requests

# ---- config ---------------------------------------------------------------
MODE          = os.environ.get("MODE", "real").lower()          # real | fake
RTSP_URL      = os.environ.get("RTSP_URL", "rtsp://ebo-engine:8554/ebo")
API_URL       = os.environ.get("EBO_API_URL", "http://ebo-api:8080").rstrip("/")
API_KEY       = os.environ.get("EBO_API_KEY", "")
ROBOT_ID      = os.environ.get("ROBOT_ID", "ebo")
# mjpeg = read frames from the API's MJPEG proxy (robust, plain JPEGs — no h264/RTSP finickiness);
# rtsp = read the engine's RTSP directly (lower latency but cv2/ffmpeg can choke on the H.264).
VIDEO_SOURCE  = os.environ.get("VIDEO_SOURCE", "mjpeg").lower()
FPS           = float(os.environ.get("FPS", "6"))
IMGSZ         = int(os.environ.get("IMGSZ", "640"))
DEPTH_IMGSZ   = int(os.environ.get("DEPTH_IMGSZ", "512"))
CONF          = float(os.environ.get("CONF", "0.35"))
DEPTH_MAX_M   = float(os.environ.get("DEPTH_MAX_M", "4.0"))     # metres mapped to depth=1.0 (far)
ENABLE_REID   = os.environ.get("ENABLE_REID", "true").lower() in ("1", "true", "yes")
DETECT_ALL    = os.environ.get("DETECT_ALL", "false").lower() in ("1", "true", "yes")  # prompt-free: detect everything
MASK_POINTS   = int(os.environ.get("MASK_POINTS", "24"))        # polygon points sent per detection (0=off)
CAMERA_KEEPALIVE = float(os.environ.get("CAMERA_KEEPALIVE", "25"))  # secs; re-assert wake+camera
# animals become bosses; everything else in the prompt list becomes an NPC house / prop.
ANIMALS = ["cat", "dog", "bird", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"]
PROPS   = [p.strip() for p in os.environ.get(
    "PROPS", "shoe,slipper,backpack,handbag,bottle,cup,book,ball,potted plant,remote").split(",") if p.strip()]
PROMPTS = ANIMALS + PROPS

S = requests.Session()
S.headers["Authorization"] = f"Bearer {API_KEY}"


def log(*a):
    print("[vision]", *a, flush=True)


# ---- control API helpers --------------------------------------------------
def post_detections(payload: dict) -> None:
    try:
        S.post(f"{API_URL}/api/v1/robots/{ROBOT_ID}/detections", json=payload, timeout=8)
    except requests.RequestException as e:
        log("post failed:", e)


def camera_keepalive() -> None:
    """Keep RTSP alive by re-asserting camera-on. This is a no-op when the robot is already
    streaming (so it won't blip video or trip the drive watchdogs) and gently wakes it when not.
    Deliberately does NOT send `wake` — that forces an RTC rejoin and fights the driving watchdogs."""
    try:
        S.patch(f"{API_URL}/api/v1/robots/{ROBOT_ID}/settings", json={"camera": True}, timeout=8)
    except requests.RequestException as e:
        log("keepalive failed:", e)


# ---- fake mode: synthetic detections (no models) --------------------------
def fake_loop():
    log("FAKE mode — emitting synthetic detections; no models loaded.")
    t0 = time.time()
    while True:
        t = time.time() - t0
        cat_x = 0.35 + 0.15 * math.sin(t * 0.6)
        cat_d = 0.5 + 0.4 * math.sin(t * 0.3)                  # boss walks near/far
        dets = [
            {"label": "cat", "conf": 0.9, "track_id": 1,
             "bbox": [cat_x, 0.32, 0.2, 0.34], "depth": max(0.05, min(1, cat_d))},
            {"label": "dog", "conf": 0.85, "track_id": 3,
             "bbox": [0.62, 0.45, 0.24, 0.4], "depth": 0.6},
            {"label": "shoe", "conf": 0.7, "track_id": 2,
             "bbox": [0.08, 0.64, 0.12, 0.1], "depth": 0.3 + 0.2 * math.sin(t * 0.5)},
        ]
        post_detections({"ts": time.time(), "source_w": 1280, "source_h": 720, "detections": dets})
        time.sleep(1.0 / FPS)


# ---- real mode ------------------------------------------------------------
def real_loop():
    import cv2
    from ultralytics import YOLOE, YOLO

    if DETECT_ALL:
        # prompt-free: run over YOLOE's built-in ~4.5k-class vocabulary — detects everything, no
        # prompt list. Falls back to a text-prompt model if the -pf weight isn't available.
        pf = os.environ.get("SEG_WEIGHTS_PF", "yoloe-26s-seg-pf.pt")
        try:
            log(f"loading {pf} (prompt-free — detect EVERYTHING)…")
            det = YOLOE(pf)
            names = det.names
            log(f"prompt-free vocabulary: {len(names)} classes")
        except Exception as e:
            log("prompt-free load failed, falling back to text prompts:", e)
            det = YOLOE(os.environ.get("SEG_WEIGHTS", "yoloe-26s-seg.pt")); det.set_classes(PROMPTS)
            names = det.names
    else:
        log("loading YOLOE-26s-seg (open-vocab seg)…")
        det = YOLOE(os.environ.get("SEG_WEIGHTS", "yoloe-26s-seg.pt"))
        det.set_classes(PROMPTS)                               # text prompts: animals + props
        names = det.names

    log("loading YOLO26n-depth (metric)…")
    depth = YOLO(os.environ.get("DEPTH_WEIGHTS", "yolo26n-depth.pt"))

    embed = None
    if ENABLE_REID:
        log("loading DINOv2-small re-id embedder…")
        import torch
        from transformers import AutoImageProcessor, AutoModel
        mid = os.environ.get("REID_MODEL", "facebook/dinov2-small")
        proc = AutoImageProcessor.from_pretrained(mid)
        enc = AutoModel.from_pretrained(mid).eval()

        def embed(crop_rgb, mask=None):
            if mask is not None:
                crop_rgb = np.where(mask[..., None], crop_rgb, 128).astype(np.uint8)
            with torch.no_grad():
                e = enc(**proc(images=crop_rgb, return_tensors="pt")).pooler_output[0]
            e = torch.nn.functional.normalize(e, dim=0)
            return e.numpy().astype(float).tolist()

    cap = _open(cv2)
    last_ka = 0.0
    period = 1.0 / FPS
    hb_n, hb_t = 0, time.time()
    while True:
        t0 = time.time()
        if t0 - last_ka > CAMERA_KEEPALIVE:
            camera_keepalive(); last_ka = t0
        ok, frame = cap.read()                                 # BGR
        if not ok or frame is None:
            log("no frame — reopening RTSP in 2s"); time.sleep(2); cap = _open(cv2); continue
        H, W = frame.shape[:2]
        try:
            r = det.track(frame, imgsz=IMGSZ, conf=CONF, persist=True,
                          tracker="botsort.yaml", verbose=False)[0]
        except Exception as e:
            log("detect/track error:", e); time.sleep(0.5); continue

        dets = []
        if r.boxes is not None and len(r.boxes):
            # metric depth once per frame
            try:
                dmap = depth.predict(frame, imgsz=DEPTH_IMGSZ, verbose=False)[0].depth.data
                dmap = dmap.cpu().numpy() if hasattr(dmap, "cpu") else np.asarray(dmap)
                if dmap.shape[:2] != (H, W):
                    dmap = cv2.resize(dmap, (W, H))
            except Exception as e:
                log("depth error:", e); dmap = None

            xyxy = r.boxes.xyxy.cpu().numpy()
            clss = r.boxes.cls.int().cpu().tolist()
            confs = r.boxes.conf.cpu().tolist()
            ids = (r.boxes.id.int().cpu().tolist() if r.boxes.id is not None else [None] * len(clss))
            polys = r.masks.xy if r.masks is not None else [None] * len(clss)     # px polygons
            mdata = r.masks.data.cpu().numpy() if r.masks is not None else None    # (N,mh,mw)

            for i in range(len(clss)):
                x1, y1, x2, y2 = xyxy[i]
                label = names[clss[i]]
                mask_full = None
                if mdata is not None and i < len(mdata):
                    mask_full = cv2.resize((mdata[i] > 0.5).astype(np.uint8), (W, H)) > 0
                depth_n = _depth_of(dmap, mask_full, (x1, y1, x2, y2))
                d = {
                    "label": label,
                    "conf": round(float(confs[i]), 3),
                    "bbox": [round(float(x1) / W, 4), round(float(y1) / H, 4),
                             round(float(x2 - x1) / W, 4), round(float(y2 - y1) / H, 4)],
                    "depth": depth_n,
                    "track_id": ids[i],
                }
                if MASK_POINTS and polys[i] is not None and len(polys[i]) >= 3:
                    d["mask"] = [_simplify(polys[i], W, H, MASK_POINTS)]
                if embed is not None and label in ANIMALS:
                    crop, m = _crop(frame, (x1, y1, x2, y2), mask_full)
                    if crop is not None:
                        try:
                            d["embedding"] = embed(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), m)
                        except Exception as e:
                            log("embed error:", e)
                dets.append(d)

        post_detections({"ts": time.time(), "source_w": W, "source_h": H, "detections": dets})
        hb_n += 1
        if t0 - hb_t >= 5:
            log(f"{hb_n / (t0 - hb_t):.1f} fps · last frame: {len(dets)} detections")
            hb_n, hb_t = 0, t0
        dt = time.time() - t0
        if dt < period:
            time.sleep(period - dt)


class MjpegReader:
    """Read frames from the API's MJPEG proxy — plain JPEGs, so no h264/RTSP decode headaches.
    Exposes the same .read() -> (ok, frame_bgr) contract as cv2.VideoCapture."""
    def __init__(self, url, cv2):
        self.url, self.cv2 = url, cv2
        self._open()

    def _open(self):
        self.r = requests.get(self.url, stream=True, timeout=(5, 30))
        self.it = self.r.iter_content(16384)
        self.buf = b""

    def read(self):
        for _ in range(6000):
            a = self.buf.find(b"\xff\xd8")
            b = self.buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
            if a >= 0 and b >= 0:
                jpg = self.buf[a:b + 2]; self.buf = self.buf[b + 2:]
                img = self.cv2.imdecode(np.frombuffer(jpg, np.uint8), self.cv2.IMREAD_COLOR)
                if img is not None:
                    return True, img
                continue
            try:
                chunk = next(self.it)
            except Exception:
                return False, None
            if not chunk:
                return False, None
            self.buf += chunk
        return False, None


def _open(cv2):
    if VIDEO_SOURCE == "mjpeg":
        url = f"{API_URL}/api/v1/robots/{ROBOT_ID}/stream/mjpeg?token={API_KEY}"
        log("video source: MJPEG", url.split("?")[0])
        return MjpegReader(url, cv2)
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    log("video source: RTSP", RTSP_URL, "opened" if cap.isOpened() else "FAILED (will retry)")
    return cap


def _depth_of(dmap, mask, box):
    if dmap is None:
        return None
    if mask is not None and mask.any():
        z = float(np.median(dmap[mask]))
    else:
        x1, y1, x2, y2 = [int(v) for v in box]
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        h, w = dmap.shape[:2]
        z = float(dmap[max(0, min(h - 1, cy)), max(0, min(w - 1, cx))])
    return round(max(0.0, min(1.0, z / DEPTH_MAX_M)), 4)         # metres → 0(near)..1(far)


def _crop(frame, box, mask):
    x1, y1, x2, y2 = [int(v) for v in box]
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None, None
    crop = frame[y1:y2, x1:x2]
    m = mask[y1:y2, x1:x2] if mask is not None else None
    return crop, m


def _simplify(poly, W, H, n):
    import cv2
    p = np.asarray(poly, dtype=np.float32)
    if len(p) > n:
        eps = 0.01 * cv2.arcLength(p.reshape(-1, 1, 2), True)
        p = cv2.approxPolyDP(p.reshape(-1, 1, 2), eps, True).reshape(-1, 2)
    return [[round(float(x) / W, 4), round(float(y) / H, 4)] for x, y in p[:n]]


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("set EBO_API_KEY")
    log(f"mode={MODE} rtsp={RTSP_URL} api={API_URL} robot={ROBOT_ID} fps={FPS} reid={ENABLE_REID}")
    log("prompts:", ", ".join(PROMPTS))
    (fake_loop if MODE == "fake" else real_loop)()
