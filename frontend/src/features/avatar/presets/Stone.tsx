import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';
import { Face } from './face';

export function Stone({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#CED5DE" />
      <Suit
        neck="#A56F4D"
        jacket="#26303D"
        lapel="#1C242E"
        shirt="#E6ECF3"
        collar
        tie="#5E2A33"
      />
      <Face skin="#B9805B" shade="#A56F4D" deep="#966245" jaw="square" />
      <path
        d="M73 90 C70 58 88 44 110 44 C132 44 150 58 147 90 C145 76 140 66 132 62 C118 58 102 58 88 62 C80 66 75 76 73 90Z"
        fill="#1F1B19"
      />
      <path
        d="M75 112 C78 132 88 146 96 151 C103 156 117 156 124 151 C132 146 142 132 145 112 C142 126 134 138 122 142 C116 140 104 140 98 142 C86 138 78 126 75 112Z"
        fill="#2A211D"
        fillOpacity=".7"
      />
      <path
        d="M100 127 Q110 122 120 127 Q110 125.5 100 127Z"
        fill="#2A211D"
        fillOpacity=".7"
      />
      <path
        d="M83 87 L100 85"
        stroke="#1F1B19"
        strokeWidth="3.2"
        strokeLinecap="round"
      />
      <path
        d="M120 85 L137 87"
        stroke="#1F1B19"
        strokeWidth="3.2"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={98}>
        <path d="M87 98 Q93 93.6 99 98 Q93 101 87 98Z" fill="#1A1513" />
        <path d="M121 98 Q127 93.6 133 98 Q127 101 121 98Z" fill="#1A1513" />
      </Eyes>
      <path
        d="M110 104 L106 120 Q110 122 114 120"
        stroke="#8A5A3E"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Mouth level={mouth} y={133} color="#4E2820">
        <path
          className="mouth"
          d="M101 132 Q110 134.5 119 132"
          stroke="#5C3226"
          strokeWidth="2.6"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
    </>
  );
}
