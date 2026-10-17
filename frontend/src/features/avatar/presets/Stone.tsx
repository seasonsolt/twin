import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';

export function Stone({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#D3DCE6" />
      <Suit
        neck="#B97A55"
        jacket="#2F3A48"
        lapel="#232C37"
        shirt="#DCE8F5"
        collar
        tie="#8C2F39"
      />
      <ellipse cx="54" cy="108" rx="9" ry="13" fill="#C88660" />
      <ellipse cx="166" cy="108" rx="9" ry="13" fill="#C88660" />
      <path
        d="M56 100 C56 58 80 44 110 44 C140 44 164 58 164 100 L164 120 C164 150 140 168 110 168 C80 168 56 150 56 120Z"
        fill="#D6976E"
      />
      <path
        d="M56 100 C54 60 80 42 110 42 C140 42 166 60 164 100 C160 82 152 72 140 68 C124 62 96 62 80 68 C70 72 60 82 56 100Z"
        fill="#2A2522"
      />
      <path
        d="M66 126 C70 156 90 168 110 168 C130 168 150 156 154 126 C146 142 130 150 110 150 C90 150 74 142 66 126Z"
        fill="#4A3A32"
        opacity=".35"
      />
      <path
        d="M75 92 L98 90"
        stroke="#2A2522"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <path
        d="M122 90 L145 92"
        stroke="#2A2522"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={106}>
        <ellipse cx="87" cy="106" rx="4.5" ry="5.5" fill="#1F1A18" />
        <ellipse cx="133" cy="106" rx="4.5" ry="5.5" fill="#1F1A18" />
        <circle cx="88.4" cy="104" r="1.5" fill="#fff" />
        <circle cx="134.4" cy="104" r="1.5" fill="#fff" />
      </Eyes>
      <path
        d="M106 112 Q110 124 116 122"
        stroke="#A86A47"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      <Mouth level={mouth} y={138} color="#5A2A20">
        <path
          className="mouth"
          d="M98 136 Q110 142 122 136"
          stroke="#5A2A20"
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
    </>
  );
}
