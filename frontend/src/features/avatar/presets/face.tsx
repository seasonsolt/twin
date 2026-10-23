/** The face of each jaw, with the shade that turns its right side away from the light. */
const JAWS = {
  firm: {
    half: 36,
    face: 'M74 94 C74 64 90 50 110 50 C130 50 146 64 146 94 C146 122 138 140 124 150 C117 155 103 155 96 150 C82 140 74 122 74 94Z',
    shade:
      'M128 56 C140 64 146 78 146 94 C146 122 138 140 124 150 C117 155 110 155 110 155 C124 146 136 128 138 104 C139 84 136 68 128 56Z',
  },
  soft: {
    half: 34,
    face: 'M76 94 C76 64 91 52 110 52 C129 52 144 64 144 94 C144 120 137 138 124 148 C117 153 103 153 96 148 C83 138 76 120 76 94Z',
    shade:
      'M127 58 C138 66 144 80 144 94 C144 120 137 138 124 148 C117 153 110 153 110 153 C123 144 134 127 136 104 C137 85 134 70 127 58Z',
  },
  square: {
    half: 37,
    face: 'M73 94 C73 62 90 50 110 50 C130 50 147 62 147 94 C147 122 141 138 128 149 C119 156 101 156 92 149 C79 138 73 122 73 94Z',
    shade:
      'M129 56 C141 64 147 78 147 94 C147 122 141 138 128 149 C119 156 110 156 110 156 C125 147 137 129 139 104 C140 84 137 68 129 56Z',
  },
};

/** The shared head of the business illustrations: the ears, the face with its jaw and its shaded side. Drawn after
 * the outfit and before the hair; ``deep`` colours the ear on the shaded side. */
export function Face({
  skin,
  shade,
  deep,
  jaw = 'firm',
}: {
  skin: string;
  shade: string;
  deep: string;
  jaw?: keyof typeof JAWS;
}) {
  const { half, face, shade: side } = JAWS[jaw];
  const left = 110 - half;
  const right = 110 + half;
  return (
    <>
      <path
        d={`M${left - 1} 98 C${left - 5} 96 ${left - 8} 102 ${left - 6} 110 C${left - 4} 116 ${left} 118 ${left + 2} 116Z`}
        fill={shade}
      />
      <path
        d={`M${right + 1} 98 C${right + 5} 96 ${right + 8} 102 ${right + 6} 110 C${right + 4} 116 ${right} 118 ${right - 2} 116Z`}
        fill={deep}
      />
      <path d={face} fill={skin} />
      <path d={side} fill={shade} />
    </>
  );
}
