"use client";

import { useMemo, useRef, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Canvas, invalidate } from "@react-three/fiber";
import { useVizDataCtx } from "@/hooks/useVizDataContext";
import {
  buildPositionBuffer,
  buildColorBuffer,
  buildEdgeBuffer,
  buildPointIndex,
} from "@/lib/vizTransforms";

function MinimapScene() {
  const { points, edges } = useVizDataCtx();

  const pointIndex = useMemo(() => buildPointIndex(points), [points]);
  const positionBuffer = useMemo(() => buildPositionBuffer(points), [points]);
  const colorBuffer = useMemo(() => buildColorBuffer(points), [points]);
  const edgeBuffer = useMemo(
    () => buildEdgeBuffer(edges, pointIndex),
    [edges, pointIndex],
  );

  const edgeVertexCount = edgeBuffer.length / 3;

  // Invalidate once when points change so the static scene renders
  useEffect(() => {
    if (points.length > 0) invalidate();
  }, [points]);

  if (points.length === 0) return null;

  return (
    <group>
      <points>
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
          size={2.5}
          vertexColors
          sizeAttenuation={false}
          transparent
          opacity={0.85}
          depthWrite={false}
        />
      </points>

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
            opacity={0.1}
            depthWrite={false}
          />
        </lineSegments>
      )}
    </group>
  );
}

export function VizMinimap() {
  const router = useRouter();
  const { points, isLoading } = useVizDataCtx();
  const [visible, setVisible] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Only render Canvas when minimap is in viewport
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(entry.isIntersecting),
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  if (isLoading || points.length === 0) return null;

  return (
    <div
      ref={containerRef}
      className="minimap-container cursor-pointer"
      style={{ height: 160 }}
      onClick={() => router.push("/viz")}
      title="Open full visualization"
      data-testid="viz-minimap"
    >
      {visible && (
        <Canvas
          frameloop="demand"
          camera={{ position: [0, 0, 40], fov: 50 }}
          gl={{ antialias: false, alpha: true }}
          style={{ pointerEvents: "none" }}
        >
          <ambientLight intensity={0.5} />
          <MinimapScene />
        </Canvas>
      )}
    </div>
  );
}
