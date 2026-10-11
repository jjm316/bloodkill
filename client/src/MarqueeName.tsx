import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

// 座位与终局名单共用：只对实际溢出的昵称启动跑马灯，尺寸变化后重新测量。
export function MarqueeName({ name, children }: { name: string; children?: ReactNode }) {
  const viewport = useRef<HTMLSpanElement>(null);
  const text = useRef<HTMLSpanElement>(null);
  const [distance, setDistance] = useState(0);

  useLayoutEffect(() => {
    const measure = () => {
      const width = viewport.current?.clientWidth ?? 0;
      setDistance(width > 0 ? Math.max(0, (text.current?.scrollWidth ?? 0) - width) : 0);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    if (viewport.current) observer?.observe(viewport.current);
    if (text.current) observer?.observe(text.current);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [name, children]);

  return <span
    ref={viewport}
    className={`marquee-name${distance > 0 ? " is-overflowing" : ""}`}
    title={name}
    tabIndex={distance > 0 ? 0 : undefined}
    onBlur={(event) => { event.currentTarget.scrollLeft = 0; }}
    style={{ "--marquee-distance": `${distance}px`, "--marquee-duration": `${Math.max(5, distance / 30 + 3)}s` } as CSSProperties}
  >
    <span ref={text} className="marquee-name-text">{name}{children}</span>
  </span>;
}
