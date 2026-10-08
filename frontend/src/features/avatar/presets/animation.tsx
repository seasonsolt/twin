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
            rx={10 + level}
            ry={[0, 3, 6, 10][level]}
            fill={color}
          />
          {level === 3 && (
            <>
              <path
                d={`M103 ${y - 5} Q110 ${y - 2} 117 ${y - 5}`}
                fill="none"
                stroke="#FFF8EE"
                strokeWidth="3"
                strokeLinecap="round"
              />
              <ellipse cx="110" cy={y + 5} rx="5" ry="2" fill="#E8826B" />
            </>
          )}
        </>
      )}
    </g>
  );
}
