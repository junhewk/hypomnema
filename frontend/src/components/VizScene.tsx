"use client";

import { useMemo, useState, useRef, useCallback } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Html } from "@react-three/drei";
import { useRouter } from "next/navigation";
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
    gl_PointSize = size;
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const FRAGMENT_SHADER = `
  varying vec3 vColor;
  void main() {
    float dist = length(gl_PointCoord - vec2(0.5));
    if (dist > 0.5) discard;
    float alpha = 1.0 - smoothstep(0.4, 0.5, dist);
    gl_FragColor = vec4(vColor, alpha * 0.9);
  }
`;

interface VizSceneProps {
  points: ProjectionPoint[];
  clusters: Cluster[];
  edges: VizEdge[];
  focusedNode: ProjectionPoint | null;
  onFocusNode: (node: ProjectionPoint | null) => void;
  onNavigateNode: (engramId: string) => void;
}

/** Smooth camera animation to a target position. */
function CameraController({ target }: { target: THREE.Vector3 | null }) {
  const targetRef = useRef<THREE.Vector3 | null>(null);
  const cameraTarget = useRef(new THREE.Vector3());
  const initialDistance = useRef(30);

  useFrame(({ camera }) => {
    if (target && !target.equals(targetRef.current ?? new THREE.Vector3())) {
      targetRef.current = target.clone();
      // Position camera at an offset from the target
      cameraTarget.current.copy(target).add(new THREE.Vector3(0, 0, 12));
      initialDistance.current = camera.position.distanceTo(target);
    }
    if (targetRef.current) {
      camera.position.lerp(cameraTarget.current, 0.06);
      // Check if close enough to stop
      if (camera.position.distanceTo(cameraTarget.current) < 0.01) {
        targetRef.current = null;
      }
    }
  });

  return null;
}

export function VizScene({ points, clusters, edges, focusedNode, onFocusNode, onNavigateNode }: VizSceneProps) {
  const [hovered, setHovered] = useState<ProjectionPoint | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const pointIndex = useMemo(() => buildPointIndex(points), [points]);
  const positionBuffer = useMemo(() => buildPositionBuffer(points), [points]);
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

  const handlePointerMove = (e: ThreeEvent<PointerEvent>) => {
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
    setHovered(null);
    if (canvasRef.current) canvasRef.current.style.cursor = "";
  };

  const handleClick = useCallback(() => {
    if (clickTimerRef.current) {
      // Double click detected — clear single-click timer
      clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
      if (hovered) {
        onNavigateNode(hovered.engram_id);
      }
      return;
    }
    // Delay single click to distinguish from double click
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

  const clusterLabel = useMemo(() => {
    if (!hovered || hovered.cluster_id == null) return null;
    const label = clusterMap.get(hovered.cluster_id);
    return label ?? `Cluster ${hovered.cluster_id}`;
  }, [hovered, clusterMap]);

  const focusedClusterLabel = useMemo(() => {
    if (!focusedNode || focusedNode.cluster_id == null) return null;
    const label = clusterMap.get(focusedNode.cluster_id);
    return label ?? `Cluster ${focusedNode.cluster_id}`;
  }, [focusedNode, clusterMap]);

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
      >
        {/* Atmosphere */}
        <fog attach="fog" args={["#08080a", 35, 80]} />
        <ambientLight intensity={0.6} />

        <CameraController target={cameraTarget} />

        <OrbitControls
          enableDamping
          dampingFactor={0.08}
          mouseButtons={{ LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN }}
          touches={{ ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN }}
          minDistance={3}
          maxDistance={100}
        />

        {/* Point cloud */}
        <points
          onPointerMove={handlePointerMove}
          onPointerLeave={handlePointerLeave}
          onClick={handleClick}
        >
          <bufferGeometry>
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
              color="#a8a29e"
              transparent
              opacity={0.18}
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
            <span className="viz-cluster-label font-mono text-[9px] text-muted/70 pointer-events-none select-none whitespace-nowrap">
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
