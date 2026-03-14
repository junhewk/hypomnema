"use client";

import { useRef, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useVizDataCtx } from "@/hooks/useVizDataContext";
import { clusterColor, buildPointIndex } from "@/lib/vizTransforms";

export function VizMinimap() {
  const router = useRouter();
  const { points, edges, isLoading } = useVizDataCtx();
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pointIndex = useMemo(() => buildPointIndex(points), [points]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    canvas.width = w * dpr;
    canvas.height = h * dpr;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    // Compute bounding box (2D: x, y only)
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of points) {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    }

    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const padding = 0.1;
    const padX = rangeX * padding;
    const padY = rangeY * padding;

    // Uniform scale to fit canvas
    const scaleX = w / (rangeX + 2 * padX);
    const scaleY = h / (rangeY + 2 * padY);
    const scale = Math.min(scaleX, scaleY);

    const offsetX = (w - rangeX * scale) / 2;
    const offsetY = (h - rangeY * scale) / 2;

    const toScreen = (x: number, y: number): [number, number] => [
      offsetX + (x - minX) * scale,
      offsetY + (y - minY) * scale,
    ];

    // Draw edges
    ctx.strokeStyle = "rgba(168, 162, 158, 0.18)";
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    for (const e of edges) {
      const src = pointIndex.get(e.source_engram_id);
      const tgt = pointIndex.get(e.target_engram_id);
      if (!src || !tgt) continue;
      const [sx, sy] = toScreen(src.x, src.y);
      const [tx, ty] = toScreen(tgt.x, tgt.y);
      ctx.moveTo(sx, sy);
      ctx.lineTo(tx, ty);
    }
    ctx.stroke();

    // Draw points — batch by cluster color for fewer style switches
    const byCluster = new Map<number | null, Array<[number, number]>>();
    for (const p of points) {
      const key = p.cluster_id ?? -1;
      if (!byCluster.has(key)) byCluster.set(key, []);
      byCluster.get(key)!.push(toScreen(p.x, p.y));
    }

    ctx.globalCompositeOperation = "screen";
    for (const [clusterId, pts] of byCluster) {
      const [r, g, b] = clusterColor(clusterId === -1 ? null : clusterId);
      ctx.fillStyle = `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, 0.9)`;
      ctx.shadowColor = `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, 0.5)`;
      ctx.shadowBlur = 3;
      ctx.beginPath();
      for (const [px, py] of pts) {
        ctx.moveTo(px + 1.5, py);
        ctx.arc(px, py, 1.5, 0, Math.PI * 2);
      }
      ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
    ctx.shadowBlur = 0;
  }, [points, edges, pointIndex]);

  // Re-render when data changes
  useEffect(() => {
    // requestAnimationFrame ensures canvas ref is attached after render
    requestAnimationFrame(draw);
  }, [draw]);

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
      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: "100%", pointerEvents: "none" }}
      />
    </div>
  );
}
