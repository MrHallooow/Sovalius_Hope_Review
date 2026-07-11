import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseTracksSidecar,
  ptsToSeconds,
  findFrameIndexAtTime,
  findFrameAtTime,
  computeContentBox,
  scaleBBoxToBox,
  trackLabel,
} from "./overlayMath.mjs";

test("ptsToSeconds converts source PTS relative to clip start", () => {
  assert.equal(ptsToSeconds(5_000_000_000, 2_000_000_000), 3);
  assert.equal(ptsToSeconds(2_000_000_000, 2_000_000_000), 0);
  assert.equal(ptsToSeconds(1_000_000_000, 2_000_000_000), -1);
});

test("parseTracksSidecar accepts a well-formed v1 payload", () => {
  const data = {
    version: 1,
    ai_resolution: [3840, 2160],
    clip_start_pts_ns: 1000,
    fps: 25,
    violation_track_id: 7,
    frames: [],
  };
  assert.equal(parseTracksSidecar(data), data);
});

test("parseTracksSidecar rejects malformed / absent payloads", () => {
  assert.equal(parseTracksSidecar(null), null);
  assert.equal(parseTracksSidecar(undefined), null);
  assert.equal(parseTracksSidecar("not json"), null);
  assert.equal(parseTracksSidecar({ version: 2, frames: [] }), null); // wrong version
  assert.equal(parseTracksSidecar({ version: 1 }), null); // no frames
  assert.equal(parseTracksSidecar({ version: 1, frames: "nope" }), null);
  assert.equal(
    parseTracksSidecar({ version: 1, frames: [], ai_resolution: [0, 0], clip_start_pts_ns: 0 }),
    null
  );
  assert.equal(parseTracksSidecar({ version: 1, frames: [], ai_resolution: [3840, 2160] }), null); // no clip_start_pts_ns
});

const FRAMES = [
  { pts_ns: 1_000_000_000, tracks: [{ id: 1 }] },
  { pts_ns: 1_040_000_000, tracks: [{ id: 2 }] },
  { pts_ns: 1_080_000_000, tracks: [{ id: 3 }] },
  { pts_ns: 1_200_000_000, tracks: [{ id: 4 }] }, // gap between 1.08s and 1.2s
];
const CLIP_START = 1_000_000_000; // frame times: 0, 0.04, 0.08, 0.2

test("findFrameIndexAtTime returns -1 before the first frame", () => {
  assert.equal(findFrameIndexAtTime(FRAMES, CLIP_START, -1), -1);
  assert.equal(findFrameIndexAtTime([], CLIP_START, 5), -1);
  assert.equal(findFrameIndexAtTime(undefined, CLIP_START, 5), -1);
});

test("findFrameIndexAtTime finds the exact frame at its own timestamp", () => {
  assert.equal(findFrameIndexAtTime(FRAMES, CLIP_START, 0), 0);
  assert.equal(findFrameIndexAtTime(FRAMES, CLIP_START, 0.04), 1);
  assert.equal(findFrameIndexAtTime(FRAMES, CLIP_START, 0.08), 2);
  assert.equal(findFrameIndexAtTime(FRAMES, CLIP_START, 0.2), 3);
});

test("findFrameIndexAtTime holds the last frame across a gap (no interpolation)", () => {
  // Between 0.08s (frame 2) and 0.2s (frame 3) there is no frame — the
  // contract says render the frame with the largest t <= currentTime.
  assert.equal(findFrameIndexAtTime(FRAMES, CLIP_START, 0.1), 2);
  assert.equal(findFrameIndexAtTime(FRAMES, CLIP_START, 0.15), 2);
});

test("findFrameIndexAtTime holds the final frame past the end of the clip", () => {
  assert.equal(findFrameIndexAtTime(FRAMES, CLIP_START, 999), 3);
});

test("findFrameAtTime returns the frame object (or null)", () => {
  assert.equal(findFrameAtTime(FRAMES, CLIP_START, -1), null);
  assert.deepEqual(findFrameAtTime(FRAMES, CLIP_START, 0.1), FRAMES[2]);
});

test("computeContentBox: media narrower than container -> pillarboxed left/right", () => {
  // 1920x1080 container, 3840x2160 (16:9) media at exactly the same ratio
  // should fill the box with no bars.
  const box = computeContentBox(1920, 1080, 3840, 2160);
  assert.deepEqual(box, { x: 0, y: 0, width: 1920, height: 1080 });
});

test("computeContentBox: wide container + taller-relative media -> pillarbox", () => {
  // Container is a wide 1000x400 (2.5:1); media is 4:3 (narrower) -> bars L/R.
  const box = computeContentBox(1000, 400, 1600, 1200);
  assert.equal(box.height, 400);
  assert.equal(box.width, 400 * (1600 / 1200));
  assert.ok(box.x > 0);
  assert.equal(box.y, 0);
});

test("computeContentBox: tall container + wide-relative media -> letterbox top/bottom", () => {
  // Container is a tall 400x1000 (0.4:1); media is 16:9 (wider) -> bars T/B.
  const box = computeContentBox(400, 1000, 1920, 1080);
  assert.equal(box.width, 400);
  assert.equal(box.height, 400 / (1920 / 1080));
  assert.equal(box.x, 0);
  assert.ok(box.y > 0);
});

test("computeContentBox is defensive against zero/missing dimensions", () => {
  assert.deepEqual(computeContentBox(0, 500, 100, 100), { x: 0, y: 0, width: 0, height: 500 });
  assert.deepEqual(computeContentBox(500, 500, 0, 0), { x: 0, y: 0, width: 500, height: 500 });
});

test("scaleBBoxToBox maps ai_resolution-space coordinates into the content box", () => {
  // Full-frame box, no letterboxing: a half-frame bbox in 3840x2160 space
  // should land at exactly half the rendered box.
  const box = { x: 0, y: 0, width: 1920, height: 1080 };
  const scaled = scaleBBoxToBox([0, 0, 1920, 1080], [3840, 2160], box);
  assert.deepEqual(scaled, [0, 0, 960, 540]);
});

test("scaleBBoxToBox accounts for the content box's own offset (letterboxing)", () => {
  const box = { x: 100, y: 0, width: 800, height: 450 }; // pillarboxed by 100px
  const scaled = scaleBBoxToBox([0, 0, 3840, 2160], [3840, 2160], box);
  assert.deepEqual(scaled, [100, 0, 900, 450]);
});

test("trackLabel joins the present fields and skips absent ones", () => {
  assert.equal(trackLabel({ plate: "SVG-123", speed_mph: 47.6, lane: "L1" }), "SVG-123 · 48 mph · L1");
  assert.equal(trackLabel({ plate: null, speed_mph: null, lane: null }), "");
  assert.equal(trackLabel({ speed_mph: 30 }), "30 mph");
  assert.equal(trackLabel(null), "");
});
