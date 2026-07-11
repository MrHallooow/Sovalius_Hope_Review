/**
 * Pure helpers for the bbox-overlay canvas player (Phase 3 CPU-erasure,
 * review side). No DOM, no React — safe to unit test directly under Node.
 *
 * tracks.json sidecar schema (version 1), shipped by the rack next to
 * clip_raw.mp4:
 *   {
 *     version: 1,
 *     ai_resolution: [w, h],        // bbox coordinate space (pipeline dims)
 *     clip_start_pts_ns: <int>,     // source PTS of clip_raw.mp4 t=0
 *     fps: <float>,
 *     violation_track_id: <int|null>,
 *     frames: [{ pts_ns, tracks: [{ id, bbox:[x1,y1,x2,y2], speed_mph, plate, lane }] }]
 *   }
 *
 * Video-time mapping: t_sec = (pts_ns - clip_start_pts_ns) / 1e9. `frames` is
 * ascending by pts_ns; gaps are allowed. At a given playback time we render
 * the frame with the largest t_sec <= currentTime (no interpolation, v1).
 */

/** Validate + normalize a parsed tracks.json payload. Returns null for
 * anything that doesn't match the version-1 shape closely enough to render
 * — callers treat null exactly like "sidecar absent" (older evidence). */
export function parseTracksSidecar(data) {
  if (!data || typeof data !== "object") return null;
  if (data.version !== 1) return null;
  if (!Array.isArray(data.frames)) return null;
  if (
    !Array.isArray(data.ai_resolution) ||
    data.ai_resolution.length !== 2 ||
    !data.ai_resolution.every((n) => typeof n === "number" && n > 0)
  ) {
    return null;
  }
  if (typeof data.clip_start_pts_ns !== "number") return null;
  return data;
}

/** Seconds since clip_raw.mp4's t=0 for a given source PTS. */
export function ptsToSeconds(ptsNs, clipStartPtsNs) {
  return (ptsNs - clipStartPtsNs) / 1e9;
}

/**
 * Binary search `frames` (ascending pts_ns) for the index of the entry with
 * the largest t_sec <= tSec. Returns -1 if tSec is before every frame (or
 * frames is empty).
 */
export function findFrameIndexAtTime(frames, clipStartPtsNs, tSec) {
  if (!Array.isArray(frames) || frames.length === 0) return -1;
  let lo = 0;
  let hi = frames.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const t = ptsToSeconds(frames[mid].pts_ns, clipStartPtsNs);
    if (t <= tSec) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}

/** Convenience wrapper: the frame object itself (or null). */
export function findFrameAtTime(frames, clipStartPtsNs, tSec) {
  const idx = findFrameIndexAtTime(frames, clipStartPtsNs, tSec);
  return idx === -1 ? null : frames[idx];
}

/**
 * The letterbox/pillarbox rectangle (in element-local pixels) where the
 * media actually renders inside a `containerW x containerH` box under
 * object-fit:contain — i.e. the "content box" bbox coordinates must be
 * scaled into. object-fit:cover is also supported for completeness.
 */
export function computeContentBox(containerW, containerH, mediaW, mediaH, objectFit = "contain") {
  if (!mediaW || !mediaH || !containerW || !containerH) {
    return { x: 0, y: 0, width: containerW || 0, height: containerH || 0 };
  }
  const containerRatio = containerW / containerH;
  const mediaRatio = mediaW / mediaH;
  const widerThanMedia = objectFit === "cover" ? containerRatio < mediaRatio : containerRatio > mediaRatio;
  if (widerThanMedia) {
    // Container is relatively wider than the media -> pillarbox left/right
    // (contain) or the media overflows top/bottom, cropped (cover).
    const height = containerH;
    const width = containerH * mediaRatio;
    return { x: (containerW - width) / 2, y: 0, width, height };
  }
  // Container is relatively taller -> letterbox top/bottom (contain) or the
  // media overflows left/right, cropped (cover).
  const width = containerW;
  const height = containerW / mediaRatio;
  return { x: 0, y: (containerH - height) / 2, width, height };
}

/**
 * Scale a [x1,y1,x2,y2] bbox from `sourceResolution` ([w,h], the pipeline's
 * ai_resolution) into `box` (an element-local rect from computeContentBox).
 */
export function scaleBBoxToBox(bbox, sourceResolution, box) {
  const [x1, y1, x2, y2] = bbox;
  const [srcW, srcH] = sourceResolution;
  const sx = box.width / srcW;
  const sy = box.height / srcH;
  return [box.x + x1 * sx, box.y + y1 * sy, box.x + x2 * sx, box.y + y2 * sy];
}

/** Human-friendly label for a track, or "" if it has nothing worth showing. */
export function trackLabel(track) {
  if (!track) return "";
  const parts = [];
  if (track.plate) parts.push(String(track.plate));
  if (track.speed_mph != null) parts.push(`${Math.round(track.speed_mph)} mph`);
  if (track.lane) parts.push(String(track.lane));
  return parts.join(" · ");
}
