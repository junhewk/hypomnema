"use client";

import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Html } from "@react-three/drei";
import { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import * as THREE from "three";
import type { ProjectionPoint, Cluster, VizEdge } from "@/lib/types";
import {
  buildPositionBuffer,
  buildColorBuffer,
  buildEdgeBuffer,
  buildPointIndex,
  buildSizeBuffer,
  pointAtIndex,
} from "@/lib/vizTransforms";
import { VizTooltip } from "./VizTooltip";
import { VizNodeCard } from "./VizNodeCard";
import type { ThreeEvent } from "@react-three/fiber";
import type { RaycasterParameters } from "three";

const VERTEX_SHADER = `
  attribute float size;
  varying vec3 vColor;
  void main() {
    vColor = color;
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = size * (300.0 / length(mvPosition.xyz));
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const FRAGMENT_SHADER = `
  varying vec3 vColor;
  void main() {
    float dist = length(gl_PointCoord - vec2(0.5));
    if (dist > 0.5) discard;

    // Bright core with soft radial falloff
    float core = 1.0 - smoothstep(0.0, 0.28, dist);
    float body = 1.0 - smoothstep(0.15, 0.45, dist);
    float glow = 1.0 - smoothstep(0.3, 0.5, dist);

    // Composite: luminous center + colored body + faint halo
    vec3 col = mix(vColor, vColor + vec3(0.15), core);
    float alpha = (body * 0.85 + glow * 0.25) * 0.95;

    gl_FragColor = vec4(col, alpha);
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
}

interface VizSceneProps {
  points: ProjectionPoint[];
  clusters: Cluster[];
  edges: VizEdge[];
  focusedNode: ProjectionPoint | null;
  onFocusNode: (node: ProjectionPoint | null) => void;
  onNavigateNode: (engramId: string) => void;
}

function getClusterLabel(node: ProjectionPoint | null, clusterMap: Map<number, string | null>): string | null {
  if (!node || node.cluster_id == null) return null;
  const label = clusterMap.get(node.cluster_id);
  return label ?? `Cluster ${node.cluster_id}`;
}

/** Smooth camera animation to a target position. */
function CameraController({ target }: { target: THREE.Vector3 | null }) {
  const targetRef = useRef<THREE.Vector3 | null>(null);
  const cameraTarget = useRef(new THREE.Vector3());

  useFrame(({ camera }) => {
    if (target && !target.equals(targetRef.current ?? new THREE.Vector3())) {
      targetRef.current = target.clone();
      cameraTarget.current.copy(target).add(new THREE.Vector3(0, 0, 12));
    }
    if (targetRef.current) {
      camera.position.lerp(cameraTarget.current, 0.06);
      if (camera.position.distanceTo(cameraTarget.current) < 0.01) {
        targetRef.current = null;
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
    controls.autoRotateSpeed *= 0.95;
    if (Math.abs(controls.autoRotateSpeed) < 0.01) {
      controls.autoRotate = false;
      controls.autoRotateSpeed = 0;
    }
  });
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

export function VizScene({ points, clusters, edges, focusedNode, onFocusNode, onNavigateNode }: VizSceneProps) {
  const [hovered, setHovered] = useState<ProjectionPoint | null>(null);
  const [explodeFactor, setExplodeFactor] = useState(1.0);
  const canvasRef = useRef<HTMLDivElement>(null);
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const orbitRef = useRef<OrbitControlsImpl>(null);
  const dragState = useRef<DragState | null>(null);
  const geometryRef = useRef<THREE.BufferGeometry>(null);
  const springs = useRef<Map<number, SpringState>>(new Map());
  const cameraRef = useRef<THREE.Camera>(null);

  // Sweep velocity tracking (ring buffer of last 5 right-drag pointer events)
  const sweepBuffer = useRef<Array<{ x: number; y: number; t: number }>>([]);
  const isRightDragging = useRef(false);

  const pointIndex = useMemo(() => buildPointIndex(points), [points]);

  // Build cluster centroid map for explode
  const clusterCentroidMap = useMemo(() => {
    const map = new Map<number, { x: number; y: number; z: number }>();
    for (const c of clusters) {
      map.set(c.cluster_id, { x: c.centroid_x, y: c.centroid_y, z: c.centroid_z });
    }
    return map;
  }, [clusters]);

  const basePositionBuffer = useMemo(() => buildPositionBuffer(points), [points]);

  // Apply explode transform on top of cached base buffer
  const positionBuffer = useMemo(() => {
    if (explodeFactor === 1.0) return basePositionBuffer;
    const buf = new Float32Array(basePositionBuffer);
    for (let i = 0; i < points.length; i++) {
      const pt = points[i];
      const centroid = pt.cluster_id != null ? clusterCentroidMap.get(pt.cluster_id) : null;
      if (centroid) {
        buf[i * 3] = centroid.x + (buf[i * 3] - centroid.x) * explodeFactor;
        buf[i * 3 + 1] = centroid.y + (buf[i * 3 + 1] - centroid.y) * explodeFactor;
        buf[i * 3 + 2] = centroid.z + (buf[i * 3 + 2] - centroid.z) * explodeFactor;
      }
    }
    return buf;
  }, [basePositionBuffer, explodeFactor, points, clusterCentroidMap]);

  const colorBuffer = useMemo(() => buildColorBuffer(points), [points]);
  const sizeBuffer = useMemo(() => buildSizeBuffer(points, edges), [points, edges]);
  const edgeBuffer = useMemo(
    () => buildEdgeBuffer(edges, pointIndex),
    [edges, pointIndex],
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

  const shaderMaterial = useMemo(() => {
    return new THREE.ShaderMaterial({
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
    });
  }, []);

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

  // Node dragging — pointer down on points
  const handlePointsPointerDown = useCallback((e: ThreeEvent<PointerEvent>) => {
    // Only left button for node drag
    if (e.nativeEvent.button !== 0) return;
    if (e.intersections.length === 0) return;
    const idx = e.intersections[0].index;
    if (idx == null) return;

    e.stopPropagation();

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

    dragState.current = { active: true, nodeIndex: idx, plane, offset, shiftKey };

    // Clear any spring on this node
    springs.current.delete(idx);

    if (orbitRef.current) orbitRef.current.enabled = false;
    if (canvasRef.current) canvasRef.current.style.cursor = "grabbing";
  }, []);

  // Window-level pointer move/up for dragging
  useEffect(() => {
    const handleWindowPointerMove = (e: PointerEvent) => {
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
    };

    const handleWindowPointerUp = (e: PointerEvent) => {
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
            if (speed > 0.5 && orbitRef.current) {
              orbitRef.current.autoRotate = true;
              orbitRef.current.autoRotateSpeed = speed * 15 * (vx > 0 ? 1 : -1);
            }
          }
        }
        sweepBuffer.current = [];
      }

      const ds = dragState.current;
      if (!ds?.active) return;
      if (e.button !== 0) return;

      // Start spring settle at current position
      const geo = geometryRef.current;
      if (geo) {
        const arr = (geo.attributes.position as THREE.BufferAttribute).array as Float32Array;
        const x = arr[ds.nodeIndex * 3];
        const y = arr[ds.nodeIndex * 3 + 1];
        const z = arr[ds.nodeIndex * 3 + 2];
        springs.current.set(ds.nodeIndex, { vx: 0, vy: 0, vz: 0, tx: x, ty: y, tz: z });
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

  // Explode/contract on ctrl+scroll
  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (e.ctrlKey) {
      e.preventDefault();
      setExplodeFactor(prev => Math.max(0.3, Math.min(3.0, prev + e.deltaY * -0.002)));
    }
  }, []);

  return (
    <div
      ref={canvasRef}
      className="viz-canvas-wrapper h-full w-full"
      data-testid="viz-canvas"
      onContextMenu={(e) => e.preventDefault()}
      onWheel={handleWheel}
    >
      <Canvas
        camera={{ position: [0, 0, 30], fov: 60 }}
        raycaster={{ params: { Points: { threshold: 0.3 } } as unknown as RaycasterParameters }}
        gl={{ antialias: true, alpha: true }}
      >
        {/* Store camera ref for window-level drag raycasting */}
        <CameraStorer cameraRef={cameraRef} />

        {/* Atmosphere */}
        <fog attach="fog" args={["#08080a", 35, 80]} />
        <ambientLight intensity={0.6} />

        <CameraController target={cameraTarget} />
        <SweepDecay orbitRef={orbitRef} />
        <SpringAnimator springs={springs} geometryRef={geometryRef} />

        <OrbitControls
          ref={orbitRef}
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
          <primitive object={shaderMaterial} attach="material" />
        </points>

        {/* Edges */}
        {edgeVertexCount > 0 && (
          <lineSegments>
            <bufferGeometry>
              <bufferAttribute
                attach="attributes-position"
                args={[edgeBuffer, 3]}
              />
            </bufferGeometry>
            <lineBasicMaterial
              color="#c4b5a8"
              transparent
              opacity={0.4}
              depthWrite={false}
            />
          </lineSegments>
        )}

        {/* Cluster labels */}
        {clusters.map((c) => (
          <Html
            key={c.cluster_id}
            position={[c.centroid_x, c.centroid_y, c.centroid_z]}
            center
          >
            <span className="viz-cluster-label font-mono text-[11px] text-muted/85 pointer-events-none select-none whitespace-nowrap">
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
