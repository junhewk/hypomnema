"use client";

import { useMemo, useRef, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Canvas, useFrame, invalidate } from "@react-three/fiber";
import { useVizDataCtx } from "@/hooks/useVizDataContext";
import {
  buildPositionBuffer,
  buildColorBuffer,
  buildEdgeBuffer,
  buildPointIndex,
} from "@/lib/vizTransforms";
import type { Group } from "three";

function MinimapScene() {
  const { points, edges } = useVizDataCtx();
  const groupRef = useRef<Group>(null);

  const pointIndex = useMemo(() => buildPointIndex(points), [points]);
  const positionBuffer = useMemo(() => buildPositionBuffer(points), [points]);
  const colorBuffer = useMemo(() => buildColorBuffer(points), [points]);
  const edgeBuffer = useMemo(
    () => buildEdgeBuffer(edges, pointIndex),
    [edges, pointIndex],
  );

  const edgeVertexCount = edgeBuffer.length / 3;

  // Slow auto-rotation — only runs when Canvas renders a frame
  useFrame((_state, delta) => {
    if (groupRef.current) {
      groupRef.current.rotation.y += delta * 0.12;
    }
  });

  if (points.length === 0) return null;

  return (
    <group ref={groupRef}>
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

/** Ticks invalidation at a low framerate to drive the rotation without a full 60fps loop. */
function SlowTicker({ fps }: { fps: number }) {
  useEffect(() => {
    const interval = setInterval(() => invalidate(), 1000 / fps);
    return () => clearInterval(interval);
  }, [fps]);
  return null;
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
          <SlowTicker fps={10} />
        </Canvas>
      )}
    </div>
  );
}
