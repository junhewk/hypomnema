import { useState, useEffect } from "react";

export type InputDevice = "pointer" | "touch";
export type Platform = "mac" | "windows" | "linux";

interface InputDeviceInfo {
  device: InputDevice;
  platform: Platform;
  modKey: "opt" | "alt";
}

function detectPlatform(): Platform {
  const ua =
    (navigator as unknown as { userAgentData?: { platform?: string } })
      .userAgentData?.platform ?? navigator.platform;
  if (/mac/i.test(ua)) return "mac";
  if (/win/i.test(ua)) return "windows";
  return "linux";
}

export function useInputDevice(): InputDeviceInfo {
  const [device, setDevice] = useState<InputDevice>(() => {
    if (typeof window === "undefined") return "pointer";
    return window.matchMedia("(hover: hover) and (pointer: fine)").matches
      ? "pointer"
      : "touch";
  });

  const [platform] = useState<Platform>(() => {
    if (typeof window === "undefined") return "linux";
    return detectPlatform();
  });

  useEffect(() => {
    const mq = window.matchMedia("(hover: hover) and (pointer: fine)");
    const handler = (e: MediaQueryListEvent) => {
      setDevice(e.matches ? "pointer" : "touch");
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return {
    device,
    platform,
    modKey: platform === "mac" ? "opt" : "alt",
  };
}
