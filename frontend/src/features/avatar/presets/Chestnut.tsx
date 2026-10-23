import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';
import { Face } from './face';

export function Chestnut({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#CBD2DB" />
      <Suit
        neck="#D9A585"
        jacket="#2B323C"
        lapel="#20262E"
        shirt="#EEF1F4"
        collar
        tie="#34435A"
      />
      <Face skin="#E6B897" shade="#D6A584" deep="#C9947A" />
      <path
        d="M72 92 C66 58 86 40 112 40 C138 40 154 58 148 92 C146 80 143 72 138 66 C126 62 112 62 100 60 C92 66 86 64 80 70 C76 76 74 84 72 92Z"
        fill="#3A2A24"
      />
      <path
        d="M84 87 L100 85"
        stroke="#3A2A24"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M120 85 L136 87"
        stroke="#3A2A24"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <rect
        x="81"
        y="91"
        width="24"
        height="15"
        rx="3"
        fill="#fff"
        fillOpacity=".12"
        stroke="#3B3F46"
        strokeWidth="1.6"
      />
      <rect
        x="115"
        y="91"
        width="24"
        height="15"
        rx="3"
        fill="#fff"
        fillOpacity=".12"
        stroke="#3B3F46"
        strokeWidth="1.6"
      />
      <path d="M105 96 L115 96" stroke="#3B3F46" strokeWidth="1.6" />
      <Eyes blink={blink} y={98}>
        <path d="M87 98 Q93 93.6 99 98 Q93 101 87 98Z" fill="#2A211D" />
        <path d="M121 98 Q127 93.6 133 98 Q127 101 121 98Z" fill="#2A211D" />
      </Eyes>
      <path
        d="M110 104 L106 121 Q110 123 114 121"
        stroke="#B9846A"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Mouth level={mouth} y={133} color="#7E3F33">
        <path
          className="mouth"
          d="M101 132 Q110 134.5 119 132"
          stroke="#8F5244"
          strokeWidth="2.5"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
    </>
  );
}
