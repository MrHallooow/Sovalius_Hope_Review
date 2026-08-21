import { useState, useEffect, useRef, createContext, useContext, useCallback } from "react";
import { useDbData } from "./services/useDbData.js";
import { getEvidenceUrls, fetchTracksJson } from "./services/dbApi.js";
import { parseTracksSidecar, findFrameAtTime, computeContentBox, scaleBBoxToBox, trackLabel } from "./services/overlayMath.mjs";
import LaneConfigTab from "./components/LaneConfigTab.jsx";

const SovMark=({size=20,color="#000"})=><svg width={size} height={size*.84} viewBox="1190 690 620 520" style={{flexShrink:0,display:"block"}}><g transform="translate(1313,909)"><path d="M0 0 C13.7 5 81.5 34.2 125.1 55.3 C232.9 107.5 349.5 164 413.6 195.1 C428.5 202.2 448.2 211.7 466 221 C458.7 223.6 439 226.1 407.1 230 C350.5 237 268.4 247.3 182.6 257.9 C113.4 266.5 37.1 276 -24.1 283.6 C-60.9 288.2 -84.5 291.2 -109 293 C-110.7 283 -113.7 265.5 -115 251 C-103.1 247.7 -85.1 244.3 -52.6 238 C-32 234.1 8.3 226.3 134.5 201.8 C155.2 197.8 193.6 190.3 248.3 179.6 C261.8 177 268 177 268 175 C262.8 174 254.4 170 241.6 163.7 C200.8 144.6 123.7 108.4 62.1 79.6 C28.9 63.9 -20.7 40.7 -58 23 C-53.6 19.1 -36.1 9.8 -17.9 0.1 C-11 -3.4 0 0 0 0 Z" fill={color}/></g><g transform="translate(1698,703)"><path d="M0 0 C-2.2 8 -8.8 22.2 -24.8 57.6 C-42.7 97.4 -58.6 132.6 -84.2 189.6 C-112.4 252.4 -120.4 270.3 -127 285 C-136.3 282.2 -156.9 272.6 -177 263 C-167 236.9 -159.2 217.1 -122 124 C-143 134.3 -203.5 163 -263.4 191.4 C-295.9 206.8 -309.3 213.4 -320 214 C-325.1 211.9 -340.9 204.3 -369 191 C-364 186.8 -350.5 179.9 -324.9 166.7 C-302.6 155.2 -248 127 -200.4 102.4 C-171.2 87.4 -142.8 72.6 -109.4 55.4 C-79.1 39.8 -50.3 24.9 -18.8 8.6 C-10.4 4.3 -2.1 0 0 0 Z" fill={color}/></g></svg>;
const SovFull=({height=50,color="#000"})=><svg height={height} viewBox="200 690 1620 520" style={{display:"block",margin:"0 auto"}}><path d="M0 0 C3.4 2.9 6.8 5.9 10 9 C8.4 13 5.9 15 2.7 17.7 C1.7 18.5 0.8 19.3 -0.2 20.1 C-2.9 22 -4.7 22.6 -8 23 C-8.7 21.9 -8.7 21.9 -9.4 20.8 C-14.3 15.6 -21.3 12.4 -28.4 11.8 C-37.4 11.6 -46.1 12.9 -53 19 C-57.1 24.6 -57.9 30.2 -57 37 C-55.5 42.3 -52.4 44.7 -47.9 47.5 C-41.1 51 -33.8 53.4 -26.6 55.8 C-11.8 60.9 2 66.5 9.4 81.2 C12.7 90.5 12.8 103.6 9.4 112.8 C3.5 124.4 -4.9 131.5 -17 136 C-34.1 141.6 -52.9 140.4 -69 132.2 C-74.1 129.2 -80.9 124.9 -82.6 118.9 C-83 117 -80.8 115 -76.3 110.9 C-75.7 110.4 -75.1 109.8 -74.4 109.2 C-69.7 105 -69.7 105 -66.2 104.9 C-63.8 106.1 -62.8 107 -61.3 109.2 C-57.1 114.6 -50.7 117.7 -44 119 C-33.6 119.9 -24.6 118.3 -16.4 111.6 C-12 107.3 -10.9 104.1 -10.7 98.1 C-10.8 92.9 -11.6 89.4 -15.4 85.6 C-21.9 80.3 -29.4 78.1 -37.2 75.5 C-68.5 65.1 -68.5 65.1 -76.4 51.2 C-80.9 40.7 -81.1 28.6 -77.5 17.9 C-73 7.8 -64.1 -0.1 -54 -4.2 C-37.2 -10 -15 -11.1 0 0 Z" fill={color} transform="translate(303,934)"/><path d="M0 0 C14.1 11.9 21.9 30 24 48 C25.1 69.8 20.3 90.2 5.8 107.1 C-7.2 121 -25.2 129.5 -44.3 130.2 C-67 130.6 -86.4 124.9 -103.2 109.3 C-118 93.6 -123.8 73.5 -123.2 52.3 C-122.4 32.9 -114.6 14.3 -100.3 0.9 C-70.8 -23.1 -29.9 -23.3 0 0 Z M-88.8 19.3 C-99 31.8 -102.9 47.3 -101.8 63.2 C-99.7 78.3 -92 92.5 -80 102 C-67 109.9 -54.2 113 -38.9 110.5 C-24.7 107 -12.6 98.6 -5 86 C2.5 71.6 5 56.9 1 41 C-3.8 26.5 -12.1 14.8 -25.5 7.2 C-47.4 -3.6 -72.2 1.7 -88.8 19.3 Z" fill={color} transform="translate(458,943)"/><path d="M0 0 C6.9 0 13.9 0 21 0 C24.7 8.6 28.1 17.4 31.4 26.2 L36.8 40.8 C41 51.9 45.4 63.7 49 75 L60.2 102.3 C66.3 116.7 69.9 125.2 73.3 133.8 L74.5 136.8 C75.2 139.1 74.2 141.1 67 141.1 L52.2 141.1 C50.4 136.8 48.5 132.4 46.7 128 L42.1 117.2 L41.2 115.2 C40 112.3 39.2 110.3 39.2 107.1 C17.5 107.4 -4.3 107.8 -26.8 108.1 C-31 118.6 -35.2 129.1 -36.8 133 L-37.7 135.1 C-39.7 140 -40.8 141.1 -45.5 141.2 L-54.3 141.2 C-56.8 141.2 -59.3 141.1 -61.8 141.1 C-63 137.3 -62.3 136.4 -60.7 132.8 L-57.5 125.6 C-54.5 118.7 -49.7 107.9 -45.3 98 C-42.5 91.7 -39.7 85.4 -36.9 79 C-31.7 67.2 -26.4 55.3 -21.2 43.4 L-20.1 40.8 C-16.5 32.7 -13 24.6 -9.5 16.5 L-8 13.1 C-7.2 11.2 -6.3 9.2 -5.5 7.3 L-3.5 2.7 C-2.3 0.1 0 0 0 0 Z M6.2 28.1 C3.5 34.6 0.7 41 -2 47.5 L-8.9 63.6 L-10.2 66.5 C-13.2 73.6 -16 80.8 -18.8 88.1 C-2.6 88.1 13.6 88.1 30.2 88.1 C29.5 84.4 28.7 81.5 27.3 78 L24.8 71.9 L19.3 58.1 C18.4 55.8 17.4 53.4 16.5 51.1 C14.4 45.9 12.3 40.7 10.2 35.6 L7.2 28.1 Z" fill={color} transform="translate(670.8,928.9)"/><path d="M0 0 C6.9 0 13.9 0 21 0 C24.7 8.6 28.1 17.4 31.4 26.2 L36.8 40.8 C43.1 57.5 53.2 84.4 60.2 102.3 C66.3 116.7 69.9 125.2 73.3 133.8 L74.5 136.8 C75.2 139.1 74.2 141.1 67 141.1 L52 141 C44.2 121.9 36.8 102.5 29.5 83.2 L27 76.5 C23.7 67.9 20.5 59.4 17.2 50.8 L10.1 32.3 C8.8 28.9 7.5 25.5 6.2 22.2 L0.2 5.9 C-0.1 5.2 -0.6 3.8 -1 2 L0 0 Z M104 0 C107.1 -0.1 110.2 -0.1 113.4 -0.2 L121 -0.3 C121.7 -0.2 122.3 -0.1 123 0 C125 3 124.7 4.9 123.8 7 L121.7 12.2 L120.6 15.1 C119.4 18.2 118.1 21.4 116.9 24.5 C116 26.7 115.1 28.9 114.3 31.1 C112.4 35.7 110.6 40.4 108.8 45 C106.1 51.7 103.4 58.5 100.8 65.3 C90.9 90.5 81 115.8 71 141 C64.7 141 58.5 141 52 141 Z" fill={color} transform="translate(492,929)"/><path d="M0 0 L12.2 0 C14 0.1 15 1.1 15.1 5.8 L15.1 12.4 C15.1 19.2 15.1 24.5 15.1 27.6 C15.1 45.3 15.2 63 15.3 76.6 C15.1 98.4 16.1 98.4 26.6 116.9 C35.3 124 44.7 125.2 55.8 124.1 C62.1 122.7 68.7 120.4 72.8 115.1 C78.8 105.2 81.1 96 81.1 84.6 L81.2 72.9 C81.3 61.3 81.3 55.9 81.4 50.5 C81.5 33 81.6 18.2 81.6 9.6 L81.6 7.1 C81.7 1.2 82.8 0.1 86.8 0 L99 0 C100.8 0.1 101.8 1.1 102 10.1 L102 22.4 C102.1 37 102.1 48.5 102.2 60.2 C102.2 73.8 102.2 80.2 102.4 99.1 C100.9 116.3 87.5 131 75 142.6 C58.5 145 42.2 144.3 28.6 143.3 C17.4 138.2 7.9 128.4 -6.3 111.6 C-5.4 89.5 -5.4 68.8 -5.4 50.8 C-5.3 40.3 -5.4 31 -5.4 23 C-5.4 14.5 -5.4 9.1 -5.3 6.7 C-5.3 0 0 0 0 0 Z" fill={color} transform="translate(927.2,928.9)"/><path d="M0 0 L12.2 0 C14 0.1 15 1.1 15.1 6.5 L15.1 18.1 C15.1 33.2 15.1 54 15.1 77 C15 107.1 15 122.1 15.1 134.7 L15.1 137.8 C15 140.1 14 141.1 12.2 141.3 L0 141.3 C-2.2 141.3 -4 141.1 -5 140.1 C-5.1 136.5 -5.1 131.2 -5.1 123.2 C-5.1 108.1 -5.1 87.3 -5.1 58 C-5.1 38.6 -5.1 27 -5.1 16 C-5.1 8.9 -5.1 5.5 -5.1 3.4 C-4.9 -0.4 -3.5 0 0 0 Z" fill={color} transform="translate(872,928.9)"/><path d="M0 0 L12.2 0 C14 0.1 15 1.1 15.1 5.8 L15.1 25.7 C15.1 42.3 15.1 62.4 15.1 77 C15 107.1 15 122.1 15.8 122.1 C31.9 122.1 50.4 122.1 61.3 122 L71.2 122 C74.5 122 77 122.1 78 123.1 L78.1 134.1 C78.1 140 77 141.1 69.5 141.3 L59.2 141.3 C50 141.3 37.5 141.3 27.7 141.3 C16.5 141.3 8.6 141.3 3.5 141.3 C-3.9 141.2 -5 140.1 -5.1 134.7 C-5.1 124.5 -5.1 104.2 -5.1 80.7 C-5.1 58 -5.1 38.6 -5.1 27 C-5.1 16 -5.1 8.9 -5.1 3.4 C-4.9 -0.4 -3.5 0 0 0 Z" fill={color} transform="translate(771,928.9)"/><path d="M0 0 C3.4 2.9 6.8 5.9 10 9 C8.4 13 5.9 15 2.7 17.7 C-2.9 22 -4.7 22.6 -8 23 C-8.7 21.9 -14.3 15.6 -28.4 11.8 C-46.1 12.9 -53 19 -57.1 24.6 C-57.9 30.2 -57 37 -55.5 42.3 C-52.4 44.7 -41.1 51 -26.6 55.8 C-11.8 60.9 2 66.5 9.4 81.2 C12.7 90.5 12.8 103.6 9.4 112.8 C3.5 124.4 -4.9 131.5 -17 136 C-34.1 141.6 -52.9 140.4 -69 132.2 C-82.6 118.9 -83 117 -76.3 110.9 C-69.7 105 -66.2 104.9 -63.8 106.1 C-57.1 114.6 -50.7 117.7 -44 119 C-24.6 118.3 -12 107.3 -10.7 98.1 C-11.6 89.4 -21.9 80.3 -37.2 75.5 C-68.5 65.1 -76.4 51.2 -80.9 40.7 C-81.1 28.6 -77.5 17.9 -73 7.8 C-54 -4.2 -37.2 -10 0 0 Z" fill={color} transform="translate(1137,934)"/><g transform="translate(1313,909)"><path d="M0 0 C13.7 5 81.5 34.2 125.1 55.3 C232.9 107.5 349.5 164 413.6 195.1 C428.5 202.2 448.2 211.7 466 221 C458.7 223.6 439 226.1 407.1 230 C350.5 237 268.4 247.3 182.6 257.9 C113.4 266.5 37.1 276 -24.1 283.6 C-60.9 288.2 -84.5 291.2 -109 293 C-110.7 283 -113.7 265.5 -115 251 C-103.1 247.7 -85.1 244.3 -52.6 238 C-32 234.1 8.3 226.3 134.5 201.8 C155.2 197.8 193.6 190.3 248.3 179.6 C261.8 177 268 177 268 175 C262.8 174 254.4 170 241.6 163.7 C200.8 144.6 123.7 108.4 62.1 79.6 C28.9 63.9 -20.7 40.7 -58 23 C-53.6 19.1 -36.1 9.8 -17.9 0.1 C-11 -3.4 0 0 0 0 Z" fill={color}/></g><g transform="translate(1698,703)"><path d="M0 0 C-2.2 8 -8.8 22.2 -24.8 57.6 C-42.7 97.4 -58.6 132.6 -84.2 189.6 C-112.4 252.4 -120.4 270.3 -127 285 C-136.3 282.2 -156.9 272.6 -177 263 C-167 236.9 -159.2 217.1 -122 124 C-143 134.3 -203.5 163 -263.4 191.4 C-295.9 206.8 -309.3 213.4 -320 214 C-325.1 211.9 -340.9 204.3 -369 191 C-364 186.8 -350.5 179.9 -324.9 166.7 C-302.6 155.2 -248 127 -200.4 102.4 C-171.2 87.4 -142.8 72.6 -109.4 55.4 C-79.1 39.8 -50.3 24.9 -18.8 8.6 C-10.4 4.3 -2.1 0 0 0 Z" fill={color}/></g></svg>;

/* ═══ DATA ═══ */
const AN={today:{total:0,approved:0,dismissed:0,pending:0},week:{total:0,approved:0,dismissed:0,pending:0},month:{total:0,approved:0,dismissed:0,pending:0},byType:{},hourly:new Array(24).fill(0),approvalRate:0,avgReviewTime:"--",officersActive:0};
const NOTIFS_INIT=[];
const QN=["Clear violation","Insufficient evidence","Low visibility","Plate not readable","Multiple vehicles"];
const SPEEDS=[0.5,1,1.5,2];
const CSC={default:{type:{"Speeding":"#f59e0b","Reckless Driving":"#ef4444","Illegal Parking":"#60a5fa"},status:{pending:"#f59e0b",approved:"#34d399",dismissed:"#f87171"}},cb:{type:{"Speeding":"#e69f00","Reckless Driving":"#d55e00","Illegal Parking":"#0072b2"},status:{pending:"#e69f00",approved:"#009e73",dismissed:"#cc79a7"}}};
const NPL=[{k:"bottom",l:"Bottom bar"},{k:"below_decision",l:"Below decision"},{k:"video_controls",l:"Inline with video"},{k:"top",l:"Top of review"},{k:"floating",l:"Floating arrows"},{k:"both",l:"Bottom + Below decision"}];
const ThC=createContext("dark"),StC=createContext({}),KbC=createContext({}),CC=createContext(CSC.default);
const DS={autoAdvance:false,defaultVideoMode:"ai",defaultFilter:"all",notifNew:true,notifOverride:false,fsNavStyle:"large",queueDensity:"comfortable",queueSort:"time",queueCols:{plate:true,location:true,confidence:true,speed:true,time:true},autoPlay:false,playbackSpeed:1,annotationOpacity:1,quickNotes:QN,confidenceThreshold:80,confirmActions:false,minNoteLength:0,fontSize:"medium",sidebarPos:"right",timeFormat:"24h",colorBlind:false,hoverPreview:true,navPlacement:"bottom",autoHideDelay:3,sessionTimeout:30};
const DK={next:{key:"ArrowRight",alt:"n",ctrl:false,desc:"Next"},prev:{key:"ArrowLeft",alt:"p",ctrl:false,desc:"Previous"},back:{key:"b",alt:"Backspace",ctrl:false,desc:"Back"},focusNotes:{key:"/",alt:null,ctrl:false,desc:"Focus notes"},approve:{key:"a",alt:null,ctrl:true,desc:"Approve"},dismiss:{key:"d",alt:null,ctrl:true,desc:"Dismiss"},playPause:{key:" ",alt:null,ctrl:false,desc:"Play/pause"},toggleAI:{key:"t",alt:null,ctrl:false,desc:"Toggle AI/RAW"},fullscreen:{key:"f",alt:null,ctrl:false,desc:"Fullscreen"},exitFullscreen:{key:"Escape",alt:null,ctrl:false,desc:"Exit fullscreen"},toggleDrawer:{key:"r",alt:null,ctrl:false,desc:"Drawer"},cheatSheet:{key:"?",alt:null,ctrl:false,desc:"Shortcuts"},pin:{key:"s",alt:null,ctrl:false,desc:"Pin/unpin"}};

const T={
  dark:{bg:"#080b16",bgG:"radial-gradient(ellipse at 20% 30%,rgba(99,102,241,.12) 0%,transparent 50%),radial-gradient(ellipse at 80% 70%,rgba(168,85,247,.08) 0%,transparent 40%),#080b16",gl:"rgba(14,20,36,.88)",glH:"rgba(20,28,48,.92)",gB:"rgba(255,255,255,.10)",gI:"inset 0 1px 0 rgba(255,255,255,.06)",tx:"#fff",tM:"rgba(255,255,255,.55)",tD:"rgba(255,255,255,.35)",tF:"rgba(255,255,255,.2)",iB:"rgba(255,255,255,.04)",iBo:"rgba(255,255,255,.08)",dv:"rgba(255,255,255,.06)",sh:"0 4px 24px rgba(0,0,0,.2)",nB:"rgba(10,14,26,.9)",bB:"rgba(8,11,22,.92)",fB:"#000",fD:"rgba(15,20,35,.96)",fDB:"rgba(255,255,255,.1)",selBg:"#151b2e",selC:"#e0e0e0"},
  light:{bg:"#f0f2f8",bgG:"radial-gradient(ellipse at 20% 30%,rgba(99,102,241,.06) 0%,transparent 50%),#f0f2f8",gl:"rgba(255,255,255,.85)",glH:"rgba(255,255,255,.92)",gB:"rgba(0,0,0,.08)",gI:"inset 0 1px 0 rgba(255,255,255,.9)",tx:"#111827",tM:"#4b5563",tD:"#6b7280",tF:"#9ca3af",iB:"rgba(0,0,0,.03)",iBo:"rgba(0,0,0,.1)",dv:"rgba(0,0,0,.06)",sh:"0 4px 24px rgba(0,0,0,.06)",nB:"rgba(255,255,255,.9)",bB:"rgba(240,242,248,.92)",fB:"#111318",fD:"rgba(240,242,248,.96)",fDB:"rgba(0,0,0,.12)",selBg:"#fff",selC:"#111827"}
};

/* ═══ HELPERS ═══ */
const fD=d=>new Date(d).toLocaleDateString("en-GB",{day:"2-digit",month:"short",year:"numeric"});
const fT=(d,f)=>new Date(d).toLocaleTimeString("en-GB",f==="12h"?{hour:"numeric",minute:"2-digit",hour12:true}:{hour:"2-digit",minute:"2-digit"});
const fTF=(d)=>new Date(d).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
const tS=d=>{const m=Math.floor((Date.now()-new Date(d).getTime())/60000);if(m<60)return`${m}m ago`;const h=Math.floor(m/60);return h<24?`${h}h ago`:`${Math.floor(h/24)}d ago`;};
const sc=s=>s==="small"?.85:s==="large"?1.15:1;
const kl=(k,c)=>{if(!k)return"—";const n=k===" "?"Space":k==="ArrowLeft"?"←":k==="ArrowRight"?"→":k==="Escape"?"Esc":k.length===1?k.toUpperCase():k;return c?`Ctrl+${n}`:n;};

function useCD(dt){const[l,sL]=useState("");useEffect(()=>{if(!dt)return;const tick=()=>{const ms=new Date(dt).getTime()+86400000-Date.now();if(ms<=0){sL("Expired");return;}sL(`${Math.floor(ms/3600000)}h ${Math.floor((ms%3600000)/60000)}m`);};tick();const i=setInterval(tick,30000);return()=>clearInterval(i);},[dt]);return l;}
function useKB(b,a){const r=useRef(a);useEffect(()=>{r.current=a;});useEffect(()=>{const h=e=>{const ty=["INPUT","TEXTAREA","SELECT"].includes(e.target.tagName);for(const[k,v]of Object.entries(b)){if(!r.current[k])continue;if(!(e.key.toLowerCase()===v.key.toLowerCase()||(v.alt&&e.key.toLowerCase()===v.alt.toLowerCase())))continue;if(v.ctrl&&!e.ctrlKey&&!e.metaKey)continue;if(!v.ctrl&&(e.ctrlKey||e.metaKey)&&k!=="cheatSheet")continue;if(ty&&k!=="focusNotes"&&!v.ctrl)continue;if(k==="focusNotes"&&ty)continue;e.preventDefault();r.current[k]();return;}};window.addEventListener("keydown",h);return()=>window.removeEventListener("keydown",h);},[b]);}
function useAH(playing,delay){const[v,sV]=useState(true);const tm=useRef(null);useEffect(()=>{const r=()=>{sV(true);clearTimeout(tm.current);if(playing)tm.current=setTimeout(()=>sV(false),(delay||3)*1000);};if(!playing){sV(true);clearTimeout(tm.current);return;}r();const h=()=>r();window.addEventListener("mousemove",h);return()=>{window.removeEventListener("mousemove",h);clearTimeout(tm.current);};},[playing,delay]);return v;}

/* ═══ SESSION TIMEOUT ═══ */
function useSessionTimeout(timeoutMin,onLogout){
  const[warn,sWarn]=useState(false);const[left,sLeft]=useState(0);const lastAct=useRef(Date.now());const warnAt=5*60*1000;
  useEffect(()=>{if(!timeoutMin)return;const check=()=>{const idle=Date.now()-lastAct.current;const total=timeoutMin*60*1000;const remaining=total-idle;if(remaining<=0){onLogout();return;}if(remaining<=warnAt){sWarn(true);sLeft(Math.ceil(remaining/1000));}else{sWarn(false);}};const i=setInterval(check,1000);const reset=()=>{lastAct.current=Date.now();sWarn(false);};["mousemove","keydown","click","scroll"].forEach(e=>window.addEventListener(e,reset));return()=>{clearInterval(i);["mousemove","keydown","click","scroll"].forEach(e=>window.removeEventListener(e,reset));};},[timeoutMin,onLogout]);
  return{warn,left,dismiss:()=>{lastAct.current=Date.now();sWarn(false);}};
}

/* ═══ SMALL COMPONENTS ═══ */
function Sel({value:v,onChange:oc,options:o}){const t=T[useContext(ThC)];return(<select value={v} onChange={oc} style={{padding:"7px 8px",borderRadius:8,border:`1px solid ${t.iBo}`,background:t.selBg,color:t.selC,fontSize:11,fontWeight:600,outline:"none",cursor:"pointer"}}>{o.map(x=><option key={x.k} value={x.k} style={{background:t.selBg,color:t.selC}}>{x.l}</option>)}</select>);}
const Glass=({children,style:s={},hover:hv=false,...p})=>{const t=T[useContext(ThC)],[h,sH]=useState(false);return(<div onMouseEnter={hv?()=>sH(true):undefined} onMouseLeave={hv?()=>sH(false):undefined} style={{background:h?t.glH:t.gl,border:`1px solid ${t.gB}`,borderRadius:16,boxShadow:`${t.sh}, ${t.gI}`,...s}} {...p}>{children}</div>);};
const Kbd=({children})=>{const t=T[useContext(ThC)];return(<span style={{display:"inline-block",padding:"1px 5px",borderRadius:4,fontSize:9,fontFamily:"'JetBrains Mono',monospace",fontWeight:700,background:useContext(ThC)==="dark"?"rgba(255,255,255,.08)":"rgba(0,0,0,.06)",border:`1px solid ${t.iBo}`,color:t.tM,lineHeight:"16px",minWidth:14,textAlign:"center"}}>{children}</span>);};
const CM=({value:v})=>{const co=v>=90?"#34d399":v>=80?"#f59e0b":"#f87171";return(<div style={{display:"flex",alignItems:"center",gap:6,flexShrink:0}}><div style={{width:50,height:4,borderRadius:10,background:"rgba(128,128,128,.15)",overflow:"hidden"}}><div style={{width:`${v}%`,height:"100%",borderRadius:10,background:`linear-gradient(90deg,${co}88,${co})`}}/></div><span style={{fontSize:10,fontWeight:600,color:co,fontFamily:"'JetBrains Mono',monospace"}}>{v}%</span></div>);};
const MC=({data:d,height:h=55})=>{const mx=Math.max(...d);return(<svg width="100%" height={h} viewBox={`0 0 ${d.length*12} ${h}`} preserveAspectRatio="none"><defs><linearGradient id="bG" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#a78bfa"/><stop offset="100%" stopColor="#6366f1"/></linearGradient></defs>{d.map((v,i)=><rect key={i} x={i*12+1} y={h-(v/mx)*h} width={9} height={(v/mx)*h} fill="url(#bG)" opacity={.8} rx={2}/>)}</svg>);};
function HP({v,pos:p}){const t=T[useContext(ThC)],c=useContext(CC);if(!v)return null;return(<div style={{position:"fixed",top:Math.max(10,p.y-120),left:p.x+20,zIndex:9000,width:280,background:t.fD,border:`1px solid ${t.fDB}`,borderRadius:12,padding:14,boxShadow:"0 12px 40px rgba(0,0,0,.4)",pointerEvents:"none"}}><div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}><span style={{fontSize:12,fontWeight:700,color:t.tx,fontFamily:"'JetBrains Mono',monospace"}}>{v.id}</span><span style={{fontSize:10,fontWeight:700,color:c.type[v.type],background:`${c.type[v.type]}15`,padding:"2px 8px",borderRadius:6}}>{v.type}</span></div><p style={{fontSize:11,color:t.tM,lineHeight:1.4,margin:0,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{v.aiSummary}</p></div>);}
function CS2({onClose:oc,keybinds:kb}){const t=T[useContext(ThC)];return(<div onClick={oc} style={{position:"fixed",inset:0,zIndex:9999,background:"rgba(0,0,0,.6)",display:"flex",alignItems:"center",justifyContent:"center"}}><div onClick={e=>e.stopPropagation()} style={{background:t.fD,border:`1px solid ${t.fDB}`,borderRadius:20,padding:"28px 32px",maxWidth:500,width:"90%"}}><div style={{display:"flex",justifyContent:"space-between",marginBottom:20}}><h2 style={{margin:0,fontSize:18,fontWeight:800,color:t.tx}}>Shortcuts</h2><button onClick={oc} style={{background:"none",border:"none",color:t.tD,fontSize:18,cursor:"pointer"}}>✕</button></div><div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"6px 20px"}}>{Object.entries(kb).map(([a,b])=>(<div key={a} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"5px 0",borderBottom:`1px solid ${t.dv}`}}><span style={{fontSize:12,color:t.tM}}>{b.desc}</span><Kbd>{kl(b.key,b.ctrl)}</Kbd></div>))}</div></div></div>);}
function CDBadge({reviewedAt:ra}){const cd=useCD(ra);if(!ra)return null;const ex=cd==="Expired";return(<span style={{fontSize:10,fontFamily:"'JetBrains Mono',monospace",color:ex?"#f87171":"#f59e0b",background:ex?"rgba(248,113,113,.1)":"rgba(245,158,11,.1)",padding:"2px 8px",borderRadius:6,fontWeight:600,flexShrink:0,whiteSpace:"nowrap"}}>{ex?"Finalised":cd}</span>);}
function LTB({search:se,setSearch:sSe,sort:so,setSort:sSo,filter:fi,setFilter:sFi,sortOptions:sOp,filterOptions:fOp,placeholder:ph}){const t=T[useContext(ThC)];return(<div style={{padding:"10px 16px",display:"flex",gap:8,alignItems:"center",borderBottom:`1px solid ${t.dv}`}}><div style={{flex:1,position:"relative"}}><input value={se} onChange={e=>sSe(e.target.value)} placeholder={ph||"Search..."} style={{width:"100%",padding:"7px 10px 7px 28px",borderRadius:8,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tx,fontSize:12,outline:"none",boxSizing:"border-box"}}/><span style={{position:"absolute",left:10,top:"50%",transform:"translateY(-50%)",fontSize:11,color:t.tF,pointerEvents:"none"}}>⌕</span></div><Sel value={so} onChange={e=>sSo(e.target.value)} options={sOp}/>{fOp&&<Sel value={fi} onChange={e=>sFi(e.target.value)} options={fOp}/>}</div>);}

/* ═══ NOTIFICATIONS PANEL ═══ */
function NotifPanel({notifs,onClose,onRead,onMarkAllRead}){
  const t=T[useContext(ThC)];const unread=notifs.filter(n=>!n.read).length;
  return(<div style={{position:"absolute",top:52,right:0,width:340,background:t.fD,border:`1px solid ${t.fDB}`,borderRadius:14,boxShadow:"0 16px 48px rgba(0,0,0,.3)",zIndex:200,maxHeight:400,display:"flex",flexDirection:"column"}}>
    <div style={{padding:"14px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
      <h3 style={{margin:0,fontSize:14,fontWeight:700,color:t.tx}}>Notifications</h3>
      <div style={{display:"flex",gap:8,alignItems:"center"}}>
        {unread>0&&<button onClick={onMarkAllRead} style={{background:"none",border:"none",color:"#a78bfa",fontSize:11,fontWeight:600,cursor:"pointer",padding:0}}>Mark all read</button>}
        <button onClick={onClose} style={{background:"none",border:"none",color:t.tD,cursor:"pointer",fontSize:14}}>✕</button>
      </div>
    </div>
    <div style={{flex:1,overflowY:"auto"}}>{notifs.length===0?<p style={{padding:20,textAlign:"center",color:t.tF,fontSize:13}}>No notifications</p>:notifs.map(n=>(
      <div key={n.id} onClick={()=>onRead(n.id)} style={{padding:"10px 18px",borderBottom:`1px solid ${t.dv}`,cursor:"pointer",background:n.read?"transparent":"rgba(167,139,250,.04)"}}>
        <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:4}}>
          <span style={{width:6,height:6,borderRadius:3,background:n.read?"transparent":n.type==="violation"?"#f59e0b":n.type==="system"?"#ef4444":"#a78bfa",flexShrink:0}}/>
          <span style={{fontSize:10,color:t.tD,textTransform:"uppercase",fontWeight:600}}>{n.type}</span>
          <span style={{fontSize:10,color:t.tF,marginLeft:"auto"}}>{tS(n.at)}</span>
        </div>
        <p style={{margin:0,fontSize:12,color:n.read?t.tD:t.tx,fontWeight:n.read?400:500}}>{n.msg}</p>
      </div>
    ))}</div>
  </div>);
}

/* ═══ EVIDENCE CHAIN OF CUSTODY ═══ */
function ChainOfCustody({history}){
  const t=T[useContext(ThC)];if(!history||!history.length)return null;
  const actionColors={flagged:"#a78bfa",viewed:"#60a5fa",approved:"#34d399",dismissed:"#f87171",revised:"#f59e0b",undone:"#f87171"};
  return(<Glass style={{padding:18,marginTop:16}}>
    <h3 style={{margin:"0 0 14px",fontSize:13,fontWeight:700,color:t.tx}}>Chain of Custody</h3>
    <div style={{position:"relative",paddingLeft:20}}>
      <div style={{position:"absolute",left:7,top:4,bottom:4,width:2,background:t.dv}}/>
      {history.map((h,i)=>(<div key={i} style={{position:"relative",marginBottom:i<history.length-1?14:0}}>
        <div style={{position:"absolute",left:-16,top:4,width:10,height:10,borderRadius:5,background:actionColors[h.action]||t.tD,border:`2px solid ${t.gl}`}}/>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <div>
            <span style={{fontSize:11,fontWeight:700,color:actionColors[h.action]||t.tx,textTransform:"uppercase",letterSpacing:.5}}>{h.action}</span>
            <span style={{fontSize:11,color:t.tD,marginLeft:8}}>by {h.by}</span>
          </div>
          <span style={{fontSize:10,color:t.tF,fontFamily:"'JetBrains Mono',monospace"}}>{fTF(h.at)}</span>
        </div>
        {h.notes&&<p style={{margin:"2px 0 0",fontSize:11,color:t.tM,fontStyle:"italic"}}>{h.notes}</p>}
      </div>))}
    </div>
  </Glass>);
}

/* ═══ VIOLATION LINKING ═══ */
function LinkedViolations({current,allViolations}){
  const t=T[useContext(ThC)],c=useContext(CC);
  const linked=allViolations.filter(v=>v.id!==current.id&&(v.plate===current.plate||v.location===current.location||(Math.abs(new Date(v.date)-new Date(current.date))<1800000)));
  if(!linked.length)return null;
  return(<Glass style={{padding:18,marginTop:16}}>
    <h3 style={{margin:"0 0 12px",fontSize:13,fontWeight:700,color:t.tx}}>Related Violations</h3>
    {linked.map(v=>{
      const reasons=[];
      if(v.plate===current.plate)reasons.push("Same plate");
      if(v.location===current.location)reasons.push("Same location");
      if(Math.abs(new Date(v.date)-new Date(current.date))<1800000)reasons.push("Same timeframe");
      return(<div key={v.id} style={{padding:"8px 12px",borderRadius:10,marginBottom:8,background:t.iB,border:`1px solid ${t.iBo}`}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
          <span style={{fontSize:12,fontWeight:700,color:t.tx,fontFamily:"'JetBrains Mono',monospace"}}>{v.id}</span>
          <span style={{fontSize:9,color:c.status[v.status],fontWeight:700,textTransform:"uppercase"}}>{v.status}</span>
        </div>
        <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
          {reasons.map(r=>(<span key={r} style={{fontSize:9,padding:"2px 6px",borderRadius:4,background:"rgba(167,139,250,.1)",color:"#a78bfa",fontWeight:600}}>{r}</span>))}
          <span style={{fontSize:10,color:t.tD}}>{v.plate} · {v.type}</span>
        </div>
      </div>);
    })}
  </Glass>);
}

/* ═══ NOTES HISTORY ═══ */
function NotesHistory({history}){
  const t=T[useContext(ThC)];
  const decisions=history?.filter(h=>["approved","dismissed","revised"].includes(h.action))||[];
  if(!decisions.length)return null;
  return(<div style={{marginBottom:12}}>
    <p style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,marginBottom:8,fontWeight:600}}>Previous Decisions</p>
    {decisions.map((d,i)=>(<div key={i} style={{padding:"8px 10px",borderRadius:8,marginBottom:6,background:t.iB,borderLeft:`3px solid ${d.action==="approved"?"#34d399":"#f87171"}`}}>
      <div style={{display:"flex",justifyContent:"space-between",marginBottom:2}}>
        <span style={{fontSize:10,fontWeight:700,color:d.action==="approved"?"#34d399":"#f87171",textTransform:"uppercase"}}>{d.action}</span>
        <span style={{fontSize:9,color:t.tF}}>{d.by} · {fTF(d.at)}</span>
      </div>
      {d.notes&&<p style={{margin:0,fontSize:11,color:t.tM,fontStyle:"italic"}}>"{d.notes}"</p>}
    </div>))}
  </div>);
}

/* ═══ MULTI-CAMERA VIEW ═══ */
function CameraSwitcher({cameras,active,onSwitch}){
  const t=T[useContext(ThC)];if(!cameras||cameras.length<=1)return null;
  return(<div style={{display:"flex",gap:4,marginBottom:8}}>
    <span style={{fontSize:10,color:t.tD,fontWeight:600,alignSelf:"center",marginRight:4}}>Cameras:</span>
    {cameras.map(c=>(<button key={c} onClick={()=>onSwitch(c)} style={{padding:"4px 10px",borderRadius:6,border:`1px solid ${active===c?"rgba(167,139,250,.3)":t.iBo}`,background:active===c?"rgba(167,139,250,.15)":t.iB,color:active===c?"#a78bfa":t.tD,fontSize:10,fontWeight:600,cursor:"pointer",fontFamily:"'JetBrains Mono',monospace"}}>{c}</button>))}
  </div>);
}

/* ═══ CAMERA STATUS PAGE ═══ */
function SystemStatus(){
  const t=T[useContext(ThC)];const s=sc(useContext(StC).fontSize);
  const[ss,setSs]=useState(null);
  const[lastRefresh,sLastRefresh]=useState(new Date());
  const isEl=typeof window!=="undefined"&&window.hopeDb;
  const refresh=useCallback(()=>{
    if(!isEl)return;
    window.hopeDb.getSystemStatus().then(res=>{
      if(res.ok)setSs(res.row);
      sLastRefresh(new Date());
    });
  },[isEl]);
  useEffect(()=>{refresh();const i=setInterval(refresh,10000);return()=>clearInterval(i);},[refresh]);

  const fmtUptime=(sec)=>{if(!sec)return"0s";const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),sv=Math.floor(sec%60);return h>0?`${h}h ${m}m ${sv}s`:m>0?`${m}m ${sv}s`:`${sv}s`;};
  const staleMs=ss?Date.now()-new Date(ss.timestamp).getTime():Infinity;
  const alive=ss&&staleMs<60000;
  const feeds=alive?(ss.feed_details||[]):[];
  const activeFeeds=feeds.filter(f=>f.is_active).length;
  const inactiveFeeds=feeds.length-activeFeeds;

  const services=!ss?[]:[ 
    {name:"AI Processor",status:alive&&ss.ai_processor_ready?"operational":"down",detail:alive&&ss.ai_processor_ready?"Inference engine ready":"Not responding"},
    {name:"Plugin System",status:alive&&ss.plugins_loaded?"operational":"down",detail:alive&&ss.plugins_loaded?"All plugins loaded":"Not loaded"},
    {name:"Cloud Sync",status:alive&&ss.sync_status?.running&&ss.sync_status?.remote_connected?"operational":alive&&ss.sync_status?.running?"degraded":"down",detail:alive&&ss.sync_status?.running?`${ss.sync_status.sync_count} syncs · last ID ${ss.sync_status.last_synced_id}`:"Not syncing"},
    {name:"Feed Pipeline",status:alive&&ss.active_feeds>0?"operational":alive?"degraded":"down",detail:alive?`${ss.active_feeds}/${ss.total_feeds} feeds active`:"No feeds"},
  ];
  const svcStatC={operational:"#34d399",degraded:"#f59e0b",down:"#f87171"};
  const allOp=services.filter(sv=>sv.status==="operational").length;
  const hasDown=services.some(sv=>sv.status==="down");
  const hasDeg=services.some(sv=>sv.status==="degraded");
  const Empty=({label})=>(<div style={{padding:"40px 20px",textAlign:"center"}}><p style={{fontSize:13,color:t.tD,margin:0}}>No {label} data</p><p style={{fontSize:11,color:t.tF,margin:"4px 0 0"}}>Waiting for H.O.P.E. to push status</p></div>);
  const feedStatC=(f)=>f.is_active?"#34d399":"#f87171";

  return(<div>
    <h2 style={{fontSize:20*s,fontWeight:800,color:t.tx,margin:"0 0 20px"}}>System Status</h2>
    <Glass style={{padding:20,marginBottom:16,display:"flex",alignItems:"center",gap:16}}>
      <div style={{width:12,height:12,borderRadius:6,background:!ss?"rgba(128,128,128,.4)":!alive?"#f87171":hasDown?"#f87171":hasDeg?"#f59e0b":"#34d399",boxShadow:`0 0 12px ${!ss?"rgba(128,128,128,.2)":!alive?"#f8717144":hasDown?"#f8717144":hasDeg?"#f59e0b44":"#34d39944"}`,animation:"pulse 2s infinite"}}/>
      <div>
        <p style={{margin:0,fontSize:16*s,fontWeight:800,color:t.tx}}>{!ss?"Awaiting Data":!alive?"H.O.P.E. Offline":hasDown?"Issues Detected":hasDeg?"Partial Degradation":"All Systems Operational"}</p>
        <p style={{margin:"2px 0 0",fontSize:12,color:t.tD}}>{!ss?"No heartbeat received yet":!alive?`Last seen ${Math.round(staleMs/1000)}s ago · ${ss.device_id}`:`${activeFeeds}/${feeds.length} feeds active · ${allOp}/${services.length} services operational · ${ss.device_id}`}</p>
      </div>
      <span style={{marginLeft:"auto",fontSize:10,color:t.tF,fontFamily:"'JetBrains Mono',monospace"}}>Auto-refresh · {lastRefresh.toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}</span>
    </Glass>

    {alive&&<div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:14,marginBottom:16}}>
      {[{l:"Uptime",v:fmtUptime(ss.uptime_sec),c:"#a78bfa"},{l:"Active Feeds",v:`${ss.active_feeds}/${ss.total_feeds}`,c:"#34d399"},{l:"Violations",v:ss.total_violations,c:"#f87171"},{l:"Vehicles Tracked",v:ss.total_vehicles_tracked,c:"#38bdf8"},{l:"Syncs",v:ss.sync_status?.sync_count||0,c:"#fbbf24"}].map((x,i)=>(<Glass key={i} style={{padding:16,textAlign:"center"}}>
        <p style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,margin:"0 0 4px",fontWeight:600}}>{x.l}</p>
        <p style={{fontSize:20*s,fontWeight:800,color:x.c,margin:0,fontFamily:"'JetBrains Mono',monospace"}}>{x.v}</p>
      </Glass>))}
    </div>}

    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16,marginBottom:16}}>
      <Glass style={{overflow:"hidden"}}>
        <div style={{padding:"14px 18px",borderBottom:`1px solid ${t.dv}`}}><h3 style={{margin:0,fontSize:14*s,fontWeight:700,color:t.tx}}>Services</h3></div>
        {services.length===0?<Empty label="service"/>:services.map((sv,i)=>(<div key={i} style={{padding:"12px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",alignItems:"center",gap:12}}>
          <div style={{width:8,height:8,borderRadius:4,background:svcStatC[sv.status],boxShadow:`0 0 8px ${svcStatC[sv.status]}44`,flexShrink:0}}/>
          <div style={{flex:1,minWidth:0}}>
            <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:2}}>
              <span style={{fontSize:13*s,fontWeight:700,color:t.tx}}>{sv.name}</span>
              <span style={{fontSize:9,fontWeight:700,color:svcStatC[sv.status],textTransform:"uppercase"}}>{sv.status}</span>
            </div>
            <span style={{fontSize:11,color:t.tD}}>{sv.detail}</span>
          </div>
        </div>))}
      </Glass>

      <Glass style={{overflow:"hidden"}}>
        <div style={{padding:"14px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <h3 style={{margin:0,fontSize:14*s,fontWeight:700,color:t.tx}}>Feeds</h3>
          {feeds.length>0&&<div style={{display:"flex",gap:8}}>
            <span style={{fontSize:10,color:"#34d399",fontWeight:600}}>{activeFeeds} active</span>
            {inactiveFeeds>0&&<span style={{fontSize:10,color:"#f87171",fontWeight:600}}>{inactiveFeeds} inactive</span>}
          </div>}
        </div>
        {feeds.length===0?<Empty label="feed"/>:feeds.map((f,i)=>(<div key={f.name||i} style={{padding:"10px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",alignItems:"center",gap:12}}>
          <div style={{width:8,height:8,borderRadius:4,background:feedStatC(f),boxShadow:`0 0 8px ${feedStatC(f)}44`,flexShrink:0}}/>
          <div style={{flex:1,minWidth:0}}>
            <span style={{fontSize:12*s,fontWeight:700,color:t.tx,fontFamily:"'JetBrains Mono',monospace"}}>{f.name}</span>
            <span style={{fontSize:10,color:t.tD,marginLeft:8,wordBreak:"break-all"}}>{f.source}</span>
          </div>
          <div style={{textAlign:"right",flexShrink:0}}>
            <p style={{margin:0,fontSize:11,color:t.tM,fontFamily:"'JetBrains Mono',monospace"}}>{f.fps} FPS</p>
            <p style={{margin:"1px 0 0",fontSize:10,color:t.tF}}>{f.violations_count} violations · {f.vehicles_tracked} tracked</p>
          </div>
          <span style={{fontSize:10,fontWeight:700,color:feedStatC(f),textTransform:"uppercase"}}>{f.is_active?"active":"inactive"}</span>
        </div>))}
      </Glass>
    </div>
  </div>);
}

/* ═══ AUDIT LOG PAGE ═══ */
function AuditLog({auditLog}){
  const t=T[useContext(ThC)];const s=sc(useContext(StC).fontSize);
  const[search,sSearch]=useState("");const[actFilter,sActFilter]=useState("all");const[offFilter,sOffFilter]=useState("all");
  // The gateway's ACTUAL audit vocabulary (gateway/audit.py _PREFIX). The old
  // list here filtered on renderer-invented names like "approved"/"revised",
  // which match nothing the server ever writes — so those filters silently
  // returned an empty log.
  const ACTIONS=[
    {k:"review_approved",l:"Approved",c:"#34d399"},
    {k:"review_dismissed",l:"Dismissed",c:"#f87171"},
    {k:"review_reopened",l:"Reopened",c:"#f59e0b"},
    {k:"review_notes",l:"Notes edited",c:"#a78bfa"},
    {k:"pinned",l:"Pinned",c:"#a78bfa"},
    {k:"evidence_accessed",l:"Evidence viewed",c:"#60a5fa"},
    {k:"violation_viewed",l:"Case viewed",c:"#60a5fa"},
    {k:"login",l:"Sign-in",c:"#60a5fa"},
    {k:"user_admin",l:"User admin",c:"#f59e0b"},
    {k:"camera_change",l:"Camera change",c:"#f59e0b"},
    {k:"service_change",l:"Service change",c:"#f59e0b"},
  ];
  const actionC=Object.fromEntries(ACTIONS.map(a=>[a.k,a.c]));
  const actionL=Object.fromEntries(ACTIONS.map(a=>[a.k,a.l]));
  const officers=[...new Set(auditLog.map(l=>l.officer))];
  let filtered=[...auditLog];
  if(search){const q=search.toLowerCase();filtered=filtered.filter(l=>(l.violationId||"").toLowerCase().includes(q)||(l.officer||"").toLowerCase().includes(q)||(l.notes||"").toLowerCase().includes(q));}
  if(actFilter!=="all")filtered=filtered.filter(l=>l.action===actFilter);
  if(offFilter!=="all")filtered=filtered.filter(l=>l.officer===offFilter);
  filtered.sort((a,b)=>new Date(b.at)-new Date(a.at));
  return(<div>
    <h2 style={{fontSize:20*s,fontWeight:800,color:t.tx,margin:"0 0 20px"}}>Audit Log</h2>
    <Glass style={{overflow:"hidden"}}>
      <div style={{padding:"12px 18px",display:"flex",gap:8,alignItems:"center",borderBottom:`1px solid ${t.dv}`}}>
        <div style={{flex:1,position:"relative"}}><input value={search} onChange={e=>sSearch(e.target.value)} placeholder="Search violations, officers..." style={{width:"100%",padding:"7px 10px 7px 28px",borderRadius:8,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tx,fontSize:12,outline:"none",boxSizing:"border-box"}}/><span style={{position:"absolute",left:10,top:"50%",transform:"translateY(-50%)",fontSize:11,color:t.tF,pointerEvents:"none"}}>⌕</span></div>
        <Sel value={actFilter} onChange={e=>sActFilter(e.target.value)} options={[{k:"all",l:"All actions"},...ACTIONS.map(a=>({k:a.k,l:a.l}))]}/>
        <Sel value={offFilter} onChange={e=>sOffFilter(e.target.value)} options={[{k:"all",l:"All officers"},...officers.map(o=>({k:o,l:o}))]}/>
      </div>
      <div style={{maxHeight:500,overflowY:"auto"}}>
        {filtered.map(l=>(<div key={l.id} style={{padding:"10px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",alignItems:"center",gap:12}}>
          <span title={l.action} style={{fontSize:10,fontWeight:700,color:actionC[l.action]||t.tx,textTransform:"uppercase",width:110,flexShrink:0}}>{actionL[l.action]||l.action}</span>
          <span style={{fontSize:12,fontWeight:700,color:t.tx,fontFamily:"'JetBrains Mono',monospace",width:140,flexShrink:0}}>{l.violationId}</span>
          <span style={{fontSize:12,color:t.tM,flex:1}}>{l.officer}</span>
          {l.notes&&<span style={{fontSize:11,color:t.tD,fontStyle:"italic",flex:1,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>"{l.notes}"</span>}
          <span style={{fontSize:10,color:t.tF,fontFamily:"'JetBrains Mono',monospace",flexShrink:0}}>{fTF(l.at)} · {tS(l.at)}</span>
        </div>))}
        {filtered.length===0&&<p style={{padding:20,textAlign:"center",color:t.tF}}>No matching entries</p>}
      </div>
    </Glass>
  </div>);
}

/* ═══ SESSION TIMEOUT WARNING ═══ */
function TimeoutWarning({left,onDismiss}){
  const t=T[useContext(ThC)];const m=Math.floor(left/60),s=left%60;
  return(<div style={{position:"fixed",inset:0,zIndex:10000,background:"rgba(0,0,0,.6)",display:"flex",alignItems:"center",justifyContent:"center"}}>
    <div style={{background:t.fD,border:`1px solid ${t.fDB}`,borderRadius:16,padding:"28px 32px",maxWidth:380,textAlign:"center"}}>
      <p style={{fontSize:14,color:"#f59e0b",fontWeight:700,margin:"0 0 8px"}}>⚠ Session Expiring</p>
      <p style={{fontSize:32,fontWeight:800,color:t.tx,margin:"0 0 12px",fontFamily:"'JetBrains Mono',monospace"}}>{m}:{String(s).padStart(2,"0")}</p>
      <p style={{fontSize:13,color:t.tD,margin:"0 0 20px"}}>Click below or move your mouse to stay active</p>
      <button onClick={onDismiss} style={{padding:"10px 28px",borderRadius:10,border:"none",background:"linear-gradient(135deg,#6366f1,#8b5cf6)",color:"#fff",fontSize:14,fontWeight:700,cursor:"pointer"}}>Stay Active</button>
    </div>
  </div>);
}

/* ═══ TRACK OVERLAY (canvas bbox player, Phase 3 CPU-erasure) ═══ */
function TrackOverlay({videoRef:vR,tracksData:td,active}){
  const cvRef=useRef(null);
  useEffect(()=>{
    const video=vR.current,canvas=cvRef.current;
    if(!video||!canvas)return;
    let cancelled=false,rafId=null,rvfcId=null;
    const ctx=canvas.getContext("2d");
    const draw=()=>{
      if(cancelled)return;
      const dpr=window.devicePixelRatio||1;
      const w=video.clientWidth,h=video.clientHeight;
      const pw=Math.max(1,Math.round(w*dpr)),ph=Math.max(1,Math.round(h*dpr));
      if(canvas.width!==pw||canvas.height!==ph){canvas.width=pw;canvas.height=ph;}
      ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.clearRect(0,0,w,h);
      if(!active||!td||!video.videoWidth||!video.videoHeight)return;
      const frame=findFrameAtTime(td.frames,td.clip_start_pts_ns,video.currentTime);
      if(!frame||!frame.tracks)return;
      const box=computeContentBox(w,h,video.videoWidth,video.videoHeight);
      for(const tr of frame.tracks){
        if(!tr.bbox||tr.bbox.length!==4)continue;
        const isV=td.violation_track_id!=null&&tr.id===td.violation_track_id;
        const[x1,y1,x2,y2]=scaleBBoxToBox(tr.bbox,td.ai_resolution,box);
        ctx.lineWidth=isV?3:1.5;
        ctx.strokeStyle=isV?"#f87171":"#34d399";
        ctx.strokeRect(x1,y1,x2-x1,y2-y1);
        const label=trackLabel(tr);
        if(label){
          ctx.font="600 11px 'JetBrains Mono',monospace";
          const tw=ctx.measureText(label).width;
          const lx=Math.max(0,x1),ly=Math.max(13,y1);
          ctx.fillStyle=isV?"rgba(248,113,113,.9)":"rgba(52,211,153,.9)";
          ctx.fillRect(lx,ly-13,tw+8,15);
          ctx.fillStyle="#0a0f0c";
          ctx.fillText(label,lx+4,ly-2);
        }
      }
    };
    const loop=()=>{
      if(cancelled)return;
      draw();
      if(typeof video.requestVideoFrameCallback==="function"){
        rvfcId=video.requestVideoFrameCallback(loop);
      }else if(!video.paused){
        rafId=requestAnimationFrame(loop);
      }
    };
    const onPlay=()=>{if(typeof video.requestVideoFrameCallback!=="function")loop();};
    let ro=null;
    video.addEventListener("play",onPlay);
    video.addEventListener("seeked",draw);
    video.addEventListener("pause",draw);
    video.addEventListener("loadedmetadata",draw);
    if(typeof ResizeObserver!=="undefined"){ro=new ResizeObserver(draw);ro.observe(video);}
    else window.addEventListener("resize",draw);
    loop();
    return()=>{
      cancelled=true;
      video.removeEventListener("play",onPlay);
      video.removeEventListener("seeked",draw);
      video.removeEventListener("pause",draw);
      video.removeEventListener("loadedmetadata",draw);
      if(ro)ro.disconnect();else window.removeEventListener("resize",draw);
      if(rafId)cancelAnimationFrame(rafId);
      if(rvfcId&&typeof video.cancelVideoFrameCallback==="function")video.cancelVideoFrameCallback(rvfcId);
    };
  },[vR,td,active]);
  return(<canvas ref={cvRef} style={{position:"absolute",inset:0,width:"100%",height:"100%",pointerEvents:"none",zIndex:1}}/>);
}

/* ═══ VIDEO PLAYER ═══ */
function VP({violation:v,onFullscreen:oFs,compact:cp=false,playing:pl,setPlaying:sPl,showAI:ai,setShowAI:sAi,onPrev:oP,onNext:oN,showNav:sN=false}){
  const st=useContext(StC),c=useContext(CC);
  const[prog,sProg]=useState(0);
  const[dur,sDur]=useState(0);
  const[spd,sSpd]=useState(st.playbackSpeed||1);
  const[annotatedUrl,sAnnotatedUrl]=useState(null);
  const[rawUrl,sRawUrl]=useState(null);
  const[ssUrl,sSsUrl]=useState(null);
  const[vidErr,sVidErr]=useState(false);
  const[imgErr,sImgErr]=useState(false);
  const[tracksData,sTracksData]=useState(null);
  const[tracksChecked,sTracksChecked]=useState(false);
  const[overlayOn,sOverlayOn]=useState(true);
  const vidRef=useRef(null);
  const vis=useAH(pl,st.autoHideDelay||3);
  const fade={opacity:vis?1:0,transition:"opacity .4s",pointerEvents:vis?"auto":"none"};
  const hasRemote=!!(v&&(v.remoteClipUrl||v.remoteScreenshotUrl));
  // The rack is retiring burned-in annotated clips: NEW evidence only ships
  // clip_raw.mp4 (+ tracks.json). If there's no annotated clip, "AI" mode
  // falls back to raw rather than showing nothing — the AI/RAW toggle still
  // works for OLD evidence that has both.
  const effectiveAi=ai&&!!annotatedUrl;
  const clipUrl=effectiveAi?annotatedUrl:(rawUrl||annotatedUrl);
  const isRawPlayback=!!clipUrl&&clipUrl===rawUrl;

  useEffect(()=>{
    let cancelled=false;
    sAnnotatedUrl(null);sRawUrl(null);sSsUrl(null);sVidErr(false);sImgErr(false);sProg(0);sDur(0);
    sTracksData(null);sTracksChecked(false);sOverlayOn(true);
    if(!v||!hasRemote){return;}
    // Case-bound: the gateway presigns THIS violation's own stored evidence
    // and audits the access. The renderer never passes an object key.
    getEvidenceUrls(v.id).then(res=>{
      if(cancelled||!res||!res.ok)return;
      if(res.clipUrl)sAnnotatedUrl(res.clipUrl);
      if(res.rawUrl)sRawUrl(res.rawUrl);
      if(res.screenshotUrl)sSsUrl(res.screenshotUrl);
      if(!res.tracksUrl){sTracksChecked(true);return;}
      fetchTracksJson(res.tracksUrl).then(raw=>{
        if(cancelled)return;
        const parsed=parseTracksSidecar(raw);
        sTracksData(parsed);
        sTracksChecked(true);
        if(parsed)sOverlayOn(true); // default ON whenever a sidecar loads
      });
    }).catch(()=>{});
    return()=>{cancelled=true;};
    // Re-fetch when the CASE changes *or* when its evidence pointers change —
    // evidence can land (or be replaced) while a reviewer has the case open.
  },[v?.id,v?.remoteClipUrl,v?.remoteRawClipUrl,v?.remoteScreenshotUrl]);

  // Swapping AI-annotated <-> RAW is a change of SOURCE for the same moment of
  // the same incident, not a new clip: assigning src + load() rewinds to 0, so
  // the reviewer lost their place every time they checked the raw footage.
  // Keep the playhead across the swap and only start from 0 for a new case.
  const lastSrc=useRef({id:null,url:null});
  useEffect(()=>{
    sVidErr(false);
    const el=vidRef.current;
    if(!el||!clipUrl)return;
    if(lastSrc.current.url===clipUrl)return; // same source already loaded
    const sameCase=lastSrc.current.id===(v?.id??null)&&!!lastSrc.current.url;
    const resumeAt=sameCase&&Number.isFinite(el.currentTime)?el.currentTime:0;
    lastSrc.current={id:v?.id??null,url:clipUrl};
    const onMeta=()=>{
      el.removeEventListener("loadedmetadata",onMeta);
      if(resumeAt>0){
        // Clamp: the raw and annotated encodes can differ by a frame or two.
        try{el.currentTime=el.duration?Math.min(resumeAt,el.duration):resumeAt;}catch{/* not seekable yet */}
      }
    };
    el.addEventListener("loadedmetadata",onMeta);
    el.src=clipUrl;el.load();
    return()=>el.removeEventListener("loadedmetadata",onMeta);
  },[clipUrl,v?.id]);

  useEffect(()=>{
    const el=vidRef.current;if(!el||!clipUrl)return;
    if(pl){el.play().catch(()=>{});}else{el.pause();}
  },[pl,clipUrl]);

  useEffect(()=>{
    const el=vidRef.current;if(!el)return;
    el.playbackRate=spd;
  },[spd,clipUrl]);

  const onTimeUpdate=useCallback(()=>{
    const el=vidRef.current;if(!el||!el.duration)return;
    sProg((el.currentTime/el.duration)*100);
  },[]);

  const onLoaded=useCallback(()=>{
    const el=vidRef.current;if(el)sDur(el.duration||0);
  },[]);

  const onEnded=useCallback(()=>{sPl(false);sProg(100);},[]);

  const seekTo=useCallback(e=>{
    const r=e.currentTarget.getBoundingClientRect();
    const pct=(e.clientX-r.left)/r.width;
    const el=vidRef.current;
    if(el&&el.duration){el.currentTime=pct*el.duration;sProg(pct*100);}
    else{sProg(pct*100);}
  },[]);

  const fmtTime=s=>{if(!s||!isFinite(s))return"0:00";const m=Math.floor(s/60);return m+":"+String(Math.floor(s%60)).padStart(2,"0");};
  const curTime=dur?(prog/100)*dur:0;

  return(<div style={{overflow:"hidden",borderRadius:cp?0:14,border:cp?"none":"1px solid rgba(255,255,255,.1)",background:"#000",height:cp?"100%":undefined,display:"flex",flexDirection:"column"}}>
    <div style={{position:"relative",background:"#000",height:cp?"100%":250,flex:cp?1:undefined,display:"flex",alignItems:"center",justifyContent:"center",minHeight:cp?0:250,overflow:"hidden"}}>
      {clipUrl&&!vidErr?(
        <video key={clipUrl} ref={vidRef} src={clipUrl} poster={ssUrl||undefined} onTimeUpdate={onTimeUpdate} onLoadedMetadata={onLoaded} onEnded={onEnded} onError={()=>sVidErr(true)} preload="metadata" playsInline style={{position:"absolute",inset:0,width:"100%",height:"100%",objectFit:"contain"}}/>
      ):ssUrl&&!imgErr?(
        <img src={ssUrl} alt="Evidence screenshot" onError={()=>sImgErr(true)} style={{position:"absolute",inset:0,width:"100%",height:"100%",objectFit:"contain"}}/>
      ):(
        <div style={{position:"absolute",inset:0,background:"linear-gradient(135deg,#0c0f1a,#141b2d,#0d1525)",display:"flex",alignItems:"center",justifyContent:"center"}}>
          <span style={{fontSize:12,color:"rgba(255,255,255,.3)",fontFamily:"'JetBrains Mono',monospace"}}>{(vidErr||imgErr)?"Failed to load evidence":"No evidence available"}</span>
        </div>
      )}
      {clipUrl&&!vidErr&&isRawPlayback&&overlayOn&&tracksData&&<TrackOverlay videoRef={vidRef} tracksData={tracksData} active={true}/>}
      {v&&clipUrl&&!vidErr&&<div style={{position:"absolute",top:10,left:12,pointerEvents:"none",display:"flex",gap:6,alignItems:"center"}}><span style={{fontSize:9,color:effectiveAi?"rgba(167,139,250,.7)":"rgba(52,211,153,.7)",fontFamily:"'JetBrains Mono',monospace",background:"rgba(0,0,0,.5)",padding:"3px 8px",borderRadius:5}}>{effectiveAi?"AI ANNOTATED":"RAW FOOTAGE"}</span>{isRawPlayback&&tracksChecked&&!tracksData&&<span style={{fontSize:9,color:"rgba(255,255,255,.4)",fontFamily:"'JetBrains Mono',monospace",background:"rgba(0,0,0,.5)",padding:"3px 8px",borderRadius:5}}>no overlay data — older evidence</span>}</div>}
      <div style={fade}>{clipUrl&&!vidErr&&!pl&&<button onClick={()=>sPl(true)} style={{position:"relative",zIndex:2,width:54,height:54,borderRadius:"50%",background:"rgba(255,255,255,.08)",border:"1.5px solid rgba(255,255,255,.25)",cursor:"pointer",display:"flex",alignItems:"center",justifyContent:"center"}}><div style={{width:0,height:0,borderLeft:"15px solid rgba(255,255,255,.9)",borderTop:"9px solid transparent",borderBottom:"9px solid transparent",marginLeft:4}}/></button>}<div style={{position:"absolute",bottom:10,left:12,fontSize:10,fontFamily:"'JetBrains Mono',monospace",color:"rgba(255,255,255,.5)",background:"rgba(0,0,0,.4)",padding:"3px 8px",borderRadius:6}}>{v?.camera} · {v?fT(v.date,st.timeFormat):""}</div></div>
      {oFs&&<button onClick={oFs} style={{position:"absolute",top:12,right:12,background:"rgba(255,255,255,.08)",border:"1px solid rgba(255,255,255,.15)",borderRadius:6,padding:"4px 8px",cursor:"pointer",color:"rgba(255,255,255,.6)",fontSize:12,zIndex:3}}>⛶</button>}
    </div>
    <div style={{...fade,padding:"10px 14px",display:"flex",alignItems:"center",gap:10,background:"transparent",flexShrink:0}}>
      {sN&&oP&&<button onClick={oP} style={{background:"none",border:"none",color:"rgba(255,255,255,.5)",cursor:"pointer",fontSize:12}}>⏮</button>}
      <button onClick={()=>sPl(!pl)} style={{background:"none",border:"none",color:"rgba(255,255,255,.7)",cursor:"pointer",fontSize:14}}>{pl?"⏸":"▶"}</button>
      {sN&&oN&&<button onClick={oN} style={{background:"none",border:"none",color:"rgba(255,255,255,.5)",cursor:"pointer",fontSize:12}}>⏭</button>}
      <div style={{flex:1,height:3,borderRadius:10,background:"rgba(255,255,255,.08)",overflow:"hidden",cursor:"pointer"}} onClick={seekTo}><div style={{width:`${prog}%`,height:"100%",background:"linear-gradient(90deg,#818cf8,#a78bfa)",borderRadius:10}}/></div>
      <span style={{fontSize:10,color:"rgba(255,255,255,.4)",fontFamily:"'JetBrains Mono',monospace"}}>{fmtTime(curTime)}/{fmtTime(dur)}</span>
      <button onClick={()=>{const i=SPEEDS.indexOf(spd);sSpd(SPEEDS[(i+1)%SPEEDS.length]);}} style={{padding:"3px 8px",borderRadius:6,border:"1px solid rgba(167,139,250,.2)",background:spd!==1?"rgba(167,139,250,.2)":"rgba(255,255,255,.04)",color:spd!==1?"#c4b5fd":"rgba(255,255,255,.4)",fontSize:10,fontWeight:700,cursor:"pointer",fontFamily:"'JetBrains Mono',monospace"}}>{spd}x</button>
      {tracksData&&<button onClick={()=>sOverlayOn(o=>!o)} title="Toggle detection-box overlay" style={{padding:"3px 8px",fontSize:10,borderRadius:6,cursor:"pointer",fontWeight:600,background:overlayOn?"rgba(52,211,153,.2)":"rgba(255,255,255,.04)",color:overlayOn?"#34d399":"rgba(255,255,255,.35)",border:`1px solid ${overlayOn?"rgba(52,211,153,.3)":"rgba(255,255,255,.06)"}`}}>▢ OVERLAY</button>}
      <div style={{display:"flex",gap:4}}>{["AI","RAW"].map(m=>(<button key={m} onClick={()=>sAi(m==="AI")} style={{padding:"3px 8px",fontSize:10,borderRadius:6,cursor:"pointer",fontWeight:600,background:(m==="AI"?ai:!ai)?"rgba(167,139,250,.25)":"rgba(255,255,255,.04)",color:(m==="AI"?ai:!ai)?"#c4b5fd":"rgba(255,255,255,.35)",border:`1px solid ${(m==="AI"?ai:!ai)?"rgba(167,139,250,.3)":"rgba(255,255,255,.06)"}`}}>{m}</button>))}</div>
    </div>
  </div>);
}

/* ═══ SPLASH SCREEN ═══ */
function SplashScreen({onDone}){
  // Honest boot state. The old splash animated a random progress bar through
  // invented steps ("Authenticating session...", "Syncing camera feeds...")
  // that corresponded to no actual work — it looked identical whether the
  // gateway was up or down. This reports the ONE thing that is really checked
  // before sign-in: can the desk reach the review gateway?
  const[ver,sVer]=useState("");
  const[st,sSt]=useState({phase:"probing",msg:"Contacting review gateway…",url:""});
  const probe=useCallback(()=>{
    sSt({phase:"probing",msg:"Contacting review gateway…",url:""});
    if(typeof window==="undefined"||!window.hopeSystem){
      sSt({phase:"error",msg:"Desktop bridge unavailable — run H.O.P.E. Review as the desktop app",url:""});
      return;
    }
    window.hopeSystem.gatewayHealth().then(r=>{
      if(r&&r.ok){sSt({phase:"ok",msg:"Review gateway ready",url:r.url||""});setTimeout(onDone,450);}
      else sSt({phase:"error",msg:(r&&r.error)||"Review gateway unreachable",url:(r&&r.url)||""});
    }).catch(e=>sSt({phase:"error",msg:String(e&&e.message||e),url:""}));
  },[onDone]);
  useEffect(()=>{
    if(typeof window!=="undefined"&&window.hopeUpdater)window.hopeUpdater.getVersion().then(v=>{if(v)sVer(v);}).catch(()=>{});
    probe();
  },[probe]);
  const bad=st.phase==="error";
  return(<div style={{minHeight:"100vh",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",background:"#080b16",fontFamily:"'Inter',sans-serif"}}>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
    <style>{`@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}} @keyframes indeterminate{0%{transform:translateX(-100%)}100%{transform:translateX(300%)}}`}</style>
    <div style={{animation:"fadeIn .8s ease-out",marginBottom:32}}>
      <SovFull height={60} color="#fff"/>
    </div>
    <h1 style={{fontSize:28,fontWeight:800,color:"#fff",letterSpacing:6,margin:"0 0 6px",animation:"fadeIn .8s ease-out .2s both"}}>H.O.P.E.</h1>
    <p style={{fontSize:10,color:"rgba(255,255,255,.3)",letterSpacing:4,textTransform:"uppercase",margin:"0 0 40px",animation:"fadeIn .8s ease-out .4s both"}}>Help · Observe · Protect · Enforce</p>
    <div style={{width:320,animation:"fadeIn .8s ease-out .6s both"}}>
      <div style={{height:3,borderRadius:10,background:"rgba(255,255,255,.06)",overflow:"hidden",marginBottom:12}}>
        {st.phase==="probing"
          ?<div style={{width:"33%",height:"100%",borderRadius:10,background:"linear-gradient(90deg,#6366f1,#a78bfa)",animation:"indeterminate 1.1s ease-in-out infinite"}}/>
          :<div style={{width:"100%",height:"100%",borderRadius:10,background:bad?"#f87171":"linear-gradient(90deg,#6366f1,#a78bfa)"}}/>}
      </div>
      <p style={{fontSize:11,color:bad?"#f87171":"rgba(255,255,255,.45)",margin:0,textAlign:"center"}}>{bad?"✕ ":st.phase==="ok"?"✓ ":""}{st.msg}</p>
      {st.url&&<p style={{fontSize:10,color:"rgba(255,255,255,.2)",margin:"6px 0 0",textAlign:"center",fontFamily:"'JetBrains Mono',monospace"}}>{st.url}</p>}
      {bad&&<div style={{display:"flex",gap:10,justifyContent:"center",marginTop:16}}>
        <button onClick={probe} style={{padding:"7px 18px",borderRadius:9,border:"none",background:"linear-gradient(135deg,#6366f1,#8b5cf6)",color:"#fff",fontSize:12,fontWeight:700,cursor:"pointer"}}>Retry</button>
        <button onClick={onDone} style={{padding:"7px 18px",borderRadius:9,border:"1px solid rgba(255,255,255,.12)",background:"transparent",color:"rgba(255,255,255,.5)",fontSize:12,fontWeight:600,cursor:"pointer"}}>Continue offline</button>
      </div>}
    </div>
    <p style={{position:"absolute",bottom:24,fontSize:9,color:"rgba(255,255,255,.15)",letterSpacing:2}}>SOVALIUS CORPORATION{ver?` · v${ver}`:""}</p>
  </div>);
}

/* ═══ UPDATE PROMPT ═══ */
function UpdatePrompt({info,onUpdate,onSkip,onLater}){
  const[dl,sDl]=useState(false);
  const pct=info?.percent||0;
  return(<div style={{minHeight:"100vh",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",background:"linear-gradient(135deg,#0a0a0f 0%,#12121a 50%,#0d0d14 100%)",fontFamily:"'Inter',sans-serif",padding:40}}>
    <style>{`@keyframes fadeIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}`}</style>
    <div style={{animation:"fadeIn .5s ease-out",marginBottom:28}}><SovMark size={36} color="#a78bfa"/></div>
    <h2 style={{fontSize:22,fontWeight:800,color:"#fff",margin:"0 0 8px",letterSpacing:2}}>Update Available</h2>
    <p style={{fontSize:13,color:"rgba(255,255,255,.45)",margin:"0 0 28px"}}>
      Version <span style={{color:"#a78bfa",fontWeight:700,fontFamily:"'JetBrains Mono',monospace"}}>{info?.version||"?"}</span> is ready
    </p>
    {info?.releaseNotes&&<div style={{maxWidth:420,maxHeight:120,overflow:"auto",background:"rgba(255,255,255,.03)",borderRadius:10,border:"1px solid rgba(255,255,255,.06)",padding:"12px 16px",marginBottom:24,fontSize:11,color:"rgba(255,255,255,.5)",lineHeight:1.6}}>{info.releaseNotes}</div>}
    {dl&&<div style={{width:300,marginBottom:24,animation:"fadeIn .3s ease-out"}}>
      <div style={{height:4,borderRadius:10,background:"rgba(255,255,255,.06)",overflow:"hidden"}}>
        <div style={{width:`${pct}%`,height:"100%",borderRadius:10,background:"linear-gradient(90deg,#6366f1,#a78bfa)",transition:"width .2s"}}/>
      </div>
      <p style={{fontSize:10,color:"rgba(255,255,255,.3)",margin:"6px 0 0",textAlign:"center",fontFamily:"'JetBrains Mono',monospace"}}>{pct}%</p>
    </div>}
    {info?.status==="ready"?
      <button onClick={onUpdate} style={{padding:"10px 36px",borderRadius:10,border:"none",background:"linear-gradient(135deg,#6366f1,#8b5cf6)",color:"#fff",fontSize:13,fontWeight:700,cursor:"pointer",marginBottom:12,letterSpacing:1}}>Install & Restart</button>
    :!dl?<div style={{display:"flex",gap:10}}>
      <button onClick={()=>{sDl(true);onUpdate();}} style={{padding:"10px 28px",borderRadius:10,border:"none",background:"linear-gradient(135deg,#6366f1,#8b5cf6)",color:"#fff",fontSize:13,fontWeight:700,cursor:"pointer",letterSpacing:1}}>Update Now</button>
    </div>:null}
    {!dl&&<div style={{display:"flex",gap:16,marginTop:14}}>
      <button onClick={onSkip} style={{padding:"6px 18px",borderRadius:8,border:"1px solid rgba(255,255,255,.08)",background:"transparent",color:"rgba(255,255,255,.4)",fontSize:11,fontWeight:600,cursor:"pointer"}}>Skip Version</button>
      <button onClick={onLater} style={{padding:"6px 18px",borderRadius:8,border:"1px solid rgba(255,255,255,.08)",background:"transparent",color:"rgba(255,255,255,.4)",fontSize:11,fontWeight:600,cursor:"pointer"}}>Remind Later</button>
    </div>}
  </div>);
}

/* ═══ LOGIN ═══ */
function Login({onLogin:oL}){
  const[u,sU]=useState(""),[p,sP]=useState(""),[e,sE]=useState(""),[loading,sLoading]=useState(false);
  const isElectron=typeof window!=="undefined"&&window.hopeAuth;
  const go=async()=>{
    if(!u||!p){sE("Enter credentials");return;}
    sE("");sLoading(true);
    if(isElectron){
      try{
        const res=await window.hopeAuth.login(u,p);
        if(res.ok){oL(res.user);}
        else{sE(res.error||"Login failed");sLoading(false);}
      }catch(err){sE("Connection error");sLoading(false);}
    }else{
      // NO fabricated session. The old branch accepted ANY username/password
      // outside the desktop shell and minted a user holding canApprove /
      // canDismiss — a review desk that looked real, on invented authority.
      // The renderer only ever runs inside Electron in a real deployment.
      sE("This build must run in the H.O.P.E. Review desktop app — no sign-in is available here.");
      sLoading(false);
    }
  };
  return(<div style={{minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center",background:"radial-gradient(ellipse at 20% 50%,rgba(99,102,241,.15) 0%,transparent 50%),#080b16",fontFamily:"'Inter',sans-serif"}}><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap" rel="stylesheet"/><style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style><div style={{width:400,padding:"44px 40px",background:"rgba(14,20,36,.9)",border:"1px solid rgba(255,255,255,.1)",borderRadius:16}}><div style={{textAlign:"center",marginBottom:36}}><div style={{margin:"0 auto 20px"}}><SovFull height={55} color="#fff"/></div><h1 style={{fontSize:26,fontWeight:800,color:"#fff",margin:"0 0 4px",letterSpacing:4}}>H.O.P.E.</h1><p style={{fontSize:10,color:"rgba(255,255,255,.35)",letterSpacing:3,textTransform:"uppercase",margin:"0 0 6px"}}>Help · Observe · Protect · Enforce</p></div><div style={{display:"flex",flexDirection:"column",gap:16}}>{[{l:"Username",v:u,s:sU,ty:"text"},{l:"Password",v:p,s:sP,ty:"password"}].map((fi,i)=>(<div key={i}><label style={{fontSize:10,color:"rgba(255,255,255,.4)",textTransform:"uppercase",letterSpacing:1.5,marginBottom:7,display:"block",fontWeight:600}}>{fi.l}</label><input value={fi.v} onChange={ev=>fi.s(ev.target.value)} type={fi.ty} placeholder={fi.l} onKeyDown={ev=>ev.key==="Enter"&&!loading&&go()} disabled={loading} style={{width:"100%",padding:"12px 16px",borderRadius:12,border:"1px solid rgba(255,255,255,.08)",background:"rgba(255,255,255,.04)",color:"#fff",fontSize:14,outline:"none",boxSizing:"border-box",opacity:loading?.5:1}}/></div>))}{e&&<p style={{color:"#f87171",fontSize:12,margin:0,textAlign:"center"}}>{e}</p>}<button onClick={go} disabled={loading} style={{width:"100%",padding:"13px 0",borderRadius:12,border:"none",background:loading?"rgba(99,102,241,.5)":"linear-gradient(135deg,#6366f1,#8b5cf6)",color:"#fff",fontSize:14,fontWeight:700,cursor:loading?"not-allowed":"pointer",letterSpacing:2,textTransform:"uppercase",display:"flex",alignItems:"center",justifyContent:"center",gap:8}}>{loading&&<div style={{width:16,height:16,border:"2px solid rgba(255,255,255,.3)",borderTopColor:"#fff",borderRadius:"50%",animation:"spin .6s linear infinite"}}/>}{loading?"Authenticating...":"Sign In"}</button></div>{!isElectron&&<p style={{textAlign:"center",fontSize:9,color:"rgba(245,158,11,.6)",marginTop:16,marginBottom:0}}>Desktop shell not detected — sign-in unavailable</p>}<p style={{textAlign:"center",fontSize:10,color:"rgba(255,255,255,.2)",marginTop:isElectron?24:8,letterSpacing:1.5,marginBottom:0}}>Sovalius Corporation · Per aspera ad astra</p></div></div>);
}

/* ═══ DECISION PANEL (with notes history) ═══ */
function DP({violation:v,onAction:oA,user:us,compact:cp=false,approveRef:aR,dismissRef:dR,notesBoxRef:nBR,onUndo:oU,revising:isR}){
  const t=T[useContext(ThC)],st=useContext(StC);const[notes,sN]=useState(v.notes||"");const[done,sD]=useState(null);const lr=useRef(null);const cd=useCD(v.reviewedAt);
  const[busy,sBusy]=useState(null);const[err,sErr]=useState("");
  useEffect(()=>{sN(isR?v.notes||"":"");sD(null);sErr("");sBusy(null);},[v.id,isR]);useEffect(()=>{if(nBR)nBR.current=lr.current;});
  // Enforcement gate, shown BEFORE the reviewer commits. citable===false is
  // the rack's "this can never become a citation" verdict and the gateway
  // refuses to record an approval for it; a case with no evidence at all is
  // equally un-approvable. Both are surfaced here so the reviewer is never
  // surprised by a server refusal.
  const noEvidence=!v.remoteClipUrl&&!v.remoteRawClipUrl&&!v.remoteScreenshotUrl;
  const blockApprove=v.citable===false?(v.gateReason||"Marked non-citable by the enforcement gate")
    :noEvidence?"No evidence is attached to this case":"";
  // A DECISION IS ONLY REAL ONCE THE SERVER SAYS SO. `done` is set from the
  // gateway's confirmation, never optimistically — the old code set it before
  // the write and showed "CONFIRMED" for rejected decisions.
  const doA=async s=>{
    const ml=st.minNoteLength||0;if(!notes.trim()||notes.trim().length<ml)return;
    if(s==="approved"&&blockApprove){sErr(`Cannot approve — ${blockApprove}`);return;}
    if(busy)return;
    sErr("");sBusy(s);
    const res=await oA(v.id,s,notes);
    sBusy(null);
    if(res&&res.ok){sD(s);}else{sErr((res&&res.error)||"The decision was not recorded");}
  };
  useEffect(()=>{if(aR)aR.current=()=>doA("approved");if(dR)dR.current=()=>doA("dismissed");});
  const ml=st.minNoteLength||0;const ok=notes.trim().length>=Math.max(1,ml);const rv=v.status!=="pending"&&v.reviewedAt&&!isR;const w24=v.reviewedAt&&(Date.now()-new Date(v.reviewedAt).getTime()<86400000);
  if(rv&&!done)return(<div><div style={{padding:14,borderRadius:14,textAlign:"center",background:v.status==="approved"?"rgba(52,211,153,.08)":"rgba(248,113,113,.08)",border:`1px solid ${v.status==="approved"?"rgba(52,211,153,.2)":"rgba(248,113,113,.2)"}`}}><p style={{fontSize:16,margin:"0 0 4px",fontWeight:800,color:v.status==="approved"?"#34d399":"#f87171"}}>{v.status==="approved"?"✓ APPROVED":"✕ DISMISSED"}</p><p style={{fontSize:11,color:t.tD,margin:"0 0 4px"}}>by {v.reviewedBy}</p>{w24&&<p style={{fontSize:12,color:"#f59e0b",margin:0,fontFamily:"'JetBrains Mono',monospace"}}>{cd} to revise</p>}</div>{w24&&<div style={{display:"flex",gap:10,marginTop:10}}><button onClick={async()=>{if(!oU||busy)return;sErr("");sBusy("undo");const r=await oU(v.id);sBusy(null);if(!(r&&r.ok))sErr((r&&r.error)||"The decision could not be reopened");}} disabled={busy==="undo"} style={{flex:1,padding:"9px 0",borderRadius:10,border:"1px solid rgba(248,113,113,.3)",background:"rgba(248,113,113,.08)",color:"#f87171",fontSize:12,fontWeight:700,cursor:busy?"not-allowed":"pointer"}}>{busy==="undo"?"REOPENING…":"↩ Undo"}</button></div>}{err&&<div role="alert" style={{marginTop:10,padding:"9px 12px",borderRadius:8,background:"rgba(248,113,113,.12)",border:"1px solid rgba(248,113,113,.35)",fontSize:12,color:"#f87171",fontWeight:600}}>✕ {err}</div>}</div>);
  if(done)return(<div style={{padding:cp?14:18,borderRadius:14,textAlign:"center",background:done==="approved"?"rgba(52,211,153,.08)":"rgba(248,113,113,.08)"}}><p style={{fontSize:cp?16:20,margin:"0 0 4px",fontWeight:800,color:done==="approved"?"#34d399":"#f87171"}}>{done==="approved"?"✓ CONFIRMED":"✕ DISMISSED"}</p><p style={{fontSize:12,color:"#f59e0b",margin:0,fontFamily:"'JetBrains Mono',monospace"}}>24h to revise</p></div>);
  return(<div>
    {isR&&<><div style={{padding:"8px 12px",borderRadius:8,marginBottom:12,background:"rgba(167,139,250,.1)",border:"1px solid rgba(167,139,250,.2)",fontSize:12,color:"#a78bfa",fontWeight:600}}>✎ Revising — submit new verdict</div><NotesHistory history={v.history}/></>}
    <label style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,marginBottom:7,display:"block",fontWeight:600}}>Notes <Kbd>/</Kbd></label>
    <textarea ref={lr} value={notes} onChange={e=>sN(e.target.value)} rows={cp?2:3} placeholder="Required..." style={{width:"100%",padding:"10px 12px",borderRadius:10,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tx,fontSize:13,fontFamily:"'Inter',sans-serif",resize:"vertical",outline:"none",boxSizing:"border-box"}}/>
    {st.quickNotes?.length>0&&<div style={{display:"flex",flexWrap:"wrap",gap:4,marginTop:6}}>{st.quickNotes.map((q,i)=>(<button key={i} onClick={()=>sN(q)} style={{padding:"2px 8px",borderRadius:5,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tM,fontSize:9,cursor:"pointer"}}>{q.length>25?q.slice(0,25)+"…":q}</button>))}</div>}
    {blockApprove&&<div style={{marginTop:10,padding:"8px 12px",borderRadius:8,background:"rgba(245,158,11,.1)",border:"1px solid rgba(245,158,11,.25)",fontSize:11,color:"#f59e0b",fontWeight:600}}>⚠ Approval blocked — {blockApprove}. This case can still be dismissed.</div>}
    {v.citable===null&&!blockApprove&&<div style={{marginTop:10,padding:"8px 12px",borderRadius:8,background:"rgba(96,165,250,.1)",border:"1px solid rgba(96,165,250,.25)",fontSize:11,color:"#60a5fa",fontWeight:600}}>ℹ Citation eligibility not yet determined — an approval is recorded, but no citation is minted until the enforcement gate confirms.</div>}
    {err&&<div role="alert" style={{marginTop:10,padding:"9px 12px",borderRadius:8,background:"rgba(248,113,113,.12)",border:"1px solid rgba(248,113,113,.35)",fontSize:12,color:"#f87171",fontWeight:600}}>✕ {err}</div>}
    <div style={{display:"flex",gap:10,marginTop:10}}>{(()=>{const aOk=ok&&!busy&&!blockApprove,dOk=ok&&!busy;return(<>
      <button onClick={()=>doA("approved")} disabled={!aOk} title={blockApprove||undefined} style={{flex:1,padding:"11px 0",borderRadius:10,border:"none",background:aOk?"linear-gradient(135deg,#059669,#34d399)":t.iB,color:aOk?"#fff":t.tF,fontSize:13,fontWeight:700,cursor:aOk?"pointer":"not-allowed"}}>{busy==="approved"?"RECORDING…":"✓ APPROVE"}</button>
      <button onClick={()=>doA("dismissed")} disabled={!dOk} style={{flex:1,padding:"11px 0",borderRadius:10,border:"none",background:dOk?"linear-gradient(135deg,#dc2626,#f87171)":t.iB,color:dOk?"#fff":t.tF,fontSize:13,fontWeight:700,cursor:dOk?"pointer":"not-allowed"}}>{busy==="dismissed"?"RECORDING…":"✕ DISMISS"}</button>
    </>);})()}</div>
  </div>);
}
function MT({violation:v}){const t=T[useContext(ThC)],st=useContext(StC);return(<div>{[{l:"Plate",v:v.plate,m:1},{l:"Vehicle",v:v.vehicle},v.speed?{l:"Speed",v:`${v.speed}/${v.limit} km/h`,m:1,c:"#f87171"}:null,{l:"Location",v:v.location},{l:"Camera",v:v.camera,m:1},{l:"Date",v:fD(v.date)},{l:"Time",v:fT(v.date,st.timeFormat),m:1},{l:"Weather",v:v.weather}].filter(Boolean).map((f,i)=>(<div key={i} style={{display:"flex",justifyContent:"space-between",padding:"8px 0",borderBottom:`1px solid ${t.dv}`}}><span style={{fontSize:11,color:t.tD,textTransform:"uppercase",letterSpacing:.8,fontWeight:600}}>{f.l}</span><span style={{fontSize:12,fontWeight:600,color:f.c||t.tx,fontFamily:f.m?"'JetBrains Mono',monospace":"inherit"}}>{f.v}</span></div>))}</div>);}
function INav({violations:vs,currentId:cid,onNav:oN,filter:fl}){const t=T[useContext(ThC)];const fd=fl==="all"?vs:vs.filter(v=>v.status===fl);const idx=fd.findIndex(v=>v.id===cid);const hp=idx>0,hn=idx<fd.length-1;return(<div style={{display:"flex",alignItems:"center",gap:10,justifyContent:"center"}}><button onClick={hp?()=>oN(fd[idx-1]):undefined} style={{padding:"7px 14px",borderRadius:10,border:`1px solid ${hp?"rgba(167,139,250,.3)":t.iBo}`,background:hp?"rgba(167,139,250,.12)":t.iB,color:hp?"#a78bfa":t.tF,fontSize:12,fontWeight:600,cursor:hp?"pointer":"not-allowed"}}>←</button><span style={{fontSize:12,color:t.tD,fontFamily:"'JetBrains Mono',monospace"}}>{idx>=0?idx+1:"-"}/{fd.length}</span><button onClick={hn?()=>oN(fd[idx+1]):undefined} style={{padding:"7px 14px",borderRadius:10,border:`1px solid ${hn?"rgba(167,139,250,.3)":t.iBo}`,background:hn?"rgba(167,139,250,.12)":t.iB,color:hn?"#a78bfa":t.tF,fontSize:12,fontWeight:600,cursor:hn?"pointer":"not-allowed"}}>→</button></div>);}

/* ═══ REVIEW SCREEN ═══ */
function VR({violation:v,violations:vs,onBack:oB,onAction:oA,onNav:oN,filter:fl,setFilter:sFl,user:us,onPin:oP,onUndo:oU,revising:isR}){
  const t=T[useContext(ThC)],st=useContext(StC),kb=useContext(KbC),c=useContext(CC);
  const[pl,sPl]=useState(!!st.autoPlay),[ai,sAi]=useState(st.defaultVideoMode!=="raw"),[cs,sCs]=useState(false),[fs,sFs]=useState(false),[fsBot,sFsBot]=useState(false),[fsRight,sFsRight]=useState(false);
  const[activeCam,setActiveCam]=useState(v.camera);
  const aR=useRef(null),dR=useRef(null),nR=useRef(null);const fd=fl==="all"?vs:vs.filter(x=>x.status===fl);const idx=fd.findIndex(x=>x.id===v.id);
  const s=sc(st.fontSize);const np=st.navPlacement||"bottom";
  const gP=()=>{if(idx>0)oN(fd[idx-1]);};const gN=()=>{if(idx<fd.length-1)oN(fd[idx+1]);};
  useKB(kb,{next:gN,prev:gP,back:()=>{if(fs)sFs(false);else oB();},playPause:()=>sPl(p=>!p),toggleAI:()=>sAi(a=>!a),fullscreen:()=>sFs(f=>!f),exitFullscreen:()=>sFs(false),focusNotes:()=>{if(nR.current)nR.current.focus();},approve:()=>{if(aR.current)aR.current();},dismiss:()=>{if(dR.current)dR.current();},cheatSheet:()=>sCs(x=>!x),pin:()=>oP(v.id),toggleDrawer:()=>{if(fs)sFsBot(b=>!b);}});
  const side=(<div style={{display:"flex",flexDirection:"column",gap:16}}>
    <Glass style={{padding:20}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:14}}><h3 style={{margin:0,fontSize:15*s,fontWeight:700,color:t.tx,fontFamily:"'JetBrains Mono',monospace"}}>{v.id}</h3><div style={{display:"flex",gap:6,alignItems:"center"}}><button onClick={()=>oP(v.id)} style={{background:"none",border:"none",cursor:"pointer",fontSize:16,color:v.pinned?"#f59e0b":t.tF}}>{v.pinned?"★":"☆"}</button><span style={{fontSize:10,padding:"3px 10px",borderRadius:8,fontWeight:700,background:`${c.status[v.status]}15`,color:c.status[v.status],textTransform:"uppercase"}}>{v.status}</span></div></div>
      {v.confidence<(st.confidenceThreshold||80)&&<div style={{padding:"8px 12px",borderRadius:8,marginBottom:12,background:"rgba(248,113,113,.1)",border:"1px solid rgba(248,113,113,.2)",fontSize:11,color:"#f87171",fontWeight:600}}>⚠ Below threshold</div>}
      <div style={{padding:"10px 14px",borderRadius:12,marginBottom:14,background:`${c.type[v.type]}08`,border:`1px solid ${c.type[v.type]}20`,display:"flex",justifyContent:"space-between",alignItems:"center"}}><span style={{fontSize:16*s,fontWeight:800,color:c.type[v.type]}}>{v.type}</span>{v.speed&&<span style={{fontSize:15*s,fontWeight:800,color:c.status.dismissed,fontFamily:"'JetBrains Mono',monospace"}}>{v.speed}/{v.limit}</span>}</div>
      <MT violation={v}/>
    </Glass>
    <Glass style={{padding:20}}><h3 style={{margin:"0 0 12px",fontSize:13*s,fontWeight:700,color:t.tx}}>Confidence</h3><div style={{display:"flex",alignItems:"center",gap:12}}><div style={{flex:1,height:8,borderRadius:10,background:"rgba(128,128,128,.12)",overflow:"hidden"}}><div style={{width:`${v.confidence}%`,height:"100%",borderRadius:10,background:v.confidence>=90?"linear-gradient(90deg,#059669,#34d399)":v.confidence>=80?"linear-gradient(90deg,#d97706,#f59e0b)":"linear-gradient(90deg,#dc2626,#f87171)"}}/></div><span style={{fontSize:18,fontWeight:800,fontFamily:"'JetBrains Mono',monospace",color:v.confidence>=90?"#34d399":v.confidence>=80?"#f59e0b":"#f87171"}}>{v.confidence}%</span></div></Glass>
    <ChainOfCustody history={v.history}/>
    <LinkedViolations current={v} allViolations={vs}/>
  </div>);
  const main=(<div style={{display:"flex",flexDirection:"column",gap:16}}>
    <CameraSwitcher cameras={v.cameras} active={activeCam} onSwitch={setActiveCam}/>
    <VP violation={{...v,camera:activeCam}} playing={pl} setPlaying={sPl} showAI={ai} setShowAI={sAi} showNav={np==="video_controls"} onPrev={gP} onNext={gN} onFullscreen={()=>sFs(true)}/>
    <Glass style={{padding:20}}><h3 style={{margin:"0 0 12px",fontSize:14*s,fontWeight:700,color:t.tx}}>AI Summary</h3><div style={{fontSize:13*s,color:t.tM,lineHeight:1.7,background:"rgba(167,139,250,.06)",padding:16,borderRadius:12,borderLeft:"3px solid #a78bfa"}}>{v.aiSummary}</div></Glass>
    <Glass style={{padding:20}}><h3 style={{margin:"0 0 14px",fontSize:14*s,fontWeight:700,color:t.tx}}>Decision</h3><DP violation={v} onAction={oA} user={us} approveRef={aR} dismissRef={dR} notesBoxRef={nR} onUndo={oU} revising={isR}/>{(np==="below_decision"||np==="both")&&<div style={{marginTop:14}}><INav violations={vs} currentId={v.id} onNav={oN} filter={fl}/></div>}</Glass>
  </div>);
  return(<div>{cs&&<CS2 onClose={()=>sCs(false)} keybinds={kb}/>}
    {fs&&<div style={{position:"fixed",inset:0,zIndex:9999,background:"#000",display:"flex",flexDirection:"column"}}>
      <div style={{flex:1,display:"flex",overflow:"hidden"}}>
        <div style={{flex:1,position:"relative"}}>
          <VP violation={{...v,camera:activeCam}} playing={pl} setPlaying={sPl} showAI={ai} setShowAI={sAi} compact showNav onPrev={gP} onNext={gN} onFullscreen={()=>sFs(false)}/>
        </div>
        <div style={{position:"absolute",right:0,top:0,bottom:fsBot?200:0,width:fsRight?360:0,transition:"width .3s cubic-bezier(.4,0,.2,1)",overflow:"hidden",zIndex:10002,background:t.fD||"rgba(15,20,35,.96)",borderLeft:fsRight?`1px solid ${t.fDB||"rgba(255,255,255,.1)"}`:"none",display:"flex",flexDirection:"column"}}>
          {fsRight&&<div style={{padding:16,overflowY:"auto",flex:1}}>{side}</div>}
        </div>
        <button onClick={()=>sFsRight(r=>!r)} style={{position:"absolute",right:fsRight?360:0,top:"50%",transform:"translateY(-50%)",zIndex:10003,background:t.fD||"rgba(15,20,35,.96)",border:`1px solid ${t.fDB||"rgba(255,255,255,.1)"}`,borderRight:fsRight?"none":undefined,borderLeft:fsRight?undefined:"none",borderRadius:fsRight?"6px 0 0 6px":"0 6px 6px 0",padding:"12px 4px",cursor:"pointer",color:t.tM||"rgba(255,255,255,.55)",fontSize:12,transition:"right .3s cubic-bezier(.4,0,.2,1)"}}>{fsRight?"\u25B6":"\u25C0"}</button>
      </div>
      <div style={{position:"absolute",bottom:0,left:0,right:fsRight?361:0,height:fsBot?"auto":0,maxHeight:fsBot?280:0,transition:"max-height .3s cubic-bezier(.4,0,.2,1)",overflow:"hidden",zIndex:10001,background:t.fD||"rgba(15,20,35,.96)",borderTop:fsBot?`1px solid ${t.fDB||"rgba(255,255,255,.1)"}`:"none"}}>
        {fsBot&&<div style={{padding:"14px 20px"}}><div style={{display:"flex",gap:16,alignItems:"flex-start"}}><div style={{flex:1}}><DP violation={v} onAction={oA} user={us} approveRef={aR} dismissRef={dR} notesBoxRef={nR} onUndo={oU} revising={isR} compact/></div><div style={{display:"flex",alignItems:"center"}}><INav violations={vs} currentId={v.id} onNav={oN} filter={fl}/></div></div></div>}
      </div>
      <button onClick={()=>sFsBot(b=>!b)} style={{position:"absolute",bottom:fsBot?Math.min(280,200):0,left:"50%",transform:"translateX(-50%)",zIndex:10003,background:t.fD||"rgba(15,20,35,.96)",border:`1px solid ${t.fDB||"rgba(255,255,255,.1)"}`,borderBottom:fsBot?"none":undefined,borderTop:fsBot?undefined:"none",borderRadius:fsBot?"6px 6px 0 0":"0 0 6px 6px",padding:"4px 20px",cursor:"pointer",color:t.tM||"rgba(255,255,255,.55)",fontSize:11,transition:"bottom .3s cubic-bezier(.4,0,.2,1)"}}>{fsBot?"\u25BC":"\u25B2"}</button>
    </div>}
    <div style={{display:"flex",justifyContent:"space-between",marginBottom:18}}><div style={{display:"flex",gap:8,alignItems:"center"}}><button onClick={oB} style={{background:t.iB,border:`1px solid ${t.iBo}`,color:"#a78bfa",cursor:"pointer",fontSize:12,padding:"6px 14px",borderRadius:8,fontWeight:600}}>← Back <Kbd>B</Kbd></button>{np==="top"&&<INav violations={vs} currentId={v.id} onNav={oN} filter={fl}/>}</div><button onClick={()=>sCs(x=>!x)} style={{background:t.iB,border:`1px solid ${t.iBo}`,color:t.tD,cursor:"pointer",fontSize:12,padding:"6px 12px",borderRadius:8,fontWeight:600}}>⌨ <Kbd>?</Kbd></button></div>
    <div style={{display:"grid",gridTemplateColumns:st.sidebarPos==="left"?"380px 1fr":"1fr 380px",gap:18}}>{st.sidebarPos==="left"?<>{side}{main}</>:<>{main}{side}</>}</div>
    {(np==="bottom"||np==="both")&&<div style={{position:"sticky",bottom:0,padding:"12px 0",display:"flex",alignItems:"center",justifyContent:"center",gap:16,background:t.bB,borderTop:`1px solid ${t.dv}`,marginTop:16,borderRadius:"12px 12px 0 0",zIndex:50}}><INav violations={vs} currentId={v.id} onNav={oN} filter={fl}/><Sel value={fl} onChange={e=>sFl(e.target.value)} options={[{k:"all",l:"All"},{k:"pending",l:"Pending"},{k:"approved",l:"Approved"},{k:"dismissed",l:"Dismissed"}]}/></div>}
  </div>);
}

/* ═══ DASHBOARD ROWS ═══ */
function QueueRow({v,onSelect,onPin,dense,scale,cols}){
  const t=T[useContext(ThC)],c=useContext(CC),st=useContext(StC);
  const[hov,sHov]=useState(false);const[mp,sMp]=useState({x:0,y:0});
  return(<div onClick={()=>onSelect(v)} onMouseEnter={e=>{sHov(true);sMp({x:e.clientX,y:e.clientY});}} onMouseMove={e=>sMp({x:e.clientX,y:e.clientY})} onMouseLeave={()=>sHov(false)}
    style={{padding:dense?"8px 16px":"12px 16px",borderBottom:`1px solid ${t.dv}`,cursor:"pointer",display:"flex",alignItems:"center",gap:dense?8:12,height:dense?44:56,boxSizing:"content-box",background:hov?t.glH:"transparent"}}>
    {hov&&st.hoverPreview!==false&&<HP v={v} pos={mp}/>}
    <div style={{width:3,height:dense?28:38,borderRadius:3,background:`linear-gradient(180deg,${c.type[v.type]},${c.type[v.type]}66)`,flexShrink:0}}/>
    {v.pinned&&<span style={{fontSize:11,color:"#f59e0b",flexShrink:0}}>★</span>}
    <div style={{flex:1,minWidth:0}}>
      <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:dense?1:3}}><span style={{fontSize:12*scale,fontWeight:700,color:t.tx,fontFamily:"'JetBrains Mono',monospace"}}>{v.id}</span><span style={{fontSize:9,padding:"1px 6px",borderRadius:5,fontWeight:600,background:`${c.type[v.type]}15`,color:c.type[v.type]}}>{v.type}</span></div>
      <div style={{fontSize:11*scale,color:t.tM,display:"flex",gap:6,overflow:"hidden",whiteSpace:"nowrap"}}>{cols.plate&&<span style={{fontFamily:"'JetBrains Mono',monospace",fontWeight:600}}>{v.plate}</span>}{cols.location&&<><span style={{opacity:.3}}>·</span><span>{v.location}</span></>}{cols.speed&&v.speed&&<><span style={{opacity:.3}}>·</span><span style={{color:c.status.dismissed,fontWeight:600,fontFamily:"'JetBrains Mono',monospace"}}>{v.speed}/{v.limit}</span></>}</div>
    </div>
    {cols.time&&<div style={{textAlign:"right",flexShrink:0,width:50}}><p style={{fontSize:10,color:t.tD,margin:0,fontFamily:"'JetBrains Mono',monospace"}}>{fT(v.date,st.timeFormat)}</p><p style={{fontSize:9,color:t.tF,margin:"1px 0 0"}}>{tS(v.date)}</p></div>}
    {cols.confidence&&<CM value={v.confidence}/>}
    <button onClick={e=>{e.stopPropagation();onPin(v.id);}} style={{background:"none",border:"none",cursor:"pointer",fontSize:13,color:v.pinned?"#f59e0b":t.tF,flexShrink:0}}>{v.pinned?"★":"☆"}</button>
  </div>);
}
function ReviewedRow({v,onSelect,onPin,onRevise,onUndo,dense,scale,cols}){
  const t=T[useContext(ThC)],c=useContext(CC),st=useContext(StC);
  const[hov,sHov]=useState(false);const[mp,sMp]=useState({x:0,y:0});
  const w24=v.reviewedAt&&(Date.now()-new Date(v.reviewedAt).getTime()<86400000);
  return(<div onClick={()=>onSelect(v)} onMouseEnter={e=>{sHov(true);sMp({x:e.clientX,y:e.clientY});}} onMouseMove={e=>sMp({x:e.clientX,y:e.clientY})} onMouseLeave={()=>sHov(false)}
    style={{padding:dense?"8px 16px":"12px 16px",borderBottom:`1px solid ${t.dv}`,cursor:"pointer",display:"flex",alignItems:"center",gap:dense?8:12,height:dense?52:64,boxSizing:"content-box",background:hov?t.glH:"transparent"}}>
    {hov&&st.hoverPreview!==false&&<HP v={v} pos={mp}/>}
    <div style={{width:3,height:dense?28:38,borderRadius:3,background:`linear-gradient(180deg,${c.status[v.status]},${c.status[v.status]}66)`,flexShrink:0}}/>
    <div style={{flex:1,minWidth:0}}>
      <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:dense?1:3}}><span style={{fontSize:12*scale,fontWeight:700,color:t.tx,fontFamily:"'JetBrains Mono',monospace"}}>{v.id}</span><span style={{fontSize:9,padding:"1px 6px",borderRadius:5,fontWeight:600,background:`${c.type[v.type]}15`,color:c.type[v.type]}}>{v.type}</span><span style={{fontSize:8,padding:"1px 5px",borderRadius:5,fontWeight:700,background:`${c.status[v.status]}15`,color:c.status[v.status],textTransform:"uppercase"}}>{v.status}</span></div>
      <div style={{fontSize:11*scale,color:t.tM,display:"flex",gap:6,alignItems:"center",overflow:"hidden",whiteSpace:"nowrap"}}>{cols.plate&&<span style={{fontFamily:"'JetBrains Mono',monospace",fontWeight:600}}>{v.plate}</span>}<span style={{opacity:.3}}>·</span><span style={{fontSize:10,color:t.tD}}>{v.reviewedBy}</span><span style={{opacity:.3}}>·</span><CM value={v.confidence}/>{w24&&<CDBadge reviewedAt={v.reviewedAt}/>}</div>
    </div>
    {cols.time&&<div style={{textAlign:"right",flexShrink:0,width:50}}><p style={{fontSize:10,color:t.tD,margin:0,fontFamily:"'JetBrains Mono',monospace"}}>{fT(v.date,st.timeFormat)}</p><p style={{fontSize:9,color:t.tF,margin:"1px 0 0"}}>{tS(v.date)}</p></div>}
    <div style={{width:180,flexShrink:0,display:"flex",justifyContent:"flex-end",gap:6,visibility:w24?"visible":"hidden"}} onClick={e=>e.stopPropagation()}>
      <button onClick={()=>onRevise(v.id)} style={{padding:"8px 14px",borderRadius:10,border:"1px solid rgba(167,139,250,.35)",background:"rgba(167,139,250,.12)",color:"#a78bfa",fontSize:12,fontWeight:700,cursor:"pointer",whiteSpace:"nowrap"}}>✎ Revise</button>
      <button onClick={()=>onUndo(v.id)} style={{padding:"8px 14px",borderRadius:10,border:"1px solid rgba(248,113,113,.35)",background:"rgba(248,113,113,.1)",color:"#f87171",fontSize:12,fontWeight:700,cursor:"pointer",whiteSpace:"nowrap"}}>↩ Undo</button>
    </div>
    <button onClick={e=>{e.stopPropagation();onPin(v.id);}} style={{background:"none",border:"none",cursor:"pointer",fontSize:13,color:v.pinned?"#f59e0b":t.tF,flexShrink:0}}>{v.pinned?"★":"☆"}</button>
  </div>);
}

/* ═══ DASHBOARD ═══ */
function Dash({violations:vs,onSelect:oSel,analytics:an,onPin:oP,onUndo:oU,onRevise:oRv}){
  const t=T[useContext(ThC)],st=useContext(StC),c=useContext(CC);const s=sc(st.fontSize);const dn=st.queueDensity==="compact";
  const[qSe,sQSe]=useState("");const[qSo,sQSo]=useState("time");const[qTF,sQTF]=useState("all");
  const[rSe,sRSe]=useState("");const[rSo,sRSo]=useState("time");const[rSF,sRSF]=useState("all");
  const pending=vs.filter(v=>v.status==="pending");const reviewed=vs.filter(v=>v.status!=="pending");
  let qL=[...pending];if(qSe){const q=qSe.toLowerCase();qL=qL.filter(v=>v.id.toLowerCase().includes(q)||v.plate.toLowerCase().includes(q)||v.location.toLowerCase().includes(q));}if(qTF!=="all")qL=qL.filter(v=>v.type===qTF);if(qSo==="confidence")qL.sort((a,b)=>a.confidence-b.confidence);else if(qSo==="type")qL.sort((a,b)=>a.type.localeCompare(b.type));qL.sort((a,b)=>(b.pinned?1:0)-(a.pinned?1:0));
  let rL=[...reviewed];if(rSe){const q=rSe.toLowerCase();rL=rL.filter(v=>v.id.toLowerCase().includes(q)||v.plate.toLowerCase().includes(q)||v.reviewedBy?.toLowerCase().includes(q));}if(rSF!=="all")rL=rL.filter(v=>v.status===rSF);if(rSo==="confidence")rL.sort((a,b)=>b.confidence-a.confidence);else if(rSo==="type")rL.sort((a,b)=>a.type.localeCompare(b.type));
  const cols=st.queueCols||{plate:true,location:true,confidence:true,speed:true,time:true};const types=[...new Set(vs.map(v=>v.type))];
  return(<div>
    <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:14,marginBottom:20}}>{[{l:"Pending",v:pending.length,c:"#f59e0b",i:"⏳"},{l:"Approved Today",v:an.today.approved,c:"#34d399",i:"✓"},{l:"Dismissed Today",v:an.today.dismissed,c:"#f87171",i:"✕"},{l:"Approval Rate",v:an.approvalRate+"%",c:"#a78bfa",i:"◎"}].map((cd,i)=>(<Glass key={i} hover style={{padding:"18px 16px",position:"relative",overflow:"hidden",cursor:"default"}}><div style={{position:"absolute",top:10,right:14,fontSize:22,opacity:.15}}>{cd.i}</div><p style={{fontSize:10*s,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,margin:"0 0 5px",fontWeight:600}}>{cd.l}</p><p style={{fontSize:26*s,fontWeight:800,margin:0,fontFamily:"'JetBrains Mono',monospace",background:`linear-gradient(135deg,${cd.c},${cd.c}cc)`,WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent"}}>{cd.v}</p></Glass>))}</div>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16,marginBottom:16}}>
      <Glass style={{overflow:"hidden"}}><div style={{padding:"14px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}><h3 style={{margin:0,fontSize:14*s,fontWeight:700,color:t.tx}}>Queue</h3><span style={{fontSize:11,color:t.tF,fontFamily:"'JetBrains Mono',monospace"}}>{qL.length}</span></div><LTB search={qSe} setSearch={sQSe} sort={qSo} setSort={sQSo} filter={qTF} setFilter={sQTF} placeholder="Search..." sortOptions={[{k:"time",l:"Time"},{k:"confidence",l:"Conf"},{k:"type",l:"Type"}]} filterOptions={[{k:"all",l:"All types"},...types.map(ty=>({k:ty,l:ty}))]}/><div style={{maxHeight:320,overflowY:"auto"}}>{qL.map(v=><QueueRow key={v.id} v={v} onSelect={oSel} onPin={oP} dense={dn} scale={s} cols={cols}/>)}{qL.length===0&&<p style={{padding:20,textAlign:"center",color:t.tF}}>No results</p>}</div></Glass>
      <Glass style={{overflow:"hidden"}}><div style={{padding:"14px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}><h3 style={{margin:0,fontSize:14*s,fontWeight:700,color:t.tx}}>Reviewed</h3><span style={{fontSize:11,color:t.tF,fontFamily:"'JetBrains Mono',monospace"}}>{rL.length}</span></div><LTB search={rSe} setSearch={sRSe} sort={rSo} setSort={sRSo} filter={rSF} setFilter={sRSF} placeholder="Search..." sortOptions={[{k:"time",l:"Time"},{k:"confidence",l:"Conf"},{k:"type",l:"Type"}]} filterOptions={[{k:"all",l:"All"},{k:"approved",l:"Approved"},{k:"dismissed",l:"Dismissed"}]}/><div style={{maxHeight:320,overflowY:"auto"}}>{rL.map(v=><ReviewedRow key={v.id} v={v} onSelect={oSel} onPin={oP} onRevise={oRv} onUndo={oU} dense={dn} scale={s} cols={cols}/>)}{rL.length===0&&<p style={{padding:20,textAlign:"center",color:t.tF}}>No results</p>}</div></Glass>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:16}}><Glass style={{padding:18}}><h3 style={{margin:"0 0 12px",fontSize:13*s,fontWeight:700,color:t.tx}}>Activity</h3><MC data={an.hourly} height={55}/></Glass><Glass style={{padding:18}}><h3 style={{margin:"0 0 14px",fontSize:13*s,fontWeight:700,color:t.tx}}>Types</h3>{Object.entries(an.byType).map(([ty,pc])=>(<div key={ty} style={{marginBottom:12}}><div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}><span style={{fontSize:11,color:t.tM}}>{ty}</span><span style={{fontSize:11,fontWeight:700,color:c.type[ty],fontFamily:"'JetBrains Mono',monospace"}}>{pc}%</span></div><div style={{height:4,borderRadius:10,background:"rgba(128,128,128,.12)",overflow:"hidden"}}><div style={{width:`${pc}%`,height:"100%",borderRadius:10,background:`linear-gradient(90deg,${c.type[ty]}88,${c.type[ty]})`}}/></div></div>))}</Glass><Glass style={{padding:18}}><h3 style={{margin:"0 0 12px",fontSize:13*s,fontWeight:700,color:t.tx}}>Stats</h3>{[{l:"Avg Review",v:an.avgReviewTime},{l:"Officers",v:an.officersActive},{l:"Month",v:an.month.total}].map((x,i)=>(<div key={i} style={{display:"flex",justifyContent:"space-between",padding:"7px 0",borderBottom:i<2?`1px solid ${t.dv}`:"none"}}><span style={{fontSize:11,color:t.tD}}>{x.l}</span><span style={{fontSize:12,fontWeight:700,color:t.tx,fontFamily:"'JetBrains Mono',monospace"}}>{x.v}</span></div>))}</Glass></div>
  </div>);
}

/* ═══ ANALYTICS ═══ */
function Analytics({violations:vs}){
  const t=T[useContext(ThC)],c=useContext(CC),s=sc(useContext(StC).fontSize);
  const[an,sAn]=useState(null);const[loading,sLoading]=useState(true);
  const isEl=typeof window!=="undefined"&&window.hopeDb;
  useEffect(()=>{
    if(isEl){window.hopeDb.getAnalytics().then(r=>{if(r.ok)sAn(r.data);sLoading(false);}).catch(()=>sLoading(false));}
    else sLoading(false);
  },[]);
  const computeLocal=()=>{
    const now=new Date();const todayStart=new Date(now);todayStart.setHours(0,0,0,0);
    const weekStart=new Date(todayStart);weekStart.setDate(weekStart.getDate()-7);
    const monthStart=new Date(todayStart);monthStart.setDate(monthStart.getDate()-30);
    const countIn=(since)=>{const f=vs.filter(v=>new Date(v.date)>=since);return{total:f.length,approved:f.filter(v=>v.status==="approved").length,dismissed:f.filter(v=>v.status==="dismissed").length,pending:f.filter(v=>v.status==="pending").length};};
    const totalAll=vs.length||1;const typeMap={};vs.forEach(v=>{typeMap[v.type]=(typeMap[v.type]||0)+1;});
    const byType={};Object.entries(typeMap).forEach(([k,n])=>{byType[k]=Math.round((n/totalAll)*100);});
    const hourly=new Array(24).fill(0);vs.filter(v=>new Date(v.date)>=todayStart).forEach(v=>{hourly[new Date(v.date).getHours()]++;});
    return{today:countIn(todayStart),week:countIn(weekStart),month:countIn(monthStart),byType,hourly};
  };
  const data=an||computeLocal();
  if(loading)return <p style={{color:t.tD,padding:40,textAlign:"center"}}>Loading analytics...</p>;
  return(<div><h2 style={{fontSize:20*s,fontWeight:800,color:t.tx,margin:"0 0 20px"}}>Analytics</h2><div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:16,marginBottom:20}}>{[{l:"Today",...data.today},{l:"Week",...data.week},{l:"Month",...data.month}].map((p,i)=>(<Glass key={i} style={{padding:22}}><h3 style={{margin:"0 0 16px",fontSize:14*s,fontWeight:700,color:t.tx}}>{p.l}</h3><div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>{[{l:"Total",v:p.total,c:t.tx},{l:"Approved",v:p.approved,c:c.status.approved},{l:"Dismissed",v:p.dismissed,c:c.status.dismissed},{l:"Pending",v:p.pending,c:c.status.pending}].map((x,j)=>(<div key={j}><p style={{fontSize:9,color:t.tD,margin:"0 0 3px",textTransform:"uppercase",letterSpacing:1.5,fontWeight:600}}>{x.l}</p><p style={{fontSize:22*s,fontWeight:800,color:x.c,margin:0,fontFamily:"'JetBrains Mono',monospace"}}>{x.v}</p></div>))}</div></Glass>))}</div><div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16}}><Glass style={{padding:22}}><h3 style={{margin:"0 0 14px",fontSize:14*s,fontWeight:700,color:t.tx}}>Hourly</h3><MC data={data.hourly.some(v=>v>0)?data.hourly:[0,0,0,0,0,0,1,2,3,4,3,2,2,3,4,3,2,1,1,1,0,0,0,0]} height={100}/></Glass><Glass style={{padding:22}}><h3 style={{margin:"0 0 18px",fontSize:14*s,fontWeight:700,color:t.tx}}>Breakdown</h3>{Object.entries(data.byType).map(([ty,pc])=>(<div key={ty} style={{marginBottom:18}}><div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}><span style={{fontSize:13,color:t.tM}}>{ty}</span><span style={{fontSize:13,fontWeight:700,color:c.type[ty]||t.tM,fontFamily:"'JetBrains Mono',monospace"}}>{pc}%</span></div><div style={{height:7,borderRadius:10,background:"rgba(128,128,128,.12)",overflow:"hidden"}}><div style={{width:`${pc}%`,height:"100%",borderRadius:10,background:`linear-gradient(90deg,${(c.type[ty]||"#a78bfa")}88,${c.type[ty]||"#a78bfa"})`}}/></div></div>))}</Glass></div></div>);
}

/* ═══ SETTINGS (abbreviated) ═══ */
function Settings({settings:st,setSettings:sS,user:us,theme:th,setTheme:sTh,keybinds:kb,setKeybinds:sKb,appVersion:av}){
  const t=T[th];const[rb,sRb]=useState(null);const sRef=useRef(null);const[updChk,sUpdChk]=useState(null);
  const upd=fn=>{const el=sRef.current;const top=el?el.scrollTop:0;sS(fn);requestAnimationFrame(()=>{if(el)el.scrollTop=top;});};
  useEffect(()=>{if(!rb)return;const h=e=>{e.preventDefault();sKb(k=>({...k,[rb]:{...k[rb],key:e.key,ctrl:e.ctrlKey||e.metaKey}}));sRb(null);};window.addEventListener("keydown",h);return()=>window.removeEventListener("keydown",h);},[rb]);
  const S=({title:ti,children:ch})=>(<Glass style={{padding:22,marginBottom:14}}><h3 style={{margin:"0 0 16px",fontSize:15,fontWeight:700,color:t.tx,borderBottom:`1px solid ${t.dv}`,paddingBottom:10}}>{ti}</h3>{ch}</Glass>);
  const Tog=({label:l,value:v,onChange:oc})=>(<div style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"10px 0",borderBottom:`1px solid ${t.dv}`}}><p style={{margin:0,fontSize:13,fontWeight:600,color:t.tx}}>{l}</p><button onClick={()=>oc(!v)} style={{width:44,height:24,borderRadius:12,border:"none",cursor:"pointer",position:"relative",background:v?"linear-gradient(135deg,#6366f1,#8b5cf6)":"rgba(128,128,128,.2)"}}><div style={{width:18,height:18,borderRadius:9,background:"#fff",position:"absolute",top:3,left:v?23:3,transition:"left .3s"}}/></button></div>);
  const Row=({label:l,children:ch})=>(<div style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"10px 0",borderBottom:`1px solid ${t.dv}`}}><p style={{margin:0,fontSize:13,fontWeight:600,color:t.tx}}>{l}</p><div>{ch}</div></div>);
  const P=({label:l,active:a,onClick:oc})=>(<button onClick={oc} style={{padding:"5px 12px",borderRadius:7,border:`1px solid ${a?"rgba(167,139,250,.3)":t.iBo}`,background:a?"rgba(167,139,250,.15)":t.iB,color:a?"#a78bfa":t.tD,fontSize:11,fontWeight:600,cursor:"pointer"}}>{l}</button>);
  return(<div ref={sRef} style={{maxWidth:700,margin:"0 auto"}}><h2 style={{fontSize:20,fontWeight:800,color:t.tx,margin:"0 0 20px"}}>Settings</h2>
    <S title="Appearance"><Row label="Theme"><div style={{display:"flex",gap:4}}>{["dark","light"].map(m=>(<P key={m} label={m==="dark"?"☾ Dark":"☀ Light"} active={th===m} onClick={()=>sTh(m)}/>))}</div></Row><Row label="Font"><div style={{display:"flex",gap:4}}>{["small","medium","large"].map(x=>(<P key={x} label={x[0].toUpperCase()+x.slice(1)} active={(st.fontSize||"medium")===x} onClick={()=>upd(p=>({...p,fontSize:x}))}/>))}</div></Row><Tog label="Color blind" value={!!st.colorBlind} onChange={v=>upd(p=>({...p,colorBlind:v}))}/><Row label="Time"><div style={{display:"flex",gap:4}}>{["24h","12h"].map(f=>(<P key={f} label={f} active={(st.timeFormat||"24h")===f} onClick={()=>upd(p=>({...p,timeFormat:f}))}/>))}</div></Row></S>
    <S title="Queue"><Row label="Density"><div style={{display:"flex",gap:4}}>{["compact","comfortable"].map(d=>(<P key={d} label={d[0].toUpperCase()+d.slice(1)} active={(st.queueDensity||"comfortable")===d} onClick={()=>upd(p=>({...p,queueDensity:d}))}/>))}</div></Row><Tog label="Hover preview" value={st.hoverPreview!==false} onChange={v=>upd(p=>({...p,hoverPreview:v}))}/></S>
    <S title="Video"><Tog label="Auto-play" value={!!st.autoPlay} onChange={v=>upd(p=>({...p,autoPlay:v}))}/><Row label="Speed"><div style={{display:"flex",gap:4}}>{SPEEDS.map(x=>(<P key={x} label={x+"x"} active={(st.playbackSpeed||1)===x} onClick={()=>upd(p=>({...p,playbackSpeed:x}))}/>))}</div></Row><Row label="Auto-hide"><div style={{display:"flex",alignItems:"center"}}><input type="range" min="1" max="10" step="1" value={st.autoHideDelay||3} onChange={e=>upd(p=>({...p,autoHideDelay:parseInt(e.target.value)}))} style={{width:100,accentColor:"#a78bfa"}}/><span style={{fontSize:11,color:t.tM,fontFamily:"'JetBrains Mono',monospace",marginLeft:8}}>{st.autoHideDelay||3}s</span></div></Row></S>
    <S title="Review"><Tog label="Auto-advance" value={!!st.autoAdvance} onChange={v=>upd(p=>({...p,autoAdvance:v}))}/><Tog label="Confirm actions" value={!!st.confirmActions} onChange={v=>upd(p=>({...p,confirmActions:v}))}/><Row label="Nav placement"><Sel value={st.navPlacement||"bottom"} onChange={e=>upd(p=>({...p,navPlacement:e.target.value}))} options={NPL}/></Row><Row label="Sidebar"><div style={{display:"flex",gap:4}}>{["left","right"].map(x=>(<P key={x} label={x[0].toUpperCase()+x.slice(1)} active={(st.sidebarPos||"right")===x} onClick={()=>upd(p=>({...p,sidebarPos:x}))}/>))}</div></Row></S>
    <S title="Security"><Row label="Session timeout (min)"><div style={{display:"flex",alignItems:"center"}}><input type="range" min="5" max="120" step="5" value={st.sessionTimeout||30} onChange={e=>upd(p=>({...p,sessionTimeout:parseInt(e.target.value)}))} style={{width:100,accentColor:"#a78bfa"}}/><span style={{fontSize:11,color:t.tM,fontFamily:"'JetBrains Mono',monospace",marginLeft:8}}>{st.sessionTimeout||30}m</span></div></Row></S>
    <S title="Keybinds"><p style={{fontSize:11,color:t.tD,margin:"0 0 8px"}}>Click to rebind</p>{Object.entries(kb).map(([a,b])=>(<div key={a} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"6px 0",borderBottom:`1px solid ${t.dv}`}}><span style={{fontSize:12,color:t.tM}}>{b.desc}</span><button onClick={()=>sRb(a)} style={{padding:"3px 10px",borderRadius:6,border:`1px solid ${rb===a?"rgba(167,139,250,.5)":t.iBo}`,background:rb===a?"rgba(167,139,250,.2)":t.iB,color:rb===a?"#c4b5fd":t.tx,fontSize:11,fontWeight:700,cursor:"pointer",fontFamily:"'JetBrains Mono',monospace",minWidth:60,textAlign:"center",animation:rb===a?"pulse 1s infinite":"none"}}>{rb===a?"...":kl(b.key,b.ctrl)}</button></div>))}<button onClick={()=>sKb(DK)} style={{marginTop:8,padding:"6px 14px",borderRadius:8,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tM,fontSize:11,fontWeight:600,cursor:"pointer"}}>Reset</button></S>
    <S title="Updates"><Tog label="Check for updates automatically" value={st.autoUpdate!==false} onChange={v=>upd(p=>({...p,autoUpdate:v}))}/><Row label="Check for updates"><div style={{display:"flex",alignItems:"center",gap:8}}><button onClick={()=>{sUpdChk("checking");if(window.hopeUpdater)window.hopeUpdater.check().then(r=>{sUpdChk(r.ok&&r.version?"available":"up-to-date");}).catch(()=>sUpdChk("error"));else sUpdChk("error");}} style={{padding:"5px 14px",borderRadius:7,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tD,fontSize:11,fontWeight:600,cursor:"pointer"}}>Check Now</button>{updChk&&<span style={{fontSize:11,color:updChk==="available"?"#a78bfa":updChk==="up-to-date"?"#34d399":"#f87171",fontWeight:600}}>{updChk==="checking"?"Checking...":updChk==="available"?"Update available":updChk==="up-to-date"?"Up to date":"Check failed"}</span>}</div></Row><Row label="Current version"><span style={{fontSize:12,color:t.tM,fontFamily:"'JetBrains Mono',monospace"}}>{av||"1.0.0"}</span></Row></S>
    <S title="Account"><Row label="Username"><span style={{fontSize:13,color:t.tM,fontFamily:"'JetBrains Mono',monospace"}}>{us?.name}</span></Row><Row label="Role"><span style={{fontSize:12,color:"#a78bfa",fontWeight:600,textTransform:"capitalize"}}>{us?.role}</span></Row></S>
    <S title="About">{[{l:"App",v:"H.O.P.E."},{l:"Ver",v:av||"1.0.0"},{l:"By",v:"Sovalius Corporation"}].map((r,i)=>(<div key={i} style={{display:"flex",justifyContent:"space-between",padding:"4px 0"}}><span style={{fontSize:12,color:t.tD}}>{r.l}</span><span style={{fontSize:12,fontWeight:600,color:t.tM}}>{r.v}</span></div>))}</S>
  </div>);
}

/* ═══ CONFIGURE PAGE ═══ */
function Configure({user}){
  const t=T[useContext(ThC)];const s=sc(useContext(StC).fontSize);
  const[tab,sTab]=useState("cameras");
  const[editCam,sEditCam]=useState(null);
  const[feeds,sFeeds]=useState([]);
  const isEl=typeof window!=="undefined"&&window.hopeDb;
  useEffect(()=>{
    if(!isEl)return;
    const pull=()=>window.hopeDb.getSystemStatus().then(res=>{
      if(res.ok&&res.row){
        const stale=Date.now()-new Date(res.row.timestamp).getTime()>60000;
        const fd=(res.row.feed_details||[]).map(f=>({id:f.name,name:f.name,source:f.source,status:stale?"offline":f.is_active?"online":"offline",fps:f.fps,violations:f.violations_count,tracked:f.vehicles_tracked}));
        sFeeds(fd);
      }
    });
    pull();const i=setInterval(pull,10000);return()=>clearInterval(i);
  },[isEl]);
  const cams=feeds;
  const[requests,sRequests]=useState([
    {id:"SVT-2026-0042",reqType:"new_camera",location:"Dorsetshire Hill",justification:"School zone, frequent speeding reports from officers",priority:"high",by:"Sgt. Williams",submittedAt:"2026-03-18T10:00:00",
      stages:[{s:"submitted",at:"2026-03-18T10:00:00"},{s:"under_review",at:"2026-03-18T14:30:00"},{s:"site_survey",at:"2026-03-19T09:00:00",note:"Sovalius technician scheduled for site visit"}],currentStage:"site_survey"},
    {id:"SVT-2026-0038",reqType:"new_camera",location:"Murray Road, Cane Garden",justification:"Blind corner, multiple accident reports",priority:"medium",by:"Cpl. James",submittedAt:"2026-03-10T08:00:00",
      stages:[{s:"submitted",at:"2026-03-10T08:00:00"},{s:"under_review",at:"2026-03-10T16:00:00"},{s:"site_survey",at:"2026-03-12T10:00:00"},{s:"approved",at:"2026-03-14T11:00:00",note:"Approved — CAM-CG-01 allocated"},{s:"installation",at:"2026-03-17T08:00:00",note:"Installation in progress"}],currentStage:"installation"},
    {id:"SVT-2026-0045",reqType:"ext_stream",location:"Ministry of Finance, Kingstown",owner:"Government of SVG — CCTV Division",streamInfo:"rtsp://10.0.1.50:554/cam3 · 1080p · H.264, fixed angle, covers Halifax St intersection",justification:"Government already has CCTV covering Halifax St intersection — high violation area. Connecting this feed avoids installing a new camera.",priority:"medium",by:"Sgt. Williams",submittedAt:"2026-03-19T14:00:00",
      stages:[{s:"submitted",at:"2026-03-19T14:00:00"},{s:"under_review",at:"2026-03-20T09:00:00",note:"Sovalius confirming stream access with SVG IT department"}],currentStage:"under_review"},
  ]);
  const[showReq,sShowReq]=useState(false);
  const[confirmMsg,sConfirmMsg]=useState(null);
  const laneCams=cams.map(c=>({id:c.id,name:c.name||c.id}));

  // Edit camera modal
  const EditModal=()=>{
    const[loc,sLoc]=useState(editCam?.location||"");const[gLat,sGLat]=useState("13.15");const[gLng,sGLng]=useState("-61.22");
    return(<div style={{position:"fixed",inset:0,zIndex:9998,background:"rgba(0,0,0,.5)",display:"flex",alignItems:"center",justifyContent:"center"}} onClick={()=>sEditCam(null)}>
      <div onClick={e=>e.stopPropagation()} style={{background:t.fD,border:`1px solid ${t.fDB}`,borderRadius:16,padding:"24px 28px",width:420}}>
        <h3 style={{margin:"0 0 18px",fontSize:16,fontWeight:800,color:t.tx}}>Edit Camera — {editCam?.id}</h3>
        <div style={{display:"flex",flexDirection:"column",gap:14}}>
          <div><label style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,display:"block",marginBottom:6,fontWeight:600}}>Location</label><input value={loc} onChange={e=>sLoc(e.target.value)} style={{width:"100%",padding:"10px 12px",borderRadius:10,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tx,fontSize:13,outline:"none",boxSizing:"border-box"}}/></div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
            <div><label style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,display:"block",marginBottom:6,fontWeight:600}}>Latitude</label><input value={gLat} onChange={e=>sGLat(e.target.value)} style={{width:"100%",padding:"10px 12px",borderRadius:10,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tx,fontSize:13,outline:"none",boxSizing:"border-box",fontFamily:"'JetBrains Mono',monospace"}}/></div>
            <div><label style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,display:"block",marginBottom:6,fontWeight:600}}>Longitude</label><input value={gLng} onChange={e=>sGLng(e.target.value)} style={{width:"100%",padding:"10px 12px",borderRadius:10,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tx,fontSize:13,outline:"none",boxSizing:"border-box",fontFamily:"'JetBrains Mono',monospace"}}/></div>
          </div>
        </div>
        <div style={{display:"flex",gap:10,marginTop:20,justifyContent:"flex-end"}}>
          <button onClick={()=>sEditCam(null)} style={{padding:"9px 20px",borderRadius:10,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tM,fontSize:13,fontWeight:600,cursor:"pointer"}}>Cancel</button>
          <button onClick={()=>{sFeeds(p=>p.map(c=>c.id===editCam.id?{...c,location:loc}:c));sEditCam(null);}} style={{padding:"9px 20px",borderRadius:10,border:"none",background:"linear-gradient(135deg,#6366f1,#8b5cf6)",color:"#fff",fontSize:13,fontWeight:700,cursor:"pointer"}}>Save</button>
        </div>
      </div>
    </div>);
  };

  // Request modal — dual type: new camera or external stream
  const ReqModal=()=>{
    const[rType,sRType]=useState("new_camera");
    const[loc,sLoc]=useState("");const[just,sJust]=useState("");const[pri,sPri]=useState("medium");const[area,sArea]=useState("");
    // External stream fields
    const[owner,sOwner]=useState("");const[streamInfo,sStreamInfo]=useState("");const[streamUrl,sStreamUrl]=useState("");const[resolution,sResolution]=useState("1080p");
    const isNew=rType==="new_camera";
    const canSubmit=isNew?(loc.trim()&&just.trim()):( loc.trim()&&owner.trim()&&just.trim());
    const submit=()=>{if(!canSubmit)return;const ticketId=`SVT-2026-${String(Math.floor(Math.random()*9000)+1000)}`;const base={id:ticketId,reqType:rType,location:`${loc}${area?", "+area:""}`,justification:just,priority:pri,by:user?.name||"Officer",submittedAt:new Date().toISOString(),stages:[{s:"submitted",at:new Date().toISOString()}],currentStage:"submitted"};if(!isNew){base.owner=owner;base.streamInfo=`${streamUrl?streamUrl+" · ":""}${resolution}${streamInfo?" · "+streamInfo:""}`;} sRequests(p=>[base,...p]);sShowReq(false);sConfirmMsg(ticketId);setTimeout(()=>sConfirmMsg(null),5000);};
    const inp=(l,v,sv,ph,extra={})=>(<div {...extra}><label style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,display:"block",marginBottom:6,fontWeight:600}}>{l}</label><input value={v} onChange={e=>sv(e.target.value)} placeholder={ph} style={{width:"100%",padding:"10px 12px",borderRadius:10,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tx,fontSize:13,outline:"none",boxSizing:"border-box"}}/></div>);
    return(<div style={{position:"fixed",inset:0,zIndex:9998,background:"rgba(0,0,0,.5)",display:"flex",alignItems:"center",justifyContent:"center"}} onClick={()=>sShowReq(false)}>
      <div onClick={e=>e.stopPropagation()} style={{background:t.fD,border:`1px solid ${t.fDB}`,borderRadius:16,padding:"24px 28px",width:480,maxHeight:"85vh",overflowY:"auto"}}>
        <h3 style={{margin:"0 0 4px",fontSize:16,fontWeight:800,color:t.tx}}>Camera Request</h3>
        <p style={{margin:"0 0 16px",fontSize:11,color:t.tD}}>Submit to Sovalius Corporation for processing</p>
        {/* Type selector */}
        <div style={{display:"flex",gap:6,marginBottom:18}}>
          {[{k:"new_camera",l:"New H.O.P.E. Camera",d:"Request Sovalius to install a new camera"},{k:"ext_stream",l:"Add Existing Stream",d:"Connect a government or third-party CCTV feed"}].map(x=>(<button key={x.k} onClick={()=>sRType(x.k)} style={{flex:1,padding:"12px 14px",borderRadius:12,border:`1px solid ${rType===x.k?"rgba(167,139,250,.4)":t.iBo}`,background:rType===x.k?"rgba(167,139,250,.1)":t.iB,cursor:"pointer",textAlign:"left"}}>
            <p style={{margin:0,fontSize:12,fontWeight:700,color:rType===x.k?"#a78bfa":t.tx}}>{x.l}</p>
            <p style={{margin:"3px 0 0",fontSize:10,color:t.tD}}>{x.d}</p>
          </button>))}
        </div>
        <div style={{display:"flex",flexDirection:"column",gap:14}}>
          {inp("Location",loc,sLoc,isNew?"e.g. Dorsetshire Hill, near school":"e.g. Ministry of Finance, Halifax St — existing camera location")}
          {inp("Area / Parish",area,sArea,"e.g. Kingstown, St. George")}
          {/* Existing stream specific fields */}
          {!isNew&&<>
            {inp("Stream Owner",owner,sOwner,"e.g. Government of SVG, Port Authority, GraceKennedy")}
            {inp("Stream URL / Access Details",streamUrl,sStreamUrl,"e.g. rtsp://10.0.1.50:554/cam3 or contact details for IT dept")}
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
              <div><label style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,display:"block",marginBottom:6,fontWeight:600}}>Resolution</label><div style={{display:"flex",gap:4}}>{["720p","1080p","4K"].map(r=>(<button key={r} onClick={()=>sResolution(r)} style={{padding:"5px 12px",borderRadius:7,border:`1px solid ${resolution===r?"rgba(167,139,250,.3)":t.iBo}`,background:resolution===r?"rgba(167,139,250,.15)":t.iB,color:resolution===r?"#a78bfa":t.tD,fontSize:11,fontWeight:600,cursor:"pointer"}}>{r}</button>))}</div></div>
              {inp("Stream Details",streamInfo,sStreamInfo,"e.g. H.264 codec, fixed angle, covers intersection")}
            </div>
          </>}
          <div><label style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,display:"block",marginBottom:6,fontWeight:600}}>Justification</label><textarea value={just} onChange={e=>sJust(e.target.value)} rows={3} placeholder={isNew?"Why is this camera needed? (incident history, safety concerns)":"Why should this stream be connected to H.O.P.E.? (coverage area, known violation hotspot)"} style={{width:"100%",padding:"10px 12px",borderRadius:10,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tx,fontSize:13,outline:"none",boxSizing:"border-box",resize:"vertical",fontFamily:"'Inter',sans-serif"}}/></div>
          <div><label style={{fontSize:10,color:t.tD,textTransform:"uppercase",letterSpacing:1.5,display:"block",marginBottom:6,fontWeight:600}}>Priority</label><div style={{display:"flex",gap:6}}>{["low","medium","high","critical"].map(p=>(<button key={p} onClick={()=>sPri(p)} style={{padding:"6px 14px",borderRadius:8,border:`1px solid ${pri===p?"rgba(167,139,250,.3)":t.iBo}`,background:pri===p?"rgba(167,139,250,.15)":t.iB,color:pri===p?"#a78bfa":t.tD,fontSize:11,fontWeight:600,cursor:"pointer",textTransform:"capitalize"}}>{p}</button>))}</div></div>
        </div>
        <div style={{display:"flex",gap:10,marginTop:20,justifyContent:"flex-end"}}>
          <button onClick={()=>sShowReq(false)} style={{padding:"9px 20px",borderRadius:10,border:`1px solid ${t.iBo}`,background:t.iB,color:t.tM,fontSize:13,fontWeight:600,cursor:"pointer"}}>Cancel</button>
          <button onClick={submit} disabled={!canSubmit} style={{padding:"9px 20px",borderRadius:10,border:"none",background:canSubmit?"linear-gradient(135deg,#6366f1,#8b5cf6)":"rgba(128,128,128,.2)",color:canSubmit?"#fff":"rgba(255,255,255,.3)",fontSize:13,fontWeight:700,cursor:canSubmit?"pointer":"not-allowed"}}>Submit to Sovalius</button>
        </div>
      </div>
    </div>);
  };

  const priC={low:"#60a5fa",medium:"#f59e0b",high:"#f87171",critical:"#ef4444"};
  const newCamStages=["submitted","under_review","site_survey","approved","denied","installation","live"];
  const extStreamStages=["submitted","under_review","compatibility","approved","denied","integration","live"];
  const stageLabels={submitted:"Submitted",under_review:"Under Review",site_survey:"Site Survey",compatibility:"Stream Check",approved:"Approved",denied:"Denied",installation:"Installation",integration:"Integration",live:"Live"};
  const stageColors={submitted:"#a78bfa",under_review:"#60a5fa",site_survey:"#f59e0b",compatibility:"#f59e0b",approved:"#34d399",denied:"#f87171",installation:"#818cf8",integration:"#818cf8",live:"#34d399"};
  const reqTypeLabels={new_camera:"New Camera",ext_stream:"Existing Stream"};
  const reqTypeColors={new_camera:"#a78bfa",ext_stream:"#60a5fa"};

  return(<div>
    {editCam&&<EditModal/>}{showReq&&<ReqModal/>}
    {/* Confirmation toast */}
    {confirmMsg&&<div style={{position:"fixed",top:70,left:"50%",transform:"translateX(-50%)",zIndex:9999,padding:"12px 24px",borderRadius:12,background:"rgba(52,211,153,.15)",border:"1px solid rgba(52,211,153,.3)",color:"#34d399",fontSize:13,fontWeight:700,display:"flex",alignItems:"center",gap:10,boxShadow:"0 8px 30px rgba(0,0,0,.3)"}}><span style={{fontSize:16}}>✓</span> Request {confirmMsg} submitted to Sovalius Corporation</div>}
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:20}}>
      <h2 style={{fontSize:20*s,fontWeight:800,color:t.tx,margin:0}}>Configure</h2>
      <div style={{display:"flex",gap:4}}>{[{k:"cameras",l:"Camera Management"},{k:"lanes",l:"Lane Drawing"}].map(x=>(<button key={x.k} onClick={()=>sTab(x.k)} style={{padding:"8px 18px",borderRadius:10,border:"none",cursor:"pointer",fontSize:12,fontWeight:600,background:tab===x.k?"rgba(167,139,250,.15)":"transparent",color:tab===x.k?"#a78bfa":t.tD}}>{x.l}</button>))}</div>
    </div>

    {tab==="cameras"&&<div>
      <Glass style={{overflow:"hidden",marginBottom:16}}>
        <div style={{padding:"14px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <h3 style={{margin:0,fontSize:14*s,fontWeight:700,color:t.tx}}>Feeds ({cams.length})</h3>
          <button onClick={()=>sShowReq(true)} style={{padding:"7px 16px",borderRadius:8,border:"none",background:"linear-gradient(135deg,#6366f1,#8b5cf6)",color:"#fff",fontSize:12,fontWeight:700,cursor:"pointer"}}>+ Request Camera</button>
        </div>
        {cams.length===0?<div style={{padding:"40px 20px",textAlign:"center"}}><p style={{fontSize:13,color:t.tD,margin:0}}>No feeds registered</p><p style={{fontSize:11,color:t.tF,margin:"4px 0 0"}}>Feeds will appear when H.O.P.E. is running</p></div>:cams.map(c=>{
          const statC={online:"#34d399",offline:"#f87171",degraded:"#f59e0b"};
          return(<div key={c.id} style={{padding:"12px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",alignItems:"center",gap:14}}>
            <div style={{width:8,height:8,borderRadius:4,background:statC[c.status],flexShrink:0}}/>
            <div style={{flex:1,minWidth:0}}>
              <div style={{display:"flex",alignItems:"center",gap:8}}>
                <span style={{fontSize:13*s,fontWeight:700,color:t.tx,fontFamily:"'JetBrains Mono',monospace"}}>{c.name}</span>
                <span style={{fontSize:10,fontWeight:700,color:statC[c.status],textTransform:"uppercase"}}>{c.status}</span>
                <span style={{fontSize:10,color:t.tM,fontFamily:"'JetBrains Mono',monospace"}}>{c.fps} FPS</span>
              </div>
              <span style={{fontSize:10,color:t.tD,wordBreak:"break-all"}}>{c.source}</span>
            </div>
            <div style={{textAlign:"right",flexShrink:0,fontSize:10,color:t.tF}}>
              <p style={{margin:0}}>{c.violations} violations</p>
              <p style={{margin:"1px 0 0"}}>{c.tracked} tracked</p>
            </div>
          </div>);
        })}
      </Glass>

      {/* Sovalius Request Tracker */}
      <Glass style={{overflow:"hidden"}}>
        <div style={{padding:"14px 18px",borderBottom:`1px solid ${t.dv}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <div>
            <h3 style={{margin:0,fontSize:14*s,fontWeight:700,color:t.tx}}>Sovalius Camera Requests</h3>
            <p style={{margin:"2px 0 0",fontSize:10,color:t.tD}}>Requests are processed by Sovalius Corporation</p>
          </div>
          <span style={{fontSize:11,color:t.tF,fontFamily:"'JetBrains Mono',monospace"}}>{requests.length} request{requests.length!==1?"s":""}</span>
        </div>
        {requests.length===0&&<p style={{padding:20,textAlign:"center",color:t.tF,fontSize:13}}>No requests submitted</p>}
        {requests.map(r=>{
          const stageOrder=r.reqType==="ext_stream"?extStreamStages:newCamStages;
          const activeIdx=stageOrder.indexOf(r.currentStage);
          const isDenied=r.currentStage==="denied";
          const pipeline=isDenied?stageOrder.slice(0,4).concat(["denied"]):stageOrder.filter(s=>s!=="denied");
          return(<div key={r.id} style={{padding:"16px 18px",borderBottom:`1px solid ${t.dv}`}}>
            {/* Header */}
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
              <div style={{display:"flex",alignItems:"center",gap:10}}>
                <span style={{fontSize:13,fontWeight:700,color:"#a78bfa",fontFamily:"'JetBrains Mono',monospace"}}>{r.id}</span>
                <span style={{fontSize:9,padding:"2px 8px",borderRadius:5,fontWeight:700,background:`${reqTypeColors[r.reqType]}15`,color:reqTypeColors[r.reqType],textTransform:"uppercase",border:`1px solid ${reqTypeColors[r.reqType]}25`}}>{reqTypeLabels[r.reqType]}</span>
                <span style={{fontSize:9,padding:"2px 8px",borderRadius:5,fontWeight:700,background:`${priC[r.priority]}15`,color:priC[r.priority],textTransform:"uppercase"}}>{r.priority}</span>
              </div>
              <span style={{fontSize:10,color:t.tF}}>by {r.by} · {tS(r.submittedAt)}</span>
            </div>
            {/* Location + justification */}
            <p style={{margin:"0 0 4px",fontSize:13,fontWeight:600,color:t.tx}}>{r.location}</p>
            {r.owner&&<p style={{margin:"0 0 4px",fontSize:11,color:t.tM}}>Owner: {r.owner}{r.streamInfo&&<span style={{color:t.tD,marginLeft:8,fontFamily:"'JetBrains Mono',monospace",fontSize:10}}>{r.streamInfo}</span>}</p>}
            <p style={{margin:"0 0 14px",fontSize:11,color:t.tD,lineHeight:1.5}}>{r.justification}</p>
            {/* Pipeline stages */}
            <div style={{display:"flex",alignItems:"center",gap:0,marginBottom:8}}>
              {pipeline.map((stage,i)=>{
                const reached=stageOrder.indexOf(stage)<=activeIdx;
                const isCurrent=stage===r.currentStage;
                return(<div key={stage} style={{display:"flex",alignItems:"center",flex:i<pipeline.length-1?1:"none"}}>
                  <div style={{display:"flex",flexDirection:"column",alignItems:"center",position:"relative"}}>
                    <div style={{width:isCurrent?24:16,height:isCurrent?24:16,borderRadius:12,background:reached?stageColors[stage]:"transparent",border:`2px solid ${reached?stageColors[stage]:t.iBo}`,display:"flex",alignItems:"center",justifyContent:"center",transition:"all .3s"}}>
                      {reached&&<span style={{color:"#fff",fontSize:isCurrent?10:7,fontWeight:800}}>{stage==="approved"||stage==="live"?"✓":stage==="denied"?"✕":"•"}</span>}
                    </div>
                    <span style={{fontSize:8,color:isCurrent?stageColors[stage]:reached?t.tM:t.tF,fontWeight:isCurrent?700:500,marginTop:4,whiteSpace:"nowrap",textTransform:"uppercase",letterSpacing:.5}}>{stageLabels[stage]}</span>
                  </div>
                  {i<pipeline.length-1&&<div style={{flex:1,height:2,background:reached&&stageOrder.indexOf(pipeline[i+1])<=activeIdx?stageColors[stage]:t.iBo,margin:"0 4px 16px",borderRadius:1,minWidth:12}}/>}
                </div>);
              })}
            </div>
            {/* Stage notes */}
            {r.stages.filter(st=>st.note).length>0&&<div style={{marginTop:8,paddingTop:8,borderTop:`1px solid ${t.dv}`}}>
              {r.stages.filter(st=>st.note).map((st,i)=>(<div key={i} style={{display:"flex",gap:8,alignItems:"baseline",marginBottom:4}}>
                <span style={{fontSize:9,color:stageColors[st.s],fontWeight:700,textTransform:"uppercase",flexShrink:0}}>{stageLabels[st.s]}</span>
                <span style={{fontSize:11,color:t.tM,fontStyle:"italic"}}>{st.note}</span>
                <span style={{fontSize:9,color:t.tF,marginLeft:"auto",flexShrink:0}}>{fT(st.at,"24h")}</span>
              </div>))}
            </div>}
          </div>);
        })}
      </Glass>
    </div>}

    {tab==="lanes"&&<LaneConfigTab cameras={laneCams} theme={t}/>}
  </div>);
}

/* ═══ APP ═══ */
export default function App(){
  const[booted,setBooted]=useState(false);
  const[th,sTh]=useState("dark"),[user,sUser]=useState(null),[page,sPage]=useState("dashboard");
  const[sel,sSel]=useState(null),[fl,sFl]=useState("all");
  const[st,sSt]=useState(DS),[kb,sKb]=useState(DK),[cs,sCs]=useState(false),[revId,sRevId]=useState(null);
  const[notifs,sNotifs]=useState(NOTIFS_INIT),[showNotifs,sShowNotifs]=useState(false);
  const[updInfo,sUpdInfo]=useState(null);
  const[updDismissed,sUpdDismissed]=useState(false);
  const[skippedVer,setSkippedVer]=useState(()=>localStorage.getItem("hope_skipped_ver")||"");
  const[appVer,sAppVer]=useState("1.0.0");
  const isEl=typeof window!=="undefined"&&window.hopeDb;

  useEffect(()=>{
    if(typeof window==="undefined"||!window.hopeUpdater)return;
    window.hopeUpdater.onStatus(d=>{sUpdInfo(prev=>({...prev,...d}));});
    window.hopeUpdater.getVersion().then(v=>{if(v)sAppVer(v);}).catch(()=>{});
  },[]);
  const prefsSaveEnabled=useRef(false);
  const handleLogin=useCallback(u=>{
    sUser(u);
    if(u.theme)sTh(u.theme);
    if(u.preferences&&Object.keys(u.preferences).length>0)sSt(prev=>({...prev,...u.preferences}));
    if(u.keybinds&&Object.keys(u.keybinds).length>0)sKb(prev=>({...prev,...u.keybinds}));
    setTimeout(()=>{prefsSaveEnabled.current=true;},1200);
  },[]);
  useEffect(()=>{
    if(!user?.id||!isEl||!window.hopePrefs||!prefsSaveEnabled.current)return;
    const t=setTimeout(()=>{window.hopePrefs.save(user.id,st,kb,th);},800);
    return()=>clearTimeout(t);
  },[st,kb,th,user?.id]);
  useEffect(()=>{if(isEl){window.hopeDb.getNotifications().then(r=>{if(r.ok&&r.rows.length>0)sNotifs(r.rows.map(n=>({id:n.id,type:n.type,msg:n.msg,at:n.at,read:n.read})));});}},[]);
  const markRead=id=>{sNotifs(p=>p.map(n=>n.id===id?{...n,read:true}:n));if(isEl)window.hopeDb.markNotificationRead(id);};
  const markAllRead=()=>{sNotifs(p=>p.map(n=>({...n,read:true})));if(isEl)window.hopeDb.markAllNotificationsRead();};

  const db=useDbData([],[],[]);
  const vs=db.violations,sVs=db.setViolations;
  const auditLog=db.auditLog,sAuditLog=db.setAuditLog;

  const t=T[th];const colors=st.colorBlind?CSC.cb:CSC.default;

  // ---- sign-out actually ENDS the session -----------------------------------
  // The old handler only repainted the renderer back to the login page: the
  // main-process tokens stayed live, the loaded cases stayed in memory and the
  // 15s poller kept running, so the next person at the desk inherited the
  // previous reviewer's data and authority. Now: revoke server-side, drop the
  // tokens, clear every case/audit/notification, and stop polling.
  const signOut=useCallback(async()=>{
    prefsSaveEnabled.current=false;
    try{if(isEl&&window.hopeAuth&&window.hopeAuth.logout)await window.hopeAuth.logout();}catch{/* tokens are dropped regardless */}
    db.reset();
    sNotifs([]);sShowNotifs(false);sSel(null);sRevId(null);sPage("dashboard");sCs(false);
    sUser(null);
  },[isEl,db]);

  const timeout=useSessionTimeout(user?st.sessionTimeout||30:0,signOut);
  const unreadCount=notifs.filter(n=>!n.read).length;

  // ---- decisions: THE SERVER IS AUTHORITATIVE -------------------------------
  // Nothing about a case changes on screen until the gateway has confirmed the
  // write. A privilege failure, an enforcement-gate refusal, a validation
  // error or a dropped connection must all read as a FAILED decision — the
  // screen may never show "approved" for something the gateway rejected.
  // The returned {ok,error} is what the decision panel renders.
  const applyServerRow=(id,row)=>{
    if(!row)return;
    sVs(p=>p.map(v=>v.id===id?{...v,
      status:row.status||"pending",
      notes:row.notes??v.notes,
      pinned:row.pinned??v.pinned,
      reviewedBy:row.reviewed_by??null,
      reviewedAt:row.reviewed_at??null,
      history:row.history||v.history||[],
    }:v));
  };
  const act=async(id,s,n)=>{
    const res=await db.persistAction(id,s,n);
    if(!res||!res.ok)return res||{ok:false,error:"The decision could not be recorded"};
    applyServerRow(id,res.row);
    sRevId(null);
    // Re-pull the tamper-evident audit chain the SERVER wrote (the client
    // never invents audit rows).
    db.refreshAll();
    return{ok:true};
  };
  const pin=async id=>{
    const cur=vs.find(v=>v.id===id);
    const res=await db.persistPin(id,!cur?.pinned);
    if(!res||!res.ok)return res||{ok:false,error:"Pin could not be saved"};
    applyServerRow(id,res.row);
    return{ok:true};
  };
  const undo=async id=>{
    const res=await db.persistAction(id,"pending","Decision undone");
    if(!res||!res.ok)return res||{ok:false,error:"The decision could not be reopened"};
    applyServerRow(id,res.row);
    db.refreshAll();
    return{ok:true};
  };
  const revise=id=>{const v=vs.find(x=>x.id===id);if(v){sSel(v);sRevId(id);}};

  useKB(kb,{cheatSheet:()=>sCs(x=>!x)});

  if(!booted)return <SplashScreen onDone={()=>setBooted(true)}/>;

  const updateReady=updInfo&&updInfo.status==="ready"&&!updDismissed;

  if(!user)return(<><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap" rel="stylesheet"/><style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}`}</style><Login onLogin={handleLogin}/></>);

  const navItems=[{id:"dashboard",l:"Dashboard",i:"◫"},{id:"analytics",l:"Analytics",i:"◎"},{id:"system",l:"System Status",i:"◉"},{id:"audit",l:"Audit Log",i:"◈"},{id:"configure",l:"Configure",i:"⬡"}];

  return(
    <ThC.Provider value={th}><StC.Provider value={st}><KbC.Provider value={kb}><CC.Provider value={colors}>
      <div style={{minHeight:"100vh",background:t.bgG,color:t.tx,fontFamily:"'Inter',sans-serif"}}>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
        <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}} ::-webkit-scrollbar{width:5px} ::-webkit-scrollbar-track{background:transparent} ::-webkit-scrollbar-thumb{background:rgba(128,128,128,.2);border-radius:10px} *{box-sizing:border-box} select option{background:${t.selBg};color:${t.selC}}`}</style>
        {cs&&<CS2 onClose={()=>sCs(false)} keybinds={kb}/>}
        {timeout.warn&&<TimeoutWarning left={timeout.left} onDismiss={timeout.dismiss}/>}

        {/* NAV */}
        <div style={{height:56,display:"flex",alignItems:"center",justifyContent:"space-between",padding:"0 28px",borderBottom:`1px solid ${t.dv}`,background:t.nB,position:"sticky",top:0,zIndex:100}}>
          <div style={{display:"flex",alignItems:"center",gap:16}}>
            <SovMark size={20} color={t.tx}/>
            <span style={{fontSize:17,fontWeight:800,letterSpacing:3,color:t.tx}}>H.O.P.E.</span>
            <div style={{display:"flex",gap:3,marginLeft:16}}>{navItems.map(n=>(<button key={n.id} onClick={()=>{sPage(n.id);sSel(null);sRevId(null);}} style={{padding:"7px 14px",borderRadius:10,border:"none",cursor:"pointer",fontSize:12,fontWeight:600,fontFamily:"'Inter',sans-serif",background:page===n.id?"rgba(167,139,250,.15)":"transparent",color:page===n.id?"#a78bfa":t.tD}}>{n.i} {n.l}</button>))}</div>
          </div>
          <div style={{display:"flex",alignItems:"center",gap:12,position:"relative"}}>
            {/* Notifications bell */}
            <button onClick={()=>sShowNotifs(x=>!x)} style={{background:t.iB,border:`1px solid ${t.iBo}`,borderRadius:10,padding:"6px 10px",cursor:"pointer",color:t.tD,fontSize:14,position:"relative"}}>
              🔔{unreadCount>0&&<span style={{position:"absolute",top:-4,right:-4,width:16,height:16,borderRadius:8,background:"#ef4444",color:"#fff",fontSize:9,fontWeight:700,display:"flex",alignItems:"center",justifyContent:"center"}}>{unreadCount}</span>}
            </button>
            {showNotifs&&<NotifPanel notifs={notifs} onClose={()=>sShowNotifs(false)} onRead={markRead} onMarkAllRead={markAllRead}/>}
            <button onClick={()=>sCs(x=>!x)} style={{background:t.iB,border:`1px solid ${t.iBo}`,borderRadius:10,padding:"6px 10px",cursor:"pointer",color:t.tD,fontSize:12}}>⌨</button>
            <button onClick={()=>{sPage("settings");sSel(null);}} style={{background:page==="settings"?"rgba(167,139,250,.15)":t.iB,border:`1px solid ${page==="settings"?"rgba(167,139,250,.3)":t.iBo}`,borderRadius:10,padding:"6px 12px",cursor:"pointer",color:page==="settings"?"#a78bfa":t.tD,fontSize:14}}>⚙</button>
            <div style={{display:"flex",alignItems:"center",gap:10}}><div style={{width:32,height:32,borderRadius:10,background:"linear-gradient(135deg,#6366f1,#8b5cf6)",display:"flex",alignItems:"center",justifyContent:"center",fontSize:13,fontWeight:700,color:"#fff"}}>{user.name[0]?.toUpperCase()}</div><div><p style={{fontSize:12,fontWeight:600,margin:0,color:t.tx}}>{user.name}</p><p style={{fontSize:10,margin:0,color:"#a78bfa",fontWeight:500,textTransform:"capitalize"}}>{user.role}</p></div></div>
            <button onClick={signOut} style={{background:t.iB,border:`1px solid ${t.iBo}`,borderRadius:8,padding:"5px 12px",cursor:"pointer",color:t.tD,fontSize:11,fontWeight:600}}>Sign Out</button>
          </div>
        </div>

        <div style={{padding:"22px 28px",maxWidth:1300,margin:"0 auto"}}>
          {page==="dashboard"&&!sel&&<Dash violations={vs} onSelect={v=>{sSel(v);sRevId(null);}} analytics={AN} onPin={pin} onUndo={undo} onRevise={revise}/>}
          {page==="dashboard"&&sel&&<VR violation={vs.find(v=>v.id===sel.id)||sel} violations={vs} onBack={()=>{sSel(null);sRevId(null);}} onAction={act} onNav={v=>{sSel(v);sRevId(null);}} filter={fl} setFilter={sFl} user={user} onPin={pin} onUndo={undo} revising={revId===sel?.id}/>}
          {page==="analytics"&&<Analytics violations={vs}/>}
          {page==="system"&&<SystemStatus/>}
          {page==="audit"&&<AuditLog auditLog={auditLog}/>}
          {page==="configure"&&<Configure user={user}/>}
          {page==="settings"&&<Settings settings={st} setSettings={sSt} user={user} theme={th} setTheme={sTh} keybinds={kb} setKeybinds={sKb} appVersion={appVer}/>}
        </div>
        <div style={{textAlign:"center",padding:"18px 0",borderTop:`1px solid ${t.dv}`,fontSize:10,color:t.tF,letterSpacing:2,marginTop:24,display:"flex",justifyContent:"center",alignItems:"center",gap:12}}>
          <span>SOVALIUS CORPORATION · H.O.P.E. v{appVer} · PER ASPERA AD ASTRA</span>
          <span style={{display:"inline-flex",alignItems:"center",gap:4}}><span style={{width:6,height:6,borderRadius:3,background:db.dbConnected?"#34d399":db.dbError?"#f87171":"#f59e0b"}}/>
          <span style={{fontSize:9}}>{db.dbConnected?"Gateway connected":db.dbError?`Gateway offline — ${db.dbError}`:"Connecting…"}</span></span>
        </div>
        {updateReady&&<div style={{position:"fixed",bottom:0,left:0,right:0,zIndex:9999,background:"linear-gradient(135deg,rgba(99,102,241,.95),rgba(139,92,246,.95))",backdropFilter:"blur(12px)",padding:"10px 28px",display:"flex",alignItems:"center",justifyContent:"center",gap:16,borderTop:"1px solid rgba(255,255,255,.1)"}}>
          <span style={{fontSize:12,fontWeight:600,color:"#fff"}}>Update v{updInfo.version} downloaded — will install on restart</span>
          <button onClick={()=>window.hopeUpdater?.install()} style={{padding:"5px 14px",borderRadius:7,border:"1px solid rgba(255,255,255,.3)",background:"rgba(255,255,255,.15)",color:"#fff",fontSize:11,fontWeight:600,cursor:"pointer"}}>Restart Now</button>
          <button onClick={()=>sUpdDismissed(true)} style={{background:"none",border:"none",color:"rgba(255,255,255,.6)",fontSize:14,cursor:"pointer",padding:"2px 6px"}}>✕</button>
        </div>}
      </div>
    </CC.Provider></KbC.Provider></StC.Provider></ThC.Provider>
  );
}
