import React, { useState, useEffect, useRef, useCallback } from "react";
import { getCameraLanes, getAllCameraLanes, saveCameraLanes } from "../services/dbApi.js";

const ZONE_TYPES = [
  { value: "lane", label: "Lane", subtypes: ["traffic_lane","bus_lane","bike_lane","hov_lane","emergency_lane"] },
  { value: "virtual_line", label: "Virtual Line", subtypes: ["stop_line","counting_line","speed_detection","trip_wire"] },
  { value: "detection_zone", label: "Detection Zone", subtypes: ["general","intersection","parking_area","restricted","queue_detection"] },
  { value: "pedestrian_crossing", label: "Pedestrian Crossing", subtypes: [] },
  { value: "no_parking", label: "No Parking Zone", subtypes: [] },
];

const ZONE_FILLS = {
  traffic_lane: "rgba(0,200,0,0.15)", bus_lane: "rgba(255,165,0,0.15)", bike_lane: "rgba(0,255,255,0.15)",
  hov_lane: "rgba(200,0,255,0.15)", emergency_lane: "rgba(255,0,0,0.15)",
  stop_line: "rgba(255,255,255,0.1)", counting_line: "rgba(255,255,255,0.1)", speed_detection: "rgba(255,255,0,0.1)", trip_wire: "rgba(0,255,255,0.1)",
  general: "rgba(128,128,128,0.15)", intersection: "rgba(0,200,0,0.15)", parking_area: "rgba(200,0,255,0.15)", restricted: "rgba(255,165,0,0.15)", queue_detection: "rgba(255,255,0,0.15)",
  pedestrian_crossing: "rgba(255,255,255,0.2)", no_parking: "rgba(255,0,0,0.2)",
};

const ZONE_STROKES = {
  traffic_lane: "#00c800", bus_lane: "#ffa500", bike_lane: "#00ffff",
  hov_lane: "#c800ff", emergency_lane: "#ff0000",
  stop_line: "#ffffff", counting_line: "#ffffff", speed_detection: "#ffff00", trip_wire: "#00ffff",
  general: "#888", intersection: "#0c0", parking_area: "#c0f", restricted: "#fa0", queue_detection: "#ff0",
  pedestrian_crossing: "#fff", no_parking: "#f44",
};

const LINE_COLORS = { white: "#ffffff", yellow: "#ffff00", blue: "#6696ff" };
const LINE_TYPES = ["solid", "dashed", "double_solid", "double_dashed"];
const DIRECTIONS = ["forward", "backward", "unknown"];
const PURPOSES = ["general","turning_left","turning_right","merging","exit","entry","through","acceleration","deceleration"];
const VEHICLES = ["all","buses_only","bicycles_only","hov_2plus","hov_3plus","emergency_only","taxis","authorized"];

const Glass = ({ children, style }) => (
  <div style={{
    background: "rgba(255,255,255,.03)",
    backdropFilter: "blur(24px)",
    WebkitBackdropFilter: "blur(24px)",
    borderRadius: 16,
    border: "1px solid rgba(255,255,255,.06)",
    ...style,
  }}>{children}</div>
);

function pointInPolygon(px, py, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}

function centroid(pts) {
  if (!pts || !pts.length) return [0.5, 0.5];
  return [
    pts.reduce((s, p) => s + p[0], 0) / pts.length,
    pts.reduce((s, p) => s + p[1], 0) / pts.length,
  ];
}

function offsetPolyline(pts, off) {
  return pts.map((p, i) => {
    const next = pts[Math.min(i + 1, pts.length - 1)];
    const prev = pts[Math.max(i - 1, 0)];
    const dx = next[0] - prev[0], dy = next[1] - prev[1];
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    return [p[0] + (-dy / len) * off, p[1] + (dx / len) * off];
  });
}

function distToSegment(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.sqrt((px - x1) ** 2 + (py - y1) ** 2);
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lenSq));
  return Math.sqrt((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2);
}

function snapToPolygonEdge(point, polygon, snapDist = 0.025) {
  if (!polygon || polygon.length < 2) return point;
  const [px, py] = point;
  let best = point, bestD = Infinity;
  for (let i = 0; i < polygon.length; i++) {
    const [x1, y1] = polygon[i];
    const [x2, y2] = polygon[(i + 1) % polygon.length];
    const dx = x2 - x1, dy = y2 - y1;
    const lenSq = dx * dx + dy * dy;
    if (lenSq === 0) continue;
    const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lenSq));
    const nx = x1 + t * dx, ny = y1 + t * dy;
    const d = Math.sqrt((px - nx) ** 2 + (py - ny) ** 2);
    if (d < bestD) { bestD = d; best = [nx, ny]; }
  }
  return bestD <= snapDist ? best : point;
}

function getPolygonXAtY(polygon, y) {
  const xs = [];
  for (let i = 0; i < polygon.length; i++) {
    const [x1, y1] = polygon[i];
    const [x2, y2] = polygon[(i + 1) % polygon.length];
    if ((y1 <= y && y <= y2) || (y2 <= y && y <= y1)) {
      if (y1 === y2) { xs.push(x1, x2); }
      else { xs.push(x1 + (y - y1) / (y2 - y1) * (x2 - x1)); }
    }
  }
  return xs;
}

function getPolylineXAtY(polyline, y) {
  for (let i = 0; i < polyline.length - 1; i++) {
    const [x1, y1] = polyline[i];
    const [x2, y2] = polyline[i + 1];
    if ((y1 <= y && y <= y2) || (y2 <= y && y <= y1)) {
      if (y1 === y2) return (x1 + x2) / 2;
      return x1 + (y - y1) / (y2 - y1) * (x2 - x1);
    }
  }
  return null;
}

function splitRoadIntoSections(road, dividerList) {
  if (!road || road.length < 3) return [];
  const dividers = dividerList.filter(d => d.length >= 2)
    .sort((a, b) => {
      const avgA = a.reduce((s, p) => s + p[0], 0) / a.length;
      const avgB = b.reduce((s, p) => s + p[0], 0) / b.length;
      return avgA - avgB;
    });
  if (!dividers.length) return [road.slice()];

  const ys = road.map(p => p[1]);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const yRange = maxY - minY;
  if (yRange < 1e-6) return [road.slice()];

  const divTops = [], divBots = [];
  for (const d of dividers) {
    if (d[0][1] < d[d.length - 1][1]) { divTops.push(d[0]); divBots.push(d[d.length - 1]); }
    else { divTops.push(d[d.length - 1]); divBots.push(d[0]); }
  }

  const topThresh = minY + yRange * 0.25, botThresh = maxY - yRange * 0.25;
  let topPts = road.filter(p => p[1] <= topThresh);
  let botPts = road.filter(p => p[1] >= botThresh);
  if (topPts.length < 2) topPts = [...road].sort((a, b) => a[1] - b[1]).slice(0, 2);
  if (botPts.length < 2) botPts = [...road].sort((a, b) => b[1] - a[1]).slice(0, 2);
  const TL = [...topPts].sort((a, b) => a[0] - b[0])[0];
  const TR = [...topPts].sort((a, b) => b[0] - a[0])[0];
  const BL = [...botPts].sort((a, b) => a[0] - b[0])[0];
  const BR = [...botPts].sort((a, b) => b[0] - a[0])[0];

  const numScan = 60;
  const step = yRange / (numScan + 1);
  const scanYSet = new Set();
  for (let i = 1; i <= numScan; i++) scanYSet.add(minY + step * i);
  [0.1, 0.3].forEach(f => { scanYSet.add(minY + step * f); scanYSet.add(maxY - step * f); });
  const sortedYs = [...scanYSet].sort((a, b) => a - b);

  const scanData = [];
  for (const y of sortedYs) {
    const bxs = getPolygonXAtY(road, y);
    if (bxs.length < 2) continue;
    const left = Math.min(...bxs), right = Math.max(...bxs);
    const row = [left];
    for (const d of dividers) {
      const dx = getPolylineXAtY(d, y);
      if (dx !== null && dx >= left && dx <= right) row.push(dx);
    }
    row.push(right);
    row.sort((a, b) => a - b);
    if (row.length >= 2) scanData.push({ y, xs: row });
  }
  if (scanData.length < 2) return [road.slice()];

  const numSections = dividers.length + 1;
  const sections = [];
  for (let si = 0; si < numSections; si++) {
    const lPts = [], rPts = [];
    const isFirst = si === 0, isLast = si === numSections - 1;
    if (isFirst && TL) lPts.push(TL); else if (si - 1 >= 0 && si - 1 < divTops.length) lPts.push(divTops[si - 1]);
    if (si < divTops.length) rPts.push(divTops[si]); else if (isLast && TR) rPts.push(TR);
    for (const { y, xs } of scanData) {
      if (si < xs.length - 1) { lPts.push([xs[si], y]); rPts.push([xs[si + 1], y]); }
    }
    if (isFirst && BL) lPts.push(BL); else if (si - 1 >= 0 && si - 1 < divBots.length) lPts.push(divBots[si - 1]);
    if (si < divBots.length) rPts.push(divBots[si]); else if (isLast && BR) rPts.push(BR);

    if (lPts.length >= 2 && rPts.length >= 2) {
      lPts.sort((a, b) => a[1] - b[1]);
      rPts.sort((a, b) => a[1] - b[1]);
      const poly = [...lPts, ...rPts.reverse()];
      const cleaned = [poly[0]];
      for (let i = 1; i < poly.length; i++) {
        const prev = cleaned[cleaned.length - 1];
        if (Math.abs(poly[i][0] - prev[0]) > 1e-6 || Math.abs(poly[i][1] - prev[1]) > 1e-6)
          cleaned.push(poly[i]);
      }
      if (cleaned.length >= 3) sections.push(cleaned);
    }
  }
  return sections;
}

const SECTION_PALETTE = [
  "rgba(76,175,80,0.3)", "rgba(33,150,243,0.3)", "rgba(255,152,0,0.3)",
  "rgba(156,39,176,0.3)", "rgba(244,67,54,0.3)", "rgba(0,188,212,0.3)",
  "rgba(255,235,59,0.3)", "rgba(121,85,72,0.3)",
];
const SECTION_STROKES = [
  "#4caf50", "#2196f3", "#ff9800", "#9c27b0", "#f44336", "#00bcd4", "#ffeb3b", "#795548",
];

export default function LaneConfigTab({ cameras: propCameras, theme: t }) {
  const aC = t.aC || "#6366f1";

  const [dbCameras, setDbCameras] = useState([]);
  const cameras = (() => {
    const seen = new Set();
    const merged = [];
    for (const c of (propCameras || [])) {
      if (!seen.has(c.name)) { seen.add(c.name); merged.push(c); }
    }
    for (const c of dbCameras) {
      if (!seen.has(c.name)) { seen.add(c.name); merged.push(c); }
    }
    return merged;
  })();

  const [camera, setCamera] = useState("");
  const [zones, setZones] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [mode, setMode] = useState("select");
  const [drawType, setDrawType] = useState("lane");
  const [drawSubtype, setDrawSubtype] = useState("traffic_lane");
  const [currentPoints, setCurrentPoints] = useState([]);
  const [history, setHistory] = useState([[]]);
  const [historyIdx, setHistoryIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [calWidth, setCalWidth] = useState(1920);
  const [calHeight, setCalHeight] = useState(1080);
  const [dragPointIdx, setDragPointIdx] = useState(null);
  const [dragZoneId, setDragZoneId] = useState(null);
  const [bgFrameUrl, setBgFrameUrl] = useState(null);

  const [roadBoundary, setRoadBoundary] = useState([]);
  const [laneDividers, setLaneDividers] = useState([]);
  const [generatedSections, setGeneratedSections] = useState([]);
  const [drawPhase, setDrawPhase] = useState(null);
  const [currentRoadPoints, setCurrentRoadPoints] = useState([]);
  const [currentDividerPoints, setCurrentDividerPoints] = useState([]);
  const [hoveredSection, setHoveredSection] = useState(null);

  const svgRef = useRef(null);
  const isDragging = useRef(false);
  const zonesRef = useRef(zones);
  zonesRef.current = zones;

  const histRef = useRef({ stack: [[]], idx: 0 });

  const syncHistState = useCallback(() => {
    const h = histRef.current;
    setHistory([...h.stack]);
    setHistoryIdx(h.idx);
  }, []);

  const pushHistory = useCallback((newZones) => {
    const h = histRef.current;
    h.stack = h.stack.slice(0, h.idx + 1);
    h.stack.push(JSON.parse(JSON.stringify(newZones)));
    h.idx = h.stack.length - 1;
    setZones(newZones);
    syncHistState();
  }, [syncHistState]);

  const undo = useCallback(() => {
    const h = histRef.current;
    if (h.idx <= 0) return;
    h.idx--;
    setZones(JSON.parse(JSON.stringify(h.stack[h.idx])));
    syncHistState();
  }, [syncHistState]);

  const redo = useCallback(() => {
    const h = histRef.current;
    if (h.idx >= h.stack.length - 1) return;
    h.idx++;
    setZones(JSON.parse(JSON.stringify(h.stack[h.idx])));
    syncHistState();
  }, [syncHistState]);

  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if (
        (e.ctrlKey || e.metaKey) && (e.key === "y" || (e.key === "z" && e.shiftKey))
      ) {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [undo, redo]);

  const inputStyle = {
    width: "100%", boxSizing: "border-box",
    background: "rgba(0,0,0,0.3)",
    border: `1px solid ${t.iBo || "rgba(255,255,255,0.1)"}`,
    borderRadius: 6, color: t.tx || "#fff",
    padding: "5px 8px", fontSize: 12, outline: "none",
    fontFamily: "inherit",
  };
  const selectStyle = { ...inputStyle, WebkitAppearance: "none", MozAppearance: "none" };
  const labelSt = { fontSize: 11, color: t.tD || "rgba(255,255,255,0.5)", marginBottom: 3 };
  const btnBase = { borderRadius: 8, cursor: "pointer", fontSize: 12, fontWeight: 500, transition: "all .15s ease", fontFamily: "inherit" };
  const btn = (active) => ({
    ...btnBase, padding: "6px 12px",
    border: active ? `1px solid ${aC}` : `1px solid ${t.iBo || "rgba(255,255,255,0.1)"}`,
    background: active ? `${aC}22` : "rgba(255,255,255,0.04)",
    color: active ? aC : (t.tx || "#fff"),
  });
  const btnSm = (disabled) => ({
    ...btnBase, padding: "4px 10px",
    border: `1px solid ${t.iBo || "rgba(255,255,255,0.1)"}`,
    background: "rgba(255,255,255,0.04)",
    color: disabled ? (t.tF || "rgba(255,255,255,0.2)") : (t.tx || "#fff"),
    opacity: disabled ? 0.5 : 1,
    cursor: disabled ? "not-allowed" : "pointer",
  });

  useEffect(() => {
    getAllCameraLanes().then(res => {
      if (res?.ok && res.rows?.length) {
        setDbCameras(res.rows.map(r => ({ id: r.camera_name, name: r.camera_name })));
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (cameras?.length && !camera) {
      setCamera(cameras[0].name);
    } else if (cameras?.length && !cameras.find(c => c.name === camera)) {
      setCamera(cameras[0].name);
    }
  }, [cameras, camera]);

  useEffect(() => {
    if (!camera) return;
    setLoading(true);
    getCameraLanes(camera)
      .then(res => {
        const newZones = [];
        if (res?.ok && res.data) {
          const ld = typeof res.data.lane_data === "string"
            ? JSON.parse(res.data.lane_data)
            : (res.data.lane_data || {});
          let idx = 0;
          const mk = (z, zoneType, defaultSub) => {
            const obj = {
              id: z.id ?? idx, type: zoneType,
              subtype: z.type || defaultSub,
              name: z.name || `Zone ${idx + 1}`,
              direction: z.direction_name || "unknown",
              points: z.normalized_boundaries || [],
              leftLineType: z.left_line_type || "solid",
              rightLineType: z.right_line_type || "solid",
              lineColor: z.line_color || "white",
              speedLimit: z.speed_limit_mph || 0,
              allowsOvertaking: z.allows_overtaking ?? true,
              purpose: z.lane_purpose || "general",
              allowedVehicles: z.allowed_vehicles || "all",
              notes: z.notes || "",
            };
            idx++;
            return obj;
          };
          (ld.lanes || []).forEach(z => newZones.push(mk(z, "lane", "traffic_lane")));
          (ld.stop_lines || []).forEach(z => newZones.push(mk(z, "virtual_line", "stop_line")));
          (ld.crossings || []).forEach(z => newZones.push(mk(z, "pedestrian_crossing", "pedestrian_crossing")));
          (ld.detection_zones || []).forEach(z => newZones.push(mk(z, "detection_zone", "general")));
          (ld.no_parking_zones || []).forEach(z => newZones.push(mk(z, "no_parking", "no_parking")));
          if (res.data.calibration_width) setCalWidth(res.data.calibration_width);
          if (res.data.calibration_height) setCalHeight(res.data.calibration_height);
          setBgFrameUrl(res.data.background_frame_presigned || null);
        } else {
          setBgFrameUrl(null);
        }
        setZones(newZones);
        const snap = JSON.parse(JSON.stringify(newZones));
        histRef.current = { stack: [snap], idx: 0 };
        syncHistState();
        setSelectedId(null);
        setCurrentPoints([]);
        setMode("select");
        setDrawPhase(null);
        setRoadBoundary([]);
        setLaneDividers([]);
        setGeneratedSections([]);
        setCurrentRoadPoints([]);
        setCurrentDividerPoints([]);
        setHoveredSection(null);
        setLoading(false);
      })
      .catch(() => {
        setZones([]);
        setBgFrameUrl(null);
        histRef.current = { stack: [[]], idx: 0 };
        syncHistState();
        setLoading(false);
      });
  }, [camera, syncHistState]);

  useEffect(() => {
    if (mode !== "draw") {
      setCurrentPoints([]);
      setDrawPhase(null);
      setCurrentRoadPoints([]);
      setCurrentDividerPoints([]);
    }
  }, [mode]);

  useEffect(() => {
    const handleUp = () => {
      if (dragPointIdx !== null) {
        if (isDragging.current) {
          pushHistory(zonesRef.current);
        }
        setDragPointIdx(null);
        setDragZoneId(null);
        isDragging.current = false;
      }
    };
    window.addEventListener("mouseup", handleUp);
    return () => window.removeEventListener("mouseup", handleUp);
  }, [dragPointIdx, pushHistory]);

  const getSvgPoint = useCallback((e) => {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const rect = svg.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    ];
  }, []);

  const handleSvgClick = useCallback((e) => {
    if (isDragging.current) { isDragging.current = false; return; }
    const [x, y] = getSvgPoint(e);

    if (drawPhase === "road") {
      setCurrentRoadPoints(prev => [...prev, [x, y]]);
      return;
    }
    if (drawPhase === "divider") {
      setCurrentDividerPoints(prev => {
        if (prev.length === 0) return [snapToPolygonEdge([x, y], roadBoundary)];
        return [...prev, [x, y]];
      });
      return;
    }
    if (drawPhase === "assign") return;

    if (mode === "draw") {
      setCurrentPoints(prev => [...prev, [x, y]]);
    } else if (mode === "select" || mode === "edit") {
      const clicked = [...zones].reverse().find(z => {
        if (z.points.length >= 3) return pointInPolygon(x, y, z.points);
        if (z.points.length === 2) {
          return distToSegment(x, y, z.points[0][0], z.points[0][1], z.points[1][0], z.points[1][1]) < 0.015;
        }
        return false;
      });
      setSelectedId(clicked ? clicked.id : null);
    }
  }, [mode, zones, getSvgPoint, drawPhase, roadBoundary]);

  const handleSvgMouseMove = useCallback((e) => {
    if (dragPointIdx === null || dragZoneId === null) return;
    isDragging.current = true;
    const [x, y] = getSvgPoint(e);
    setZones(prev => prev.map(z => {
      if (z.id !== dragZoneId) return z;
      return { ...z, points: z.points.map((p, i) => i === dragPointIdx ? [x, y] : p) };
    }));
  }, [dragPointIdx, dragZoneId, getSvgPoint]);

  const completeDrawing = useCallback(() => {
    if (currentPoints.length < 3) return;
    const newId = zones.length ? Math.max(...zones.map(z => z.id)) + 1 : 1;
    const zt = ZONE_TYPES.find(z => z.value === drawType);
    const newZone = {
      id: newId, type: drawType,
      subtype: drawSubtype || zt?.subtypes?.[0] || drawType,
      name: `${zt?.label || drawType} ${newId}`,
      direction: "unknown", points: [...currentPoints],
      leftLineType: "solid", rightLineType: "solid", lineColor: "white",
      speedLimit: 0, allowsOvertaking: true, purpose: "general",
      allowedVehicles: "all", notes: "",
    };
    pushHistory([...zones, newZone]);
    setCurrentPoints([]);
    setSelectedId(newId);
    setMode("select");
  }, [currentPoints, zones, drawType, drawSubtype, pushHistory]);

  const completeRoadBoundary = useCallback(() => {
    if (currentRoadPoints.length < 4) return;
    setRoadBoundary([...currentRoadPoints]);
    setCurrentRoadPoints([]);
    setGeneratedSections([]);
    setDrawPhase("divider");
  }, [currentRoadPoints]);

  const completeDivider = useCallback(() => {
    if (currentDividerPoints.length < 2) return;
    const pts = [...currentDividerPoints];
    pts[pts.length - 1] = snapToPolygonEdge(pts[pts.length - 1], roadBoundary);
    setLaneDividers(prev => [...prev, pts]);
    setCurrentDividerPoints([]);
    setGeneratedSections([]);
  }, [currentDividerPoints, roadBoundary]);

  const removeDivider = useCallback((idx) => {
    setLaneDividers(prev => prev.filter((_, i) => i !== idx));
    setGeneratedSections([]);
  }, []);

  const handleGenerateSections = useCallback(() => {
    if (!roadBoundary.length) return;
    const sections = splitRoadIntoSections(roadBoundary, laneDividers);
    setGeneratedSections(sections);
    setDrawPhase("assign");
    setCurrentDividerPoints([]);
  }, [roadBoundary, laneDividers]);

  const assignSection = useCallback((idx) => {
    const sectionPoly = generatedSections[idx];
    if (!sectionPoly) return;
    const newId = zones.length ? Math.max(...zones.map(z => z.id)) + 1 : 1;
    const newLane = {
      id: newId, type: "lane", subtype: "traffic_lane",
      name: `Lane ${newId}`, direction: "unknown",
      points: sectionPoly,
      leftLineType: "solid", rightLineType: "solid", lineColor: "white",
      speedLimit: 0, allowsOvertaking: true, purpose: "general",
      allowedVehicles: "all", notes: "",
    };
    pushHistory([...zones, newLane]);
    setSelectedId(newId);
    const remaining = generatedSections.filter((_, i) => i !== idx);
    setGeneratedSections(remaining);
    if (remaining.length === 0) {
      setDrawPhase(null);
      setRoadBoundary([]);
      setLaneDividers([]);
      setMode("select");
    }
  }, [generatedSections, zones, pushHistory]);

  const clearRoadState = useCallback(() => {
    setDrawPhase(null);
    setRoadBoundary([]);
    setLaneDividers([]);
    setGeneratedSections([]);
    setCurrentRoadPoints([]);
    setCurrentDividerPoints([]);
    setHoveredSection(null);
  }, []);

  const deleteZone = useCallback(() => {
    if (selectedId === null) return;
    pushHistory(zones.filter(z => z.id !== selectedId));
    setSelectedId(null);
  }, [selectedId, zones, pushHistory]);

  const clearAll = useCallback(() => {
    pushHistory([]);
    setSelectedId(null);
  }, [pushHistory]);

  const updateZoneProp = useCallback((prop, value) => {
    if (selectedId === null) return;
    pushHistory(zones.map(z => z.id === selectedId ? { ...z, [prop]: value } : z));
  }, [selectedId, zones, pushHistory]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const lanes = [], stop_lines = [], crossings = [], detection_zones = [], no_parking_zones = [];
      for (const z of zonesRef.current) {
        const base = { id: z.id, name: z.name, type: z.subtype, normalized_boundaries: z.points, notes: z.notes };
        if (z.type === "lane") {
          const half = Math.ceil(z.points.length / 2);
          const lp = z.points.slice(0, half);
          const rp = [...z.points.slice(half)].reverse();
          const cp = lp.map((l, i) => {
            const r = rp[i] || rp[rp.length - 1] || l;
            return [(l[0] + r[0]) / 2, (l[1] + r[1]) / 2];
          });
          lanes.push({
            ...base, direction_name: z.direction,
            left_points: lp, right_points: rp, center_points: cp,
            left_line_type: z.leftLineType, right_line_type: z.rightLineType,
            line_color: z.lineColor, speed_limit_mph: z.speedLimit,
            allows_overtaking: z.allowsOvertaking, lane_purpose: z.purpose,
            allowed_vehicles: z.allowedVehicles,
          });
        } else if (z.type === "virtual_line") { stop_lines.push(base); }
        else if (z.type === "pedestrian_crossing") { crossings.push(base); }
        else if (z.type === "detection_zone") { detection_zones.push(base); }
        else if (z.type === "no_parking") { no_parking_zones.push(base); }
      }
      await saveCameraLanes(camera, { lanes, stop_lines, crossings, detection_zones, no_parking_zones }, calWidth, calHeight);
    } catch (err) {
      console.error("Save failed:", err);
    }
    setSaving(false);
  }, [camera, calWidth, calHeight]);

  const selectedZone = zones.find(z => z.id === selectedId);
  const canUndo = historyIdx > 0;
  const canRedo = historyIdx < history.length - 1;
  const curZt = ZONE_TYPES.find(z => z.value === drawType);

  function renderBoundaryLine(pts, lineType, color, sw) {
    const pStr = pts.map(p => p.join(",")).join(" ");
    const dash = (lineType === "dashed" || lineType === "double_dashed") ? "0.02,0.015" : undefined;
    if (lineType === "double_solid" || lineType === "double_dashed") {
      const o1 = offsetPolyline(pts, 0.003);
      const o2 = offsetPolyline(pts, -0.003);
      return (
        <g>
          <polyline points={o1.map(p => p.join(",")).join(" ")} fill="none" stroke={color} strokeWidth={sw} strokeDasharray={dash} />
          <polyline points={o2.map(p => p.join(",")).join(" ")} fill="none" stroke={color} strokeWidth={sw} strokeDasharray={dash} />
        </g>
      );
    }
    return <polyline points={pStr} fill="none" stroke={color} strokeWidth={sw} strokeDasharray={dash} />;
  }

  function renderBoundaryLines(z, isSelected) {
    if (z.points.length < 2) return null;
    const sw = isSelected ? 0.004 : 0.002;
    if (z.type === "lane" && z.points.length >= 4) {
      const half = Math.ceil(z.points.length / 2);
      const leftPts = z.points.slice(0, half);
      const rightPts = [...z.points.slice(half)].reverse();
      const lineCol = LINE_COLORS[z.lineColor] || "#fff";
      return (
        <g>
          {renderBoundaryLine(leftPts, z.leftLineType, lineCol, sw)}
          {renderBoundaryLine(rightPts, z.rightLineType, lineCol, sw)}
        </g>
      );
    }
    const stroke = ZONE_STROKES[z.subtype] || "#888";
    if (z.points.length >= 3) {
      return (
        <polyline
          points={z.points.map(p => p.join(",")).join(" ") + " " + z.points[0].join(",")}
          fill="none" stroke={stroke} strokeWidth={sw}
        />
      );
    }
    return <polyline points={z.points.map(p => p.join(",")).join(" ")} fill="none" stroke={stroke} strokeWidth={sw} />;
  }

  function renderChevrons(z) {
    if (z.points.length < 4 || z.direction === "unknown") return null;
    const half = Math.ceil(z.points.length / 2);
    const lp = z.points.slice(0, half);
    const rp = [...z.points.slice(half)].reverse();
    const cp = lp.map((l, i) => {
      const r = rp[i] || rp[rp.length - 1] || l;
      return [(l[0] + r[0]) / 2, (l[1] + r[1]) / 2];
    });
    if (cp.length < 2) return null;
    return cp.slice(0, -1).map((_, i) => {
      const mx = (cp[i][0] + cp[i + 1][0]) / 2;
      const my = (cp[i][1] + cp[i + 1][1]) / 2;
      let ang = Math.atan2(cp[i + 1][1] - cp[i][1], cp[i + 1][0] - cp[i][0]);
      if (z.direction === "backward") ang += Math.PI;
      const s = 0.012;
      return (
        <polygon
          key={`chev-${z.id}-${i}`}
          points={`${mx - s * Math.cos(ang - 0.5)},${my - s * Math.sin(ang - 0.5)} ${mx + s * Math.cos(ang)},${my + s * Math.sin(ang)} ${mx - s * Math.cos(ang + 0.5)},${my - s * Math.sin(ang + 0.5)}`}
          fill="rgba(255,255,255,0.5)"
          style={{ pointerEvents: "none" }}
        />
      );
    });
  }

  function renderPropertyEditor() {
    if (!selectedZone) return null;
    const z = selectedZone;
    const zt = ZONE_TYPES.find(zz => zz.value === z.type);
    return (
      <Glass style={{ padding: 12, display: "flex", flexDirection: "column", gap: 8, maxHeight: 340, overflowY: "auto" }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: t.tx || "#fff", marginBottom: 2 }}>Properties</div>
        <div>
          <div style={labelSt}>Name</div>
          <input style={inputStyle} value={z.name} onChange={e => updateZoneProp("name", e.target.value)} />
        </div>
        <div>
          <div style={labelSt}>Type</div>
          <select style={selectStyle} value={z.type} onChange={e => {
            const nType = e.target.value;
            const nZt = ZONE_TYPES.find(zz => zz.value === nType);
            const nSub = nZt?.subtypes?.[0] || nType;
            pushHistory(zones.map(zn => zn.id === selectedId ? { ...zn, type: nType, subtype: nSub } : zn));
          }}>
            {ZONE_TYPES.map(zz => <option key={zz.value} value={zz.value}>{zz.label}</option>)}
          </select>
        </div>
        {zt?.subtypes?.length > 0 && (
          <div>
            <div style={labelSt}>Subtype</div>
            <select style={selectStyle} value={z.subtype} onChange={e => updateZoneProp("subtype", e.target.value)}>
              {zt.subtypes.map(s => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
            </select>
          </div>
        )}
        <div>
          <div style={labelSt}>Direction</div>
          <select style={selectStyle} value={z.direction} onChange={e => updateZoneProp("direction", e.target.value)}>
            {DIRECTIONS.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        {z.type === "lane" && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              <div>
                <div style={labelSt}>Left Line</div>
                <select style={selectStyle} value={z.leftLineType} onChange={e => updateZoneProp("leftLineType", e.target.value)}>
                  {LINE_TYPES.map(lt => <option key={lt} value={lt}>{lt.replace(/_/g, " ")}</option>)}
                </select>
              </div>
              <div>
                <div style={labelSt}>Right Line</div>
                <select style={selectStyle} value={z.rightLineType} onChange={e => updateZoneProp("rightLineType", e.target.value)}>
                  {LINE_TYPES.map(lt => <option key={lt} value={lt}>{lt.replace(/_/g, " ")}</option>)}
                </select>
              </div>
            </div>
            <div>
              <div style={labelSt}>Line Color</div>
              <select style={selectStyle} value={z.lineColor} onChange={e => updateZoneProp("lineColor", e.target.value)}>
                {Object.keys(LINE_COLORS).map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <div style={labelSt}>Speed Limit (mph)</div>
              <input type="number" style={inputStyle} value={z.speedLimit} min={0}
                onChange={e => updateZoneProp("speedLimit", Number(e.target.value) || 0)} />
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <input type="checkbox" checked={z.allowsOvertaking}
                onChange={e => updateZoneProp("allowsOvertaking", e.target.checked)} />
              <span style={{ fontSize: 12, color: t.tx || "#fff" }}>Allows Overtaking</span>
            </label>
            <div>
              <div style={labelSt}>Purpose</div>
              <select style={selectStyle} value={z.purpose} onChange={e => updateZoneProp("purpose", e.target.value)}>
                {PURPOSES.map(p => <option key={p} value={p}>{p.replace(/_/g, " ")}</option>)}
              </select>
            </div>
            <div>
              <div style={labelSt}>Allowed Vehicles</div>
              <select style={selectStyle} value={z.allowedVehicles} onChange={e => updateZoneProp("allowedVehicles", e.target.value)}>
                {VEHICLES.map(v => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}
              </select>
            </div>
          </>
        )}
        <div>
          <div style={labelSt}>Notes</div>
          <textarea style={{ ...inputStyle, height: 48, resize: "vertical" }} value={z.notes}
            onChange={e => updateZoneProp("notes", e.target.value)} />
        </div>
      </Glass>
    );
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 12, height: "calc(100vh - 64px)", padding: 12, boxSizing: "border-box" }}>
      {/* Sidebar */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, overflowY: "auto", overflowX: "hidden", minHeight: 0 }}>
        {/* Camera Selector */}
        <Glass style={{ padding: 12 }}>
          <div style={labelSt}>Camera</div>
          <select style={selectStyle} value={camera} onChange={e => setCamera(e.target.value)}>
            {(cameras || []).map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
        </Glass>

        {/* Mode Buttons */}
        <Glass style={{ padding: 12, display: "flex", gap: 6 }}>
          {[["select", "Select"], ["draw", "Draw"], ["edit", "Edit Points"]].map(([m, label]) => (
            <button key={m} style={btn(mode === m)} onClick={() => setMode(m)}>{label}</button>
          ))}
        </Glass>

        {/* Draw mode controls */}
        {mode === "draw" && (
          <Glass style={{ padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
            <div>
              <div style={labelSt}>Zone Type</div>
              <select style={selectStyle} value={drawType} onChange={e => {
                setDrawType(e.target.value);
                const zt = ZONE_TYPES.find(z => z.value === e.target.value);
                setDrawSubtype(zt?.subtypes?.[0] || e.target.value);
                if (e.target.value !== "lane") clearRoadState();
              }}>
                {ZONE_TYPES.map(z => <option key={z.value} value={z.value}>{z.label}</option>)}
              </select>
            </div>

            {drawType === "lane" ? (
              <>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.tx || "#fff", borderBottom: `1px solid ${t.dv || "rgba(255,255,255,0.06)"}`, paddingBottom: 6 }}>
                  Lane Drawing
                </div>

                {/* Step 1: Road Boundary */}
                <div style={{ fontSize: 11, fontWeight: drawPhase === "road" ? 600 : 400, color: drawPhase === "road" ? (t.tx || "#fff") : roadBoundary.length ? "#4caf50" : (t.tM || "rgba(255,255,255,0.4)") }}>
                  1. Road Boundary {roadBoundary.length > 0 && drawPhase !== "road" ? `(${roadBoundary.length} pts)` : ""}
                </div>
                {drawPhase === "road" && (
                  <>
                    <div style={{ fontSize: 11, color: t.tM || "rgba(255,255,255,0.4)" }}>
                      {currentRoadPoints.length} point{currentRoadPoints.length !== 1 ? "s" : ""} -- click to place vertices (min 4)
                    </div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <button style={{ ...btn(false), opacity: currentRoadPoints.length < 4 ? 0.4 : 1 }}
                        disabled={currentRoadPoints.length < 4} onClick={completeRoadBoundary}>Complete Road</button>
                      <button style={{ ...btn(false), opacity: !currentRoadPoints.length ? 0.4 : 1 }}
                        disabled={!currentRoadPoints.length} onClick={() => setCurrentRoadPoints(p => p.slice(0, -1))}>Undo Point</button>
                      <button style={btn(false)} onClick={() => { setDrawPhase(null); setCurrentRoadPoints([]); }}>Cancel</button>
                    </div>
                  </>
                )}
                {!drawPhase && !roadBoundary.length && (
                  <button style={btn(false)} onClick={() => setDrawPhase("road")}>Draw Road Boundary</button>
                )}

                {/* Step 2: Dividers */}
                {roadBoundary.length > 0 && (
                  <>
                    <div style={{ fontSize: 11, fontWeight: drawPhase === "divider" ? 600 : 400, color: drawPhase === "divider" ? (t.tx || "#fff") : laneDividers.length ? "#4caf50" : (t.tM || "rgba(255,255,255,0.4)") }}>
                      2. Lane Dividers ({laneDividers.length})
                    </div>
                    {drawPhase === "divider" && (
                      <>
                        <div style={{ fontSize: 11, color: t.tM || "rgba(255,255,255,0.4)" }}>
                          {currentDividerPoints.length} point{currentDividerPoints.length !== 1 ? "s" : ""} -- endpoints snap to road edge
                        </div>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          <button style={{ ...btn(false), opacity: currentDividerPoints.length < 2 ? 0.4 : 1 }}
                            disabled={currentDividerPoints.length < 2} onClick={completeDivider}>Complete Divider</button>
                          <button style={{ ...btn(false), opacity: !currentDividerPoints.length ? 0.4 : 1 }}
                            disabled={!currentDividerPoints.length} onClick={() => setCurrentDividerPoints(p => p.slice(0, -1))}>Undo Point</button>
                        </div>
                        {laneDividers.length > 0 && (
                          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                            {laneDividers.map((_, i) => (
                              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.tM || "rgba(255,255,255,0.4)" }}>
                                <div style={{ width: 8, height: 8, borderRadius: "50%", background: SECTION_STROKES[i % SECTION_STROKES.length], flexShrink: 0 }} />
                                Divider {i + 1}
                                <button style={{ ...btnSm(false), padding: "1px 6px", fontSize: 10, marginLeft: "auto" }} onClick={() => removeDivider(i)}>x</button>
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                    {drawPhase !== "road" && drawPhase !== "divider" && drawPhase !== "assign" && (
                      <button style={btn(false)} onClick={() => setDrawPhase("divider")}>Add Divider</button>
                    )}
                  </>
                )}

                {/* Step 3: Generate */}
                {roadBoundary.length > 0 && drawPhase !== "road" && drawPhase !== "assign" && (
                  <>
                    <div style={{ fontSize: 11, color: t.tM || "rgba(255,255,255,0.4)" }}>3. Generate</div>
                    <button style={btn(false)} onClick={handleGenerateSections}>Generate Lanes</button>
                  </>
                )}

                {/* Step 4: Assign */}
                {drawPhase === "assign" && (
                  <>
                    <div style={{ fontSize: 11, fontWeight: 600, color: t.tx || "#fff" }}>
                      4. Assign Lanes ({generatedSections.length} remaining)
                    </div>
                    <div style={{ fontSize: 11, color: t.tM || "rgba(255,255,255,0.4)" }}>
                      Click each section on the canvas to assign it as a lane
                    </div>
                    <button style={btn(false)} onClick={clearRoadState}>Done</button>
                  </>
                )}

                {/* Clear */}
                {(roadBoundary.length > 0 || drawPhase) && drawPhase !== "assign" && (
                  <button style={{ ...btnSm(false), marginTop: 4 }} onClick={clearRoadState}>Clear Road</button>
                )}
              </>
            ) : (
              <>
                {curZt?.subtypes?.length > 0 && (
                  <div>
                    <div style={labelSt}>Subtype</div>
                    <select style={selectStyle} value={drawSubtype} onChange={e => setDrawSubtype(e.target.value)}>
                      {curZt.subtypes.map(s => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
                    </select>
                  </div>
                )}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <button style={{ ...btn(false), opacity: currentPoints.length < 3 ? 0.4 : 1 }}
                    disabled={currentPoints.length < 3} onClick={completeDrawing}>Complete</button>
                  <button style={{ ...btn(false), opacity: !currentPoints.length ? 0.4 : 1 }}
                    disabled={!currentPoints.length} onClick={() => setCurrentPoints(p => p.slice(0, -1))}>Undo Point</button>
                  <button style={{ ...btn(false), opacity: !currentPoints.length ? 0.4 : 1 }}
                    disabled={!currentPoints.length} onClick={() => setCurrentPoints([])}>Cancel</button>
                </div>
                {currentPoints.length > 0 && (
                  <div style={{ fontSize: 11, color: t.tM || "rgba(255,255,255,0.4)" }}>
                    {currentPoints.length} point{currentPoints.length !== 1 ? "s" : ""} placed
                  </div>
                )}
              </>
            )}
          </Glass>
        )}

        {/* Zone List */}
        <Glass style={{ padding: 10, flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", minHeight: 120 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: t.tx || "#fff", marginBottom: 6 }}>
            Zones ({zones.length})
          </div>
          <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 3 }}>
            {zones.map(z => {
              const isSel = z.id === selectedId;
              return (
                <div key={z.id} style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "5px 8px", borderRadius: 8,
                  background: isSel ? (t.selBg || `${aC}18`) : "transparent",
                  border: isSel ? `1px solid ${aC}44` : "1px solid transparent",
                  cursor: "pointer", transition: "all .15s ease",
                }} onClick={() => { setSelectedId(z.id); if (mode === "draw") setMode("select"); }}>
                  <div style={{ width: 10, height: 10, borderRadius: "50%", background: ZONE_STROKES[z.subtype] || "#888", flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: t.tx || "#fff", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{z.name}</div>
                    <div style={{ fontSize: 10, color: t.tM || "rgba(255,255,255,0.4)" }}>
                      {z.subtype.replace(/_/g, " ")} &middot; {z.points.length} pts
                    </div>
                  </div>
                </div>
              );
            })}
            {!zones.length && (
              <div style={{ fontSize: 12, color: t.tF || "rgba(255,255,255,0.2)", textAlign: "center", padding: 12 }}>
                No zones defined
              </div>
            )}
          </div>
        </Glass>

        {/* Property Editor */}
        {selectedZone && (mode === "select" || mode === "edit") && renderPropertyEditor()}

        {/* Action Buttons */}
        <Glass style={{ padding: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button style={btnSm(!canUndo)} disabled={!canUndo} onClick={undo}>Undo</button>
          <button style={btnSm(!canRedo)} disabled={!canRedo} onClick={redo}>Redo</button>
          <button style={btnSm(!selectedZone)} disabled={!selectedZone} onClick={deleteZone}>Delete Zone</button>
          <button style={btnSm(!zones.length)} disabled={!zones.length} onClick={clearAll}>Clear All</button>
        </Glass>

        {/* Save */}
        <button style={{
          ...btnBase, padding: "10px 16px",
          background: `linear-gradient(135deg, ${aC}, ${aC}cc)`,
          color: "#fff", border: "none", fontSize: 13, fontWeight: 600,
          opacity: saving ? 0.6 : 1,
        }} disabled={saving} onClick={handleSave}>
          {saving ? "Saving\u2026" : "Save Configuration"}
        </button>
      </div>

      {/* Canvas Area */}
      <Glass style={{ display: "flex", flexDirection: "column", overflow: "hidden", padding: 0 }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "10px 16px",
          borderBottom: `1px solid ${t.dv || "rgba(255,255,255,0.06)"}`,
        }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: t.tx || "#fff" }}>{camera || "No Camera"}</div>
          <div style={{
            fontSize: 11, padding: "3px 10px", borderRadius: 12, fontWeight: 500,
            background: drawPhase ? "rgba(255,165,0,0.15)" : mode === "draw" ? "rgba(255,100,100,0.15)" : mode === "edit" ? "rgba(100,200,255,0.15)" : "rgba(100,255,100,0.1)",
            color: drawPhase ? "#fa8" : mode === "draw" ? "#f88" : mode === "edit" ? "#8cf" : "#8f8",
          }}>
            {drawPhase === "road" ? "Draw Road" : drawPhase === "divider" ? "Draw Divider" : drawPhase === "assign" ? "Assign Lanes" : mode === "select" ? "Select Mode" : mode === "draw" ? "Draw Mode" : "Edit Points"}
          </div>
        </div>
        <div style={{ flex: "1 1 0", minHeight: 0, display: "flex", alignItems: "flex-start", justifyContent: "center", padding: 12, overflow: "hidden" }}>
          <div style={{ width: "100%", maxHeight: "100%", aspectRatio: `${calWidth} / ${calHeight}`, position: "relative" }}>
            {loading ? (
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: t.tD || "#888", fontSize: 14 }}>
                Loading&hellip;
              </div>
            ) : (
              <svg
                ref={svgRef}
                viewBox="0 0 1 1"
                preserveAspectRatio="none"
                style={{
                  width: "100%", height: "100%",
                  background: "rgba(0,0,0,0.4)", borderRadius: 8,
                  cursor: (drawPhase === "road" || drawPhase === "divider") ? "crosshair" : drawPhase === "assign" ? "pointer" : mode === "draw" ? "crosshair" : mode === "edit" ? "default" : "pointer",
                }}
                onClick={handleSvgClick}
                onMouseMove={handleSvgMouseMove}
              >
                {bgFrameUrl && (
                  <image
                    href={bgFrameUrl}
                    x="0" y="0" width="1" height="1"
                    preserveAspectRatio="none"
                    opacity="0.55"
                    style={{ pointerEvents: "none" }}
                  />
                )}
                {!bgFrameUrl && [0.25, 0.5, 0.75].map(v => (
                  <g key={v}>
                    <line x1={v} y1={0} x2={v} y2={1} stroke="rgba(255,255,255,0.05)" strokeWidth={0.001} />
                    <line x1={0} y1={v} x2={1} y2={v} stroke="rgba(255,255,255,0.05)" strokeWidth={0.001} />
                  </g>
                ))}

                {zones.map(z => {
                  const isSel = z.id === selectedId;
                  const fill = ZONE_FILLS[z.subtype] || "rgba(128,128,128,0.15)";
                  const [cx, cy] = centroid(z.points);
                  return (
                    <g key={z.id}>
                      {z.points.length >= 3 && (
                        <polygon points={z.points.map(p => p.join(",")).join(" ")} fill={fill} stroke="none" />
                      )}
                      {renderBoundaryLines(z, isSel)}
                      {z.type === "lane" && renderChevrons(z)}
                      {z.points.length >= 2 && (
                        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
                          fill="#fff" fontSize={0.022} fontWeight={500}
                          style={{ pointerEvents: "none", textShadow: "0 1px 3px rgba(0,0,0,0.8)" }}>
                          {z.name}
                        </text>
                      )}
                      {isSel && z.points.length >= 3 && (
                        <polygon points={z.points.map(p => p.join(",")).join(" ")}
                          fill="none" stroke={aC} strokeWidth={0.003} strokeDasharray="0.01,0.008" />
                      )}
                      {isSel && mode === "edit" && z.points.map((p, i) => (
                        <circle key={i} cx={p[0]} cy={p[1]} r={0.008}
                          fill={aC} stroke="#fff" strokeWidth={0.002}
                          style={{ cursor: "grab" }}
                          onMouseDown={e => {
                            e.stopPropagation();
                            setDragPointIdx(i);
                            setDragZoneId(z.id);
                            isDragging.current = false;
                          }} />
                      ))}
                    </g>
                  );
                })}

                {/* Road boundary overlay */}
                {roadBoundary.length >= 3 && (
                  <polygon
                    points={roadBoundary.map(p => p.join(",")).join(" ")}
                    fill="rgba(255,255,255,0.04)"
                    stroke="#ff9800"
                    strokeWidth={0.003}
                    strokeDasharray="0.015,0.008"
                    style={{ pointerEvents: "none" }}
                  />
                )}

                {/* Divider polylines */}
                {laneDividers.map((div, i) => (
                  <polyline
                    key={`div-${i}`}
                    points={div.map(p => p.join(",")).join(" ")}
                    fill="none"
                    stroke={SECTION_STROKES[i % SECTION_STROKES.length]}
                    strokeWidth={0.003}
                    style={{ pointerEvents: "none" }}
                  />
                ))}

                {/* Generated sections (assign phase) */}
                {drawPhase === "assign" && generatedSections.map((section, idx) => (
                  <polygon
                    key={`section-${idx}`}
                    points={section.map(p => p.join(",")).join(" ")}
                    fill={hoveredSection === idx ? "rgba(255,255,255,0.35)" : SECTION_PALETTE[idx % SECTION_PALETTE.length]}
                    stroke={hoveredSection === idx ? "#fff" : SECTION_STROKES[idx % SECTION_STROKES.length]}
                    strokeWidth={hoveredSection === idx ? 0.004 : 0.002}
                    style={{ cursor: "pointer", transition: "fill 0.15s" }}
                    onClick={(e) => { e.stopPropagation(); assignSection(idx); }}
                    onMouseEnter={() => setHoveredSection(idx)}
                    onMouseLeave={() => setHoveredSection(null)}
                  />
                ))}

                {/* In-progress road boundary drawing */}
                {drawPhase === "road" && currentRoadPoints.length > 0 && (
                  <g>
                    {currentRoadPoints.length >= 3 && (
                      <polygon
                        points={currentRoadPoints.map(p => p.join(",")).join(" ")}
                        fill="rgba(255,165,0,0.08)"
                        stroke="none"
                      />
                    )}
                    <polyline
                      points={currentRoadPoints.map(p => p.join(",")).join(" ")}
                      fill="none"
                      stroke="#ff9800"
                      strokeWidth={0.002}
                      strokeDasharray="0.008,0.005"
                    />
                    {currentRoadPoints.map((p, i) => (
                      <circle key={i} cx={p[0]} cy={p[1]} r={0.006}
                        fill="#ff9800" stroke="#fff" strokeWidth={0.0015} />
                    ))}
                  </g>
                )}

                {/* In-progress divider drawing */}
                {drawPhase === "divider" && currentDividerPoints.length > 0 && (
                  <g>
                    <polyline
                      points={currentDividerPoints.map(p => p.join(",")).join(" ")}
                      fill="none"
                      stroke="#2196f3"
                      strokeWidth={0.003}
                      strokeDasharray="0.008,0.005"
                    />
                    {currentDividerPoints.map((p, i) => (
                      <circle key={i} cx={p[0]} cy={p[1]} r={0.006}
                        fill="#2196f3" stroke="#fff" strokeWidth={0.0015} />
                    ))}
                  </g>
                )}

                {mode === "draw" && !drawPhase && currentPoints.length > 0 && (
                  <g>
                    {currentPoints.length >= 3 && (
                      <polygon
                        points={currentPoints.map(p => p.join(",")).join(" ")}
                        fill={ZONE_FILLS[drawSubtype] || "rgba(128,128,128,0.1)"}
                        stroke="none"
                      />
                    )}
                    <polyline
                      points={currentPoints.map(p => p.join(",")).join(" ")}
                      fill="none"
                      stroke={ZONE_STROKES[drawSubtype] || "#fff"}
                      strokeWidth={0.002}
                      strokeDasharray="0.008,0.005"
                    />
                    {currentPoints.map((p, i) => (
                      <circle key={i} cx={p[0]} cy={p[1]} r={0.006}
                        fill={aC} stroke="#fff" strokeWidth={0.0015} />
                    ))}
                  </g>
                )}
              </svg>
            )}
          </div>
        </div>
      </Glass>
    </div>
  );
}
