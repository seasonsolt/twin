import type { ReactNode } from 'react';

export interface ArtProps {
  blink: boolean;
  mouth: number;
}

export function Eyes({
  blink,
  y,
  children,
}: {
  blink: boolean;
  y: number;
  children: ReactNode;
}) {
  return (
    <g
      className="eyes"
      data-eye=""
      style={{
        transformBox: 'view-box',
        transformOrigin: `110px ${y}px`,
        transform: `scaleY(${blink ? 0.1 : 1})`,
      }}
    >
      {children}
    </g>
  );
}

export function Mouth({
  level,
  y,
  color,
  children,
}: {
  level: number;
  y: number;
  color: string;
  children: ReactNode;
}) {
  return (
    <g data-mouth="" data-level={level}>
      <g visibility={level === 0 ? 'visible' : 'hidden'}>{children}</g>
      {level > 0 && (
        <>
          <ellipse
            className="mouth"
            cx="110"
            cy={y}
            rx={7 + level}
            ry={[0, 2, 4, 6.5][level]}
            fill={color}
          />
          {level === 3 && (
            <>
              <path
                d={`M105 ${y - 3.5} Q110 ${y - 1.5} 115 ${y - 3.5}`}
                fill="none"
                stroke="#F4EFE8"
                strokeWidth="2"
                strokeLinecap="round"
              />
              <ellipse cx="110" cy={y + 3.5} rx="3.5" ry="1.4" fill="#C9776A" />
            </>
          )}
        </>
      )}
    </g>
  );
}
