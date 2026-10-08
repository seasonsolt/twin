import { Eyes, Mouth, type ArtProps } from './animation';

export function Bun({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#F7DF8E" />
      <circle cx="182" cy="176" r="30" fill="#FBEBB8" />
      <path
        d="M32 220 C36 174 70 160 110 160 C150 160 184 174 188 220Z"
        fill="#7C8A4A"
      />
      <path d="M96 160 L110 182 L124 160Z" fill="#F4EBD6" />
      <path
        d="M97 140 L123 140 L125 164 C115 170 105 170 95 164Z"
        fill="#D99A74"
      />
      <circle cx="110" cy="30" r="22" fill="#2C2320" />
      <ellipse cx="110" cy="106" rx="52" ry="58" fill="#EDB48C" />
      <path
        d="M58 104 C52 58 80 42 110 42 C142 42 168 58 162 104 C154 78 136 64 110 62 C86 64 66 76 58 104Z"
        fill="#2C2320"
      />
      <path
        d="M84 52 Q110 44 136 52"
        stroke="#E46A4E"
        strokeWidth="5"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M76 96 Q87 92 98 96"
        stroke="#2C2320"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M122 96 Q133 92 144 96"
        stroke="#2C2320"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={110.25}>
        <path
          d="M80 112 Q87 105 94 112"
          stroke="#2C2320"
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
        />
        <path
          d="M126 112 Q133 105 140 112"
          stroke="#2C2320"
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
        />
      </Eyes>
      <circle cx="76" cy="126" r="10" fill="#E8735A" opacity=".4" />
      <circle cx="144" cy="126" r="10" fill="#E8735A" opacity=".4" />
      <path
        d="M108 118 Q111 124 114 122"
        stroke="#C78260"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      <Mouth level={mouth} y={138} color="#9C3B30">
        <path className="mouth" d="M97 134 Q110 150 123 134Z" fill="#9C3B30" />
        <path
          d="M102 136 Q110 140 118 136"
          stroke="#fff"
          strokeWidth="3"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
      <ellipse cx="58" cy="110" rx="7" ry="11" fill="#E3A57F" />
      <ellipse cx="162" cy="110" rx="7" ry="11" fill="#E3A57F" />
      <circle cx="57" cy="126" r="5" fill="#E46A4E" />
      <circle cx="163" cy="126" r="5" fill="#E46A4E" />
    </>
  );
}
