"use client";

import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Html } from "@react-three/drei";
import { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import * as THREE from "three";
import type { ProjectionPoint, Cluster, VizEdge } from "@/lib/types";
import type { InputDevice } from "@/hooks/useInputDevice";
import {
  buildPositionBuffer,
  buildColorBuffer,
  buildEdgeBufferFromPositions,
  buildEdgeColorBuffer,
  buildPointIndex,
  buildSizeBuffer,
  computeNetworkMetrics,
  computeDataBounds,
  pointAtIndex,
} from "@/lib/vizTransforms";
import { VizTooltip } from "./VizTooltip";
import { VizNodeCard } from "./VizNodeCard";
import type { ThreeEvent } from "@react-three/fiber";
import type { RaycasterParameters } from "three";

const VERTEX_SHADER = `
  attribute float size;
  uniform float uReveal;
  uniform float uTime;
  uniform vec3 uCentroid;
  uniform float uDataRadius;
  varying vec3 vColor;
  varying float vVisible;
  void main() {
    vColor = color;
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);

    // Radial reveal from data centroid
    float dist = length(position.xyz - uCentroid) / uDataRadius;
    vVisible = smoothstep(dist - 0.05, dist + 0.05, uReveal);

    // Base size with breathing
    float breath = 1.0 + sin(uTime * 0.8 + position.x * 0.5) * 0.06;
    gl_PointSize = size * (300.0 / length(mvPosition.xyz)) * vVisible * breath;
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const FRAGMENT_SHADER = `
  varying vec3 vColor;
  varying float vVisible;
  void main() {
    if (vVisible < 0.01) discard;
    float dist = length(gl_PointCoord - vec2(0.5));
    if (dist > 0.5) discard;
    float edge = 1.0 - smoothstep(0.45, 0.5, dist);
    gl_FragColor = vec4(vColor, edge);
  }
`;

// Spring physics constants
const SPRING_TENSION = 0.15;
const SPRING_FRICTION = 0.75;

interface SpringState {
  vx: number;
  vy: number;
  vz: number;
  tx: number;
  ty: number;
  tz: number;
}

interface DragState {
  active: boolean;
  nodeIndex: number;
  plane: THREE.Plane;
  offset: THREE.Vector3;
  shiftKey: boolean;
  originalPos: THREE.Vector3;
}

interface VizSceneProps {
  points: ProjectionPoint[];
  clusters: Cluster[];
  edges: VizEdge[];
  focusedNode: ProjectionPoint | null;
  onFocusNode: (node: ProjectionPoint | null) => void;
  onNavigateNode: (engramId: string) => void;
  autoOrbit: boolean;
  onAutoOrbitStop: () => void;
  explodeFactor: number;
  onSpreadChange: (factor: number) => void;
  device: InputDevice;
}

function getClusterLabel(node: ProjectionPoint | null, clusterMap: Map<number, string | null>): string | null {
  if (!node || node.cluster_id == null) return null;
  const label = clusterMap.get(node.cluster_id);
  return label ?? `Cluster ${node.cluster_id}`;
}

/** One-shot camera animation to a target position. Animates once then releases. */
function CameraController({ target }: { target: THREE.Vector3 | null }) {
  const animatingTo = useRef<THREE.Vector3 | null>(null);
  const cameraGoal = useRef(new THREE.Vector3());
  const lastTargetId = useRef<string | null>(null);

  useFrame(({ camera }) => {
    // Detect new target (compare serialized to avoid object identity issues)
    const targetId = target ? `${target.x},${target.y},${target.z}` : null;
    if (targetId !== lastTargetId.current) {
      lastTargetId.current = targetId;
      if (target) {
        animatingTo.current = target.clone();
        cameraGoal.current.copy(target).add(new THREE.Vector3(0, 0, 12));
      } else {
        animatingTo.current = null;
      }
    }

    // Animate toward goal, then stop (don't hold the camera)
    if (animatingTo.current) {
      camera.position.lerp(cameraGoal.current, 0.06);
      if (camera.position.distanceTo(cameraGoal.current) < 0.01) {
        animatingTo.current = null;
      }
    }
  });

  return null;
}

/** Sweep momentum — decays autoRotate after a fast right-drag release. */
function SweepDecay({ orbitRef }: { orbitRef: React.RefObject<OrbitControlsImpl | null> }) {
  useFrame(() => {
    const controls = orbitRef.current;
    if (!controls || !controls.autoRotate) return;
    // Don't decay slow auto-orbit (cinematic mode)
    if (Math.abs(controls.autoRotateSpeed) < 1.0) return;
    controls.autoRotateSpeed *= 0.95;
    if (Math.abs(controls.autoRotateSpeed) < 0.01) {
      controls.autoRotate = false;
      controls.autoRotateSpeed = 0;
    }
  });
  return null;
}

/** Auto-orbit controller — slow cinematic rotation. */
function AutoOrbitController({
  orbitRef,
  active,
  onStop,
  sweepSuppressed,
}: {
  orbitRef: React.RefObject<OrbitControlsImpl | null>;
  active: boolean;
  onStop: () => void;
  sweepSuppressed: React.MutableRefObject<boolean>;
}) {
  useEffect(() => {
    if (!active) {
      const controls = orbitRef.current;
      if (controls && Math.abs(controls.autoRotateSpeed) < 1.0) {
        controls.autoRotate = false;
        controls.autoRotateSpeed = 0;
      }
      return;
    }
    const controls = orbitRef.current;
    if (controls) {
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.5;
    }

    let suppressTimer: ReturnType<typeof setTimeout> | null = null;
    const stopOnInteraction = () => {
      onStop();
      sweepSuppressed.current = true;
      suppressTimer = setTimeout(() => { sweepSuppressed.current = false; }, 500);
    };

    window.addEventListener("pointerdown", stopOnInteraction, { once: true });
    window.addEventListener("wheel", stopOnInteraction, { once: true });
    return () => {
      window.removeEventListener("pointerdown", stopOnInteraction);
      window.removeEventListener("wheel", stopOnInteraction);
      if (suppressTimer) clearTimeout(suppressTimer);
    };
  }, [active, orbitRef, onStop, sweepSuppressed]);

  return null;
}

/** Drives shader uniforms: radial reveal (0→1 over ~2s) and breathing time. */
function ShaderAnimator({
  materialRef,
}: {
  materialRef: React.RefObject<THREE.ShaderMaterial | null>;
}) {
  const startTime = useRef<number | null>(null);
  const revealDone = useRef(false);

  useFrame(({ clock }) => {
    const mat = materialRef.current;
    if (!mat) return;

    // Radial reveal (runs once, then stops)
    if (!revealDone.current) {
      if (startTime.current === null) startTime.current = performance.now();
      const reveal = Math.min((performance.now() - startTime.current) / 2000, 1.0);
      mat.uniforms.uReveal.value = reveal;
      if (reveal >= 1.0) revealDone.current = true;
    }

    // Breathing time (always active)
    mat.uniforms.uTime.value = clock.getElapsedTime();
  });

  return null;
}

/** One-shot camera fitter — positions camera to frame the data on first render. */
function DataFitter({ centroid, radius }: { centroid: [number, number, number]; radius: number }) {
  const { camera } = useThree();
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current) return;
    fitted.current = true;
    camera.position.set(centroid[0], centroid[1], centroid[2] + Math.max(radius * 2.5, 15));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

/** Spring animation for dragged nodes settling. */
function SpringAnimator({
  springs,
  geometryRef,
}: {
  springs: React.RefObject<Map<number, SpringState>>;
  geometryRef: React.RefObject<THREE.BufferGeometry | null>;
}) {
  useFrame(() => {
    const geo = geometryRef.current;
    const springMap = springs.current;
    if (!geo || springMap.size === 0) return;
    const posAttr = geo.attributes.position as THREE.BufferAttribute;
    const arr = posAttr.array as Float32Array;
    const toDelete: number[] = [];

    for (const [idx, s] of springMap) {
      const cx = arr[idx * 3];
      const cy = arr[idx * 3 + 1];
      const cz = arr[idx * 3 + 2];

      s.vx += (s.tx - cx) * SPRING_TENSION;
      s.vy += (s.ty - cy) * SPRING_TENSION;
      s.vz += (s.tz - cz) * SPRING_TENSION;
      s.vx *= SPRING_FRICTION;
      s.vy *= SPRING_FRICTION;
      s.vz *= SPRING_FRICTION;

      arr[idx * 3] = cx + s.vx;
      arr[idx * 3 + 1] = cy + s.vy;
      arr[idx * 3 + 2] = cz + s.vz;

      const dist = Math.abs(s.tx - arr[idx * 3]) + Math.abs(s.ty - arr[idx * 3 + 1]) + Math.abs(s.tz - arr[idx * 3 + 2]);
      const vel = Math.abs(s.vx) + Math.abs(s.vy) + Math.abs(s.vz);
      if (dist < 0.001 && vel < 0.001) toDelete.push(idx);
    }

    for (const idx of toDelete) springMap.delete(idx);
    if (toDelete.length > 0 || springMap.size > 0) {
      posAttr.needsUpdate = true;
    }
  });
  return null;
}

export function VizScene({ points, clusters, edges, focusedNode, onFocusNode, onNavigateNode, autoOrbit, onAutoOrbitStop, explodeFactor, onSpreadChange, device }: VizSceneProps) {
  const [hovered, setHovered] = useState<ProjectionPoint | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressTriggered = useRef(false);
  const longPressStartPos = useRef<{ x: number; y: number } | null>(null);

  // Refs for stable closure access (avoids dep-array churn in event handlers)
  const explodeFactorRef = useRef(explodeFactor);
  explodeFactorRef.current = explodeFactor;
  const pointsRef = useRef(points);
  pointsRef.current = points;
  const orbitRef = useRef<OrbitControlsImpl>(null);
  const dragState = useRef<DragState | null>(null);
  const dragOffsets = useRef<Map<number, THREE.Vector3>>(new Map());
  const geometryRef = useRef<THREE.BufferGeometry>(null);
  const edgeGeometryRef = useRef<THREE.BufferGeometry>(null);
  const springs = useRef<Map<number, SpringState>>(new Map());
  const cameraRef = useRef<THREE.Camera>(null);
  const materialRef = useRef<THREE.ShaderMaterial>(null);
  const nodeToEdgeVertsRef = useRef<Map<number, number[]>>(new Map());

  // Sweep velocity tracking (ring buffer of last 5 right-drag pointer events)
  const sweepBuffer = useRef<Array<{ x: number; y: number; t: number }>>([]);
  const isRightDragging = useRef(false);
  const sweepSuppressed = useRef(false);

  const pointIndex = useMemo(() => buildPointIndex(points), [points]);
  const bounds = useMemo(() => computeDataBounds(points), [points]);

  // Map node index → edge vertex indices (for real-time edge updates during drag)
  const nodeToEdgeVerts = useMemo(() => {
    const map = new Map<number, number[]>();
    const idToIdx = new Map<string, number>();
    for (let i = 0; i < points.length; i++) idToIdx.set(points[i].engram_id, i);

    let vertIdx = 0;
    for (const e of edges) {
      const si = idToIdx.get(e.source_engram_id);
      const ti = idToIdx.get(e.target_engram_id);
      if (si == null || ti == null || !pointIndex.has(e.source_engram_id) || !pointIndex.has(e.target_engram_id)) continue;
      // Each edge has 2 vertices: vertIdx (source), vertIdx+1 (target)
      if (!map.has(si)) map.set(si, []);
      map.get(si)!.push(vertIdx);
      if (!map.has(ti)) map.set(ti, []);
      map.get(ti)!.push(vertIdx + 1);
      vertIdx += 2;
    }
    return map;
  }, [points, edges, pointIndex]);

  nodeToEdgeVertsRef.current = nodeToEdgeVerts;

  // Network metrics computation
  const metrics = useMemo(() => computeNetworkMetrics(points, edges), [points, edges]);

  // Build cluster centroid map for explode
  const clusterCentroidMap = useMemo(() => {
    const map = new Map<number, { x: number; y: number; z: number }>();
    for (const c of clusters) {
      map.set(c.cluster_id, { x: c.centroid_x, y: c.centroid_y, z: c.centroid_z });
    }
    return map;
  }, [clusters]);

  const basePositionBuffer = useMemo(() => buildPositionBuffer(points), [points]);

  // Apply explode transform and drag offsets on top of cached base buffer
  const positionBuffer = useMemo(() => {
    const buf = new Float32Array(basePositionBuffer);
    if (explodeFactor !== 1.0) {
      for (let i = 0; i < points.length; i++) {
        const pt = points[i];
        const centroid = pt.cluster_id != null ? clusterCentroidMap.get(pt.cluster_id) : null;
        if (centroid) {
          buf[i * 3] = centroid.x + (buf[i * 3] - centroid.x) * explodeFactor;
          buf[i * 3 + 1] = centroid.y + (buf[i * 3 + 1] - centroid.y) * explodeFactor;
          buf[i * 3 + 2] = centroid.z + (buf[i * 3 + 2] - centroid.z) * explodeFactor;
        }
      }
    }
    // Apply persistent drag offsets
    for (const [idx, offset] of dragOffsets.current) {
      buf[idx * 3] += offset.x;
      buf[idx * 3 + 1] += offset.y;
      buf[idx * 3 + 2] += offset.z;
    }
    return buf;
  }, [basePositionBuffer, explodeFactor, points, clusterCentroidMap]);

  // All nodes show cluster colors
  const colorBuffer = useMemo(() => buildColorBuffer(points, "all"), [points]);
  const sizeBuffer = useMemo(() => buildSizeBuffer(points, metrics), [points, metrics]);
  const edgeBuffer = useMemo(
    () => buildEdgeBufferFromPositions(edges, pointIndex, points, positionBuffer),
    [edges, pointIndex, points, positionBuffer],
  );

  // Edge colors — highlight connected edges on focus (opacity baked into color)
  const edgeColors = useMemo(
    () => buildEdgeColorBuffer(edges, pointIndex, focusedNode?.engram_id, focusedNode?.cluster_id),
    [edges, pointIndex, focusedNode],
  );

  const clusterMap = useMemo(() => {
    const map = new Map<number, string | null>();
    for (const c of clusters) map.set(c.cluster_id, c.label);
    return map;
  }, [clusters]);

  const edgeVertexCount = edgeBuffer.length / 3;

  const cameraTarget = useMemo(() => {
    if (!focusedNode) return null;
    return new THREE.Vector3(focusedNode.x, focusedNode.y, focusedNode.z);
  }, [focusedNode]);

  const orbitTarget = useMemo(
    () => new THREE.Vector3(...bounds.centroid),
    [bounds],
  );

  const shaderMaterial = useMemo(() => {
    return new THREE.ShaderMaterial({
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      uniforms: {
        uReveal: { value: 0.0 },
        uTime: { value: 0.0 },
        uCentroid: { value: new THREE.Vector3(0, 0, 0) },
        uDataRadius: { value: 1.0 },
      },
    });
  }, []);

  // Update shader uniforms when data bounds change
  useEffect(() => {
    const mat = materialRef.current ?? shaderMaterial;
    if (!mat?.uniforms) return;
    mat.uniforms.uCentroid.value.set(...bounds.centroid);
    mat.uniforms.uDataRadius.value = Math.max(bounds.radius, 1.0);
  }, [bounds]);

  // Update color buffer when it changes
  useEffect(() => {
    const geo = geometryRef.current;
    if (!geo) return;
    const colorAttr = geo.attributes.color as THREE.BufferAttribute | undefined;
    if (colorAttr) {
      colorAttr.array.set(colorBuffer);
      colorAttr.needsUpdate = true;
    }
  }, [colorBuffer]);

  // Update edge colors when focus changes
  useEffect(() => {
    const geo = edgeGeometryRef.current;
    if (!geo) return;
    const colorAttr = geo.attributes.color as THREE.BufferAttribute | undefined;
    if (colorAttr) {
      colorAttr.array.set(edgeColors);
      colorAttr.needsUpdate = true;
    }
  }, [edgeColors]);

  // Raycaster for node picking during drag
  const raycaster = useMemo(() => new THREE.Raycaster(), []);
  const pointer = useMemo(() => new THREE.Vector2(), []);

  const handlePointerMove = (e: ThreeEvent<PointerEvent>) => {
    // Don't update hover during drag
    if (dragState.current?.active) return;

    if (e.intersections.length > 0) {
      const idx = e.intersections[0].index;
      if (idx != null) {
        const pt = pointAtIndex(points, idx);
        setHovered(pt);
        if (canvasRef.current) canvasRef.current.style.cursor = "pointer";
        return;
      }
    }
    setHovered(null);
    if (canvasRef.current) canvasRef.current.style.cursor = "";
  };

  const handlePointerLeave = () => {
    if (dragState.current?.active) return;
    setHovered(null);
    if (canvasRef.current) canvasRef.current.style.cursor = "";
  };

  const handleClick = useCallback(() => {
    // Don't fire click if we were dragging
    if (dragState.current?.active) return;
    // Don't fire click if long-press already triggered focus
    if (longPressTriggered.current) {
      longPressTriggered.current = false;
      return;
    }

    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
      if (hovered) {
        onNavigateNode(hovered.engram_id);
      }
      return;
    }
    const currentHovered = hovered;
    clickTimerRef.current = setTimeout(() => {
      clickTimerRef.current = null;
      if (currentHovered) {
        onFocusNode(currentHovered);
      } else {
        onFocusNode(null);
      }
    }, 250);
  }, [hovered, onFocusNode, onNavigateNode]);

  // Node dragging — pointer down on points (with long-press for touch focus)
  const handlePointsPointerDown = useCallback((e: ThreeEvent<PointerEvent>) => {
    // Only left button for node drag
    if (e.nativeEvent.button !== 0) return;
    if (e.intersections.length === 0) return;
    const idx = e.intersections[0].index;
    if (idx == null) return;

    e.stopPropagation();

    // Track start position for long-press threshold
    longPressStartPos.current = { x: e.nativeEvent.clientX, y: e.nativeEvent.clientY };
    longPressTriggered.current = false;

    // Start long-press timer for touch focus
    if (device === "touch") {
      const pt = pointAtIndex(pointsRef.current, idx);
      longPressTimerRef.current = setTimeout(() => {
        longPressTimerRef.current = null;
        if (pt) {
          longPressTriggered.current = true;
          onFocusNode(pt);
        }
      }, 400);
    }

    const geo = geometryRef.current;
    if (!geo) return;
    const posAttr = geo.attributes.position as THREE.BufferAttribute;
    const arr = posAttr.array as Float32Array;
    const nodePos = new THREE.Vector3(arr[idx * 3], arr[idx * 3 + 1], arr[idx * 3 + 2]);

    const camera = e.camera;
    const shiftKey = e.nativeEvent.shiftKey;

    let plane: THREE.Plane;
    if (shiftKey) {
      // Z-yank: plane perpendicular to camera's right vector (so Y mouse movement = depth)
      const camDir = new THREE.Vector3();
      camera.getWorldDirection(camDir);
      const camRight = new THREE.Vector3();
      camRight.crossVectors(camDir, camera.up).normalize();
      plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camRight, nodePos);
    } else {
      // Planar drag: plane facing camera at node depth
      const camDir = new THREE.Vector3();
      camera.getWorldDirection(camDir);
      plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camDir.negate(), nodePos);
    }

    // Calculate offset so node doesn't jump to cursor
    const ray = e.ray;
    const intersection = new THREE.Vector3();
    ray.intersectPlane(plane, intersection);
    const offset = new THREE.Vector3().subVectors(nodePos, intersection);

    dragState.current = { active: true, nodeIndex: idx, plane, offset, shiftKey, originalPos: nodePos.clone() };

    // Clear any spring on this node
    springs.current.delete(idx);

    if (orbitRef.current) orbitRef.current.enabled = false;
    if (canvasRef.current) canvasRef.current.style.cursor = "grabbing";
  }, [device, onFocusNode]);

  // Window-level pointer move/up for dragging
  useEffect(() => {
    const handleWindowPointerMove = (e: PointerEvent) => {
      // Cancel long-press if pointer moves >10px
      if (longPressTimerRef.current && longPressStartPos.current) {
        const dx = e.clientX - longPressStartPos.current.x;
        const dy = e.clientY - longPressStartPos.current.y;
        if (dx * dx + dy * dy > 100) {
          clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }
      }

      // Track sweep buffer for right-drag
      if (isRightDragging.current) {
        const buf = sweepBuffer.current;
        buf.push({ x: e.clientX, y: e.clientY, t: performance.now() });
        if (buf.length > 5) buf.shift();
      }

      const ds = dragState.current;
      if (!ds?.active) return;

      const canvas = canvasRef.current?.querySelector("canvas");
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      const geo = geometryRef.current;
      if (!geo) return;
      const posAttr = geo.attributes.position as THREE.BufferAttribute;
      const arr = posAttr.array as Float32Array;

      const camera = cameraRef.current;
      if (!camera) return;
      raycaster.setFromCamera(pointer, camera);

      const intersection = new THREE.Vector3();
      if (!raycaster.ray.intersectPlane(ds.plane, intersection)) return;

      const target = intersection.add(ds.offset);
      arr[ds.nodeIndex * 3] = target.x;
      arr[ds.nodeIndex * 3 + 1] = target.y;
      arr[ds.nodeIndex * 3 + 2] = target.z;
      posAttr.needsUpdate = true;

      // Update connected edge positions
      const edgeGeo = edgeGeometryRef.current;
      const edgeVerts = nodeToEdgeVertsRef.current.get(ds.nodeIndex);
      if (edgeGeo && edgeVerts) {
        const edgePosAttr = edgeGeo.attributes.position as THREE.BufferAttribute;
        const edgeArr = edgePosAttr.array as Float32Array;
        for (const vi of edgeVerts) {
          edgeArr[vi * 3] = target.x;
          edgeArr[vi * 3 + 1] = target.y;
          edgeArr[vi * 3 + 2] = target.z;
        }
        edgePosAttr.needsUpdate = true;
      }
    };

    const handleWindowPointerUp = (e: PointerEvent) => {
      // Cancel any pending long-press
      if (longPressTimerRef.current) {
        clearTimeout(longPressTimerRef.current);
        longPressTimerRef.current = null;
      }

      // Sweep detection on right button release
      if (e.button === 2 && isRightDragging.current) {
        isRightDragging.current = false;
        const buf = sweepBuffer.current;
        if (buf.length >= 2) {
          const last = buf[buf.length - 1];
          const first = buf[0];
          const dt = last.t - first.t;
          if (dt > 0 && dt < 300) {
            const vx = (last.x - first.x) / dt;
            const vy = (last.y - first.y) / dt;
            const speed = Math.sqrt(vx * vx + vy * vy);
            if (speed > 1.5 && orbitRef.current && !sweepSuppressed.current) {
              orbitRef.current.autoRotate = true;
              orbitRef.current.autoRotateSpeed = speed * 15 * (vx > 0 ? 1 : -1);
            }
          }
        }
        sweepBuffer.current = [];
      }

      const ds = dragState.current;
      if (!ds?.active) return;

      // Persist drag offset so position survives re-renders
      const geo = geometryRef.current;
      if (geo) {
        const arr = (geo.attributes.position as THREE.BufferAttribute).array as Float32Array;
        const currentPos = new THREE.Vector3(
          arr[ds.nodeIndex * 3],
          arr[ds.nodeIndex * 3 + 1],
          arr[ds.nodeIndex * 3 + 2],
        );
        const delta = currentPos.clone().sub(ds.originalPos);
        if (delta.lengthSq() > 0.0001) {
          const existing = dragOffsets.current.get(ds.nodeIndex);
          if (existing) {
            existing.add(delta);
          } else {
            dragOffsets.current.set(ds.nodeIndex, delta);
          }
        }
      }

      dragState.current = null;
      if (orbitRef.current) orbitRef.current.enabled = true;
      if (canvasRef.current) canvasRef.current.style.cursor = "";
    };

    const handleRightDown = (e: PointerEvent) => {
      if (e.button === 2) {
        isRightDragging.current = true;
        sweepBuffer.current = [{ x: e.clientX, y: e.clientY, t: performance.now() }];
      }
    };

    window.addEventListener("pointermove", handleWindowPointerMove);
    window.addEventListener("pointerup", handleWindowPointerUp);
    window.addEventListener("pointerdown", handleRightDown);

    return () => {
      window.removeEventListener("pointermove", handleWindowPointerMove);
      window.removeEventListener("pointerup", handleWindowPointerUp);
      window.removeEventListener("pointerdown", handleRightDown);
    };
  }, [raycaster, pointer]);

  const clusterLabel = useMemo(() => getClusterLabel(hovered, clusterMap), [hovered, clusterMap]);
  const focusedClusterLabel = useMemo(() => getClusterLabel(focusedNode, clusterMap), [focusedNode, clusterMap]);

  // Explode/contract on alt+scroll (Option+scroll on macOS)
  // Native capture-phase listener to intercept before OrbitControls
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      if (!e.altKey) return;
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      let dy = e.deltaY;
      if (e.deltaMode === 1) dy *= 40;
      if (e.deltaMode === 2) dy *= 800;
      onSpreadChange(explodeFactorRef.current + dy * -0.005);
    };
    el.addEventListener("wheel", handler, { capture: true, passive: false });
    return () => el.removeEventListener("wheel", handler, { capture: true });
  }, [onSpreadChange]);

  // Edge material with vertex colors
  const edgeMaterial = useMemo(() => {
    return new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      linewidth: 2,
    });
  }, []);

  return (
    <div
      ref={canvasRef}
      className="viz-canvas-wrapper h-full w-full"
      data-testid="viz-canvas"
      onContextMenu={(e) => e.preventDefault()}
    >
      <Canvas
        camera={{ position: [0, 0, 30], fov: 60 }}
        raycaster={{ params: { Points: { threshold: 0.3 } } as unknown as RaycasterParameters }}
        gl={{ antialias: true, alpha: true }}
        onPointerMissed={() => onFocusNode(null)}
      >
        {/* Store camera ref for window-level drag raycasting */}
        <CameraStorer cameraRef={cameraRef} />

        {/* Atmosphere */}
        <ambientLight intensity={0.6} />

        <DataFitter centroid={bounds.centroid} radius={bounds.radius} />
        <CameraController target={cameraTarget} />
        <SweepDecay orbitRef={orbitRef} />
        <SpringAnimator springs={springs} geometryRef={geometryRef} />
        <AutoOrbitController orbitRef={orbitRef} active={autoOrbit} onStop={onAutoOrbitStop} sweepSuppressed={sweepSuppressed} />
        <ShaderAnimator materialRef={materialRef} />

        <OrbitControls
          ref={orbitRef}
          target={orbitTarget}
          enableDamping
          dampingFactor={0.12}
          screenSpacePanning
          mouseButtons={{ LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE }}
          touches={{ ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE }}
          minDistance={3}
          maxDistance={100}
        />

        {/* Point cloud */}
        <points
          onPointerMove={handlePointerMove}
          onPointerLeave={handlePointerLeave}
          onClick={handleClick}
          onPointerDown={handlePointsPointerDown}
        >
          <bufferGeometry ref={geometryRef}>
            <bufferAttribute
              attach="attributes-position"
              args={[positionBuffer, 3]}
            />
            <bufferAttribute
              attach="attributes-color"
              args={[colorBuffer, 3]}
            />
            <bufferAttribute
              attach="attributes-size"
              args={[sizeBuffer, 1]}
            />
          </bufferGeometry>
          <primitive object={shaderMaterial} attach="material" ref={materialRef} />
        </points>

        {/* Edges */}
        {edgeVertexCount > 0 && (
          <lineSegments>
            <bufferGeometry ref={edgeGeometryRef}>
              <bufferAttribute
                attach="attributes-position"
                args={[edgeBuffer, 3]}
              />
              <bufferAttribute
                attach="attributes-color"
                args={[edgeColors, 3]}
              />
            </bufferGeometry>
            <primitive object={edgeMaterial} attach="material" />
          </lineSegments>
        )}

        {/* Cluster labels */}
        {clusters.map((c) => (
          <Html
            key={c.cluster_id}
            position={[c.centroid_x, c.centroid_y, c.centroid_z]}
            center
          >
            <span className="viz-cluster-label font-mono text-[12px] pointer-events-none select-none whitespace-nowrap">
              {c.label ?? `Cluster ${c.cluster_id}`}
            </span>
          </Html>
        ))}

        {/* Tooltip (only when not showing focused card) */}
        {hovered && !focusedNode && (
          <Html
            position={[hovered.x, hovered.y, hovered.z]}
            style={{ pointerEvents: "none", transform: "translate(12px, -50%)" }}
          >
            <VizTooltip name={hovered.canonical_name} clusterLabel={clusterLabel} />
          </Html>
        )}

        {/* Focused node card */}
        {focusedNode && (
          <Html
            position={[focusedNode.x, focusedNode.y, focusedNode.z]}
            style={{ transform: "translate(12px, -50%)" }}
          >
            <VizNodeCard
              name={focusedNode.canonical_name}
              clusterLabel={focusedClusterLabel}
              onOpen={() => onNavigateNode(focusedNode.engram_id)}
            />
          </Html>
        )}
      </Canvas>
    </div>
  );
}

/** Stores camera reference for window-level drag events. */
function CameraStorer({ cameraRef }: { cameraRef: React.MutableRefObject<THREE.Camera | null> }) {
  const { camera } = useThree();
  useEffect(() => {
    cameraRef.current = camera;
  }, [camera, cameraRef]);
  return null;
}
