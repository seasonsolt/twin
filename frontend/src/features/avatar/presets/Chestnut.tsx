import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';

export function Chestnut({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#D5E0EE" />
      <Suit
        neck="#E4AE8C"
        jacket="#24364F"
        lapel="#1A2839"
        shirt="#F4F6F9"
        collar
        tie="#1F5FBF"
      />
      <ellipse cx="56" cy="106" rx="9" ry="13" fill="#E8B394" />
      <ellipse cx="164" cy="106" rx="9" ry="13" fill="#E8B394" />
      <ellipse cx="110" cy="104" rx="54" ry="60" fill="#F3C4A2" />
      <path
        d="M54 100 C50 52 82 36 112 38 C144 40 170 56 166 100 C162 82 154 70 140 64 C120 58 90 60 74 68 C64 76 58 88 54 100Z"
        fill="#4A2E26"
      />
      <path
        d="M76 92 L98 90"
        stroke="#4A2E26"
        strokeWidth="4"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M122 90 L144 92"
        stroke="#4A2E26"
        strokeWidth="4"
        fill="none"
        strokeLinecap="round"
      />
      <rect
        x="72"
        y="96"
        width="30"
        height="22"
        rx="6"
        fill="#fff"
        fillOpacity=".2"
        stroke="#2A2F38"
        strokeWidth="3"
      />
      <rect
        x="118"
        y="96"
        width="30"
        height="22"
        rx="6"
        fill="#fff"
        fillOpacity=".2"
        stroke="#2A2F38"
        strokeWidth="3"
      />
      <path d="M102 104 L118 104" stroke="#2A2F38" strokeWidth="3" />
      <Eyes blink={blink} y={107}>
        <ellipse cx="87" cy="107" rx="4" ry="5" fill="#2B1D18" />
        <ellipse cx="133" cy="107" rx="4" ry="5" fill="#2B1D18" />
        <circle cx="88.3" cy="105.2" r="1.3" fill="#fff" />
        <circle cx="134.3" cy="105.2" r="1.3" fill="#fff" />
      </Eyes>
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
          d="M99 139 Q110 145 121 139"
          stroke="#8E3B2E"
          strokeWidth="3.5"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
    </>
  );
}
