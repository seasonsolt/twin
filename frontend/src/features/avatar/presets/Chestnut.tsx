import { Eyes, Mouth, type ArtProps } from './animation';

export function Chestnut({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#F6C9A8" />
      <circle cx="178" cy="40" r="26" fill="#FBE3CF" />
      <path
        d="M30 220 C34 172 70 158 110 158 C150 158 186 172 190 220Z"
        fill="#E2A33B"
      />
      <path
        d="M84 162 C92 178 128 178 136 162 L132 158 C124 168 96 168 88 158Z"
        fill="#C9862A"
      />
      <path
        d="M96 140 L124 140 L126 166 C116 172 104 172 94 166Z"
        fill="#E9A985"
      />
      <ellipse cx="56" cy="106" rx="9" ry="13" fill="#EDB494" />
      <ellipse cx="164" cy="106" rx="9" ry="13" fill="#EDB494" />
      <ellipse cx="110" cy="104" rx="54" ry="60" fill="#F3C4A2" />
      <path
        d="M54 102 C48 50 82 34 112 36 C146 38 172 58 166 102 C158 80 146 70 126 66 C110 76 86 78 66 74 C60 82 56 92 54 102Z"
        fill="#4A2E26"
      />
      <path
        d="M74 92 Q86 86 98 92"
        stroke="#4A2E26"
        strokeWidth="4"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M122 92 Q134 86 146 92"
        stroke="#4A2E26"
        strokeWidth="4"
        fill="none"
        strokeLinecap="round"
      />
      <circle
        cx="87"
        cy="108"
        r="15"
        fill="#fff"
        fillOpacity=".25"
        stroke="#3A2A24"
        strokeWidth="3.5"
      />
      <circle
        cx="133"
        cy="108"
        r="15"
        fill="#fff"
        fillOpacity=".25"
        stroke="#3A2A24"
        strokeWidth="3.5"
      />
      <path
        d="M102 107 Q110 102 118 107"
        stroke="#3A2A24"
        strokeWidth="3.5"
        fill="none"
      />
      <Eyes blink={blink} y={109}>
        <ellipse cx="87" cy="109" rx="4.5" ry="5.5" fill="#2B1D18" />
        <ellipse cx="133" cy="109" rx="4.5" ry="5.5" fill="#2B1D18" />
        <circle cx="88.5" cy="107" r="1.5" fill="#fff" />
        <circle cx="134.5" cy="107" r="1.5" fill="#fff" />
      </Eyes>
      <circle cx="76" cy="128" r="9" fill="#E8826B" opacity=".35" />
      <circle cx="144" cy="128" r="9" fill="#E8826B" opacity=".35" />
      <path
        d="M107 118 Q110 126 114 124"
        stroke="#C98664"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      <Mouth level={mouth} y={140.5} color="#8E3B2E">
        <path
          className="mouth"
          d="M98 138 Q110 148 122 138"
          stroke="#8E3B2E"
          strokeWidth="3.5"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
    </>
  );
}
