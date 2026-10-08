import { useEffect, useState } from 'react';

export function usePortrait(url?: string) {
  const [loaded, setLoaded] = useState<{
    url: string;
    image: HTMLImageElement;
  } | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    const image = new Image();
    image.onload = () => {
      if (alive) setLoaded({ url, image });
    };
    image.src = url;
    return () => {
      alive = false;
    };
  }, [url]);
  return loaded && loaded.url === url ? loaded.image : null;
}
export function paintTwinPortrait(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  name: string,
  color: string,
  ink: string,
  image: HTMLImageElement | null,
) {
  ctx.save();
  ctx.shadowColor = color;
  ctx.shadowBlur = radius * 0.45;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.save();
  ctx.beginPath();
  ctx.arc(x, y, radius * 0.88, 0, Math.PI * 2);
  ctx.clip();
  if (image) {
    const edge = Math.min(image.width, image.height);
    ctx.drawImage(
      image,
      (image.width - edge) / 2,
      (image.height - edge) / 2,
      edge,
      edge,
      x - radius,
      y - radius,
      radius * 2,
      radius * 2,
    );
  } else {
    ctx.fillStyle = ink;
    ctx.font = `600 ${radius}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText([...name.trim()][0] || '你', x, y + radius * 0.06);
  }
  ctx.restore();
  ctx.beginPath();
  ctx.arc(x, y, radius * 0.98, 0, Math.PI * 2);
  ctx.lineWidth = radius * 0.07;
  ctx.strokeStyle = color;
  ctx.stroke();
  ctx.restore();
}
