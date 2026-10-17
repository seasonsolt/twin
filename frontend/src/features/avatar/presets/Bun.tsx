import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';

export function Bun({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#E1E5EA" />
      <Suit
        neck="#D99A74"
        jacket="#6B7A8F"
        lapel="#56657A"
        shirt="#FFFFFF"
        collar
      />
      <circle cx="110" cy="34" r="20" fill="#2C2320" />
      <ellipse cx="58" cy="110" rx="7" ry="11" fill="#E3A57F" />
      <ellipse cx="162" cy="110" rx="7" ry="11" fill="#E3A57F" />
      <ellipse cx="110" cy="106" rx="52" ry="58" fill="#EDB48C" />
      <path
        d="M58 104 C52 58 80 44 110 44 C142 44 168 58 162 104 C156 80 138 66 104 64 C86 66 66 78 58 104Z"
        fill="#2C2320"
      />
      <path
        d="M77 96 Q87 92 98 95"
        stroke="#2C2320"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M122 95 Q133 92 143 96"
        stroke="#2C2320"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={110.25}>
        <ellipse cx="88" cy="110" rx="4.5" ry="5" fill="#2C2320" />
        <ellipse cx="132" cy="110" rx="4.5" ry="5" fill="#2C2320" />
        <circle cx="89.4" cy="108.2" r="1.4" fill="#fff" />
        <circle cx="133.4" cy="108.2" r="1.4" fill="#fff" />
      </Eyes>
      <path
        d="M108 118 Q111 124 114 122"
        stroke="#C78260"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      <Mouth level={mouth} y={138} color="#9C3B30">
        <path
          className="mouth"
          d="M99 136 Q110 143 121 136"
          stroke="#9C3B30"
          strokeWidth="3.5"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
      <circle cx="57" cy="124" r="3.5" fill="#D9DDE3" />
      <circle cx="163" cy="124" r="3.5" fill="#D9DDE3" />
    </>
  );
}
