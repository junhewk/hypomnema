"use client";

import { useMemo, useState, useRef } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Html } from "@react-three/drei";
import { useRouter } from "next/navigation";
import type { ProjectionPoint, Cluster, VizEdge } from "@/lib/types";
import {
  buildPositionBuffer,
  buildColorBuffer,
  buildEdgeBuffer,
  buildPointIndex,
  pointAtIndex,
} from "@/lib/vizTransforms";
import { VizTooltip } from "./VizTooltip";
import type { ThreeEvent } from "@react-three/fiber";
import type { RaycasterParameters } from "three";

interface VizSceneProps {
  points: ProjectionPoint[];
  clusters: Cluster[];
  edges: VizEdge[];
}

export function VizScene({ points, clusters, edges }: VizSceneProps) {
  const router = useRouter();
  const [hovered, setHovered] = useState<ProjectionPoint | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  const pointIndex = useMemo(() => buildPointIndex(points), [points]);
  const positionBuffer = useMemo(() => buildPositionBuffer(points), [points]);
  const colorBuffer = useMemo(() => buildColorBuffer(points), [points]);
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

  const handleClick = () => {
    if (hovered) {
      router.push(`/engrams/${hovered.engram_id}`);
    }
  };

  const clusterLabel = useMemo(() => {
    if (!hovered || hovered.cluster_id == null) return null;
    const label = clusterMap.get(hovered.cluster_id);
    return label ?? `Cluster ${hovered.cluster_id}`;
  }, [hovered, clusterMap]);

  return (
    <div ref={canvasRef} className="h-full w-full" data-testid="viz-canvas">
      <Canvas
        camera={{ position: [0, 0, 30], fov: 60 }}
        raycaster={{ params: { Points: { threshold: 0.3 } } as unknown as RaycasterParameters }}
        gl={{ antialias: true, alpha: true }}
      >
        {/* Atmosphere */}
        <fog attach="fog" args={["#08080a", 35, 80]} />
        <ambientLight intensity={0.6} />

        <OrbitControls enableDamping dampingFactor={0.08} />

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
          </bufferGeometry>
          <pointsMaterial
            size={5}
            vertexColors
            sizeAttenuation={false}
            transparent
            opacity={0.9}
            depthWrite={false}
          />
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

        {/* Tooltip */}
        {hovered && (
          <Html
            position={[hovered.x, hovered.y, hovered.z]}
            style={{ pointerEvents: "none", transform: "translate(12px, -50%)" }}
          >
            <VizTooltip name={hovered.canonical_name} clusterLabel={clusterLabel} />
          </Html>
        )}
      </Canvas>
    </div>
  );
}
