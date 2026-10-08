import { Eyes, Mouth, type ArtProps } from './animation';

export function Wave({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#FFD9C2" />
      <circle cx="40" cy="48" r="20" fill="#FFEBDD" />
      <path
        d="M48 120 C36 160 44 196 60 220 L160 220 C176 196 184 160 172 120Z"
        fill="#A4442F"
      />
      <path
        d="M34 220 C38 176 72 162 110 162 C148 162 182 176 186 220Z"
        fill="#2F8C83"
      />
      <path d="M92 162 Q110 184 128 162" fill="#F2BC98" />
      <path
        d="M97 140 L123 140 L125 166 C115 172 105 172 95 166Z"
        fill="#E9A985"
      />
      <ellipse cx="110" cy="104" rx="52" ry="60" fill="#F6C8A4" />
      <path
        d="M58 112 C48 54 80 32 112 34 C150 36 174 62 162 114 C156 92 150 76 138 66 C120 80 94 84 70 80 C64 90 60 100 58 112Z"
        fill="#B8523A"
      />
      <path
        d="M60 80 C42 96 46 128 40 150 C54 140 60 124 62 110Z"
        fill="#B8523A"
      />
      <path
        d="M160 80 C178 96 174 128 180 150 C166 140 160 124 158 110Z"
        fill="#B8523A"
      />
      <path
        d="M138 66 C130 58 120 56 112 60"
        stroke="#D9765B"
        strokeWidth="4"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M76 94 Q87 89 98 94"
        stroke="#7A2E21"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M122 94 Q133 89 144 94"
        stroke="#7A2E21"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={110}>
        <ellipse cx="87" cy="110" rx="5" ry="6.5" fill="#2B1D18" />
        <ellipse cx="133" cy="110" rx="5" ry="6.5" fill="#2B1D18" />
        <circle cx="88.8" cy="107.6" r="1.8" fill="#fff" />
        <circle cx="134.8" cy="107.6" r="1.8" fill="#fff" />
      </Eyes>
      <path
        d="M80 104 L76 101 M140 104 L144 101"
        stroke="#2B1D18"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="76" cy="128" r="10" fill="#EE7F6C" opacity=".38" />
      <circle cx="144" cy="128" r="10" fill="#EE7F6C" opacity=".38" />
      <path
        d="M108 120 Q111 127 114 125"
        stroke="#D28A66"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      <Mouth level={mouth} y={140.25} color="#C2473E">
        <path
          className="mouth"
          d="M99 138 Q110 147 121 138 Q110 142 99 138Z"
          fill="#C2473E"
          stroke="#C2473E"
          strokeWidth="3"
          strokeLinejoin="round"
        />
      </Mouth>
      <circle cx="58" cy="128" r="4" fill="#F2C14E" />
      <circle cx="162" cy="128" r="4" fill="#F2C14E" />
    </>
  );
}
