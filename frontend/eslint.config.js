import tseslint from 'typescript-eslint';
import hooks from 'eslint-plugin-react-hooks';
import ui from './eslint/twin-ui.js';

export default tseslint.config(
  { ignores: ['node_modules/**', 'e2e/.results/**'] },
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { 'react-hooks': hooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/components/effects/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              regex: '(^|/)reactbits(/|$)',
              message:
                'Import application wrappers from components/effects, not React Bits sources.',
            },
          ],
        },
      ],
    },
  },
  // Pages and features build their look from components/ui only (see AGENTS.md「前端规则」). No inline
  // eslint-disable: an exception is a folder listed below, with its reason.
  {
    files: ['src/**/*.tsx'],
    ignores: [
      // The design system itself: the only place that turns tokens into classes.
      'src/components/ui/**',
      // Motion primitives (Pressable is the button underneath Button) and the React Bits wrappers and sources.
      'src/components/motion/**',
      'src/components/effects/**',
      'src/components/reactbits/**',
      // Illustrated and 3D avatars: SVG art, measured stage sizes and colours per preset.
      'src/features/avatar/**',
      // The memory graph draws on a canvas with per-dimension colours and a dark theme of its own.
      'src/features/profile/graph/**',
      // The chat stage: header height, portrait size and breathing scale follow springs and the voice level frame by
      // frame (motion values in style), on a round portrait stage of its own. Its rings are PresenceRing.
      'src/features/chat/ChatStage.tsx',
      'src/test/**',
    ],
    linterOptions: { noInlineConfig: true },
    plugins: { 'twin-ui': ui },
    rules: {
      'twin-ui/no-raw-controls': 'error',
      'twin-ui/no-free-style': 'error',
    },
  },
);
