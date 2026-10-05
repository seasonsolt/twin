# React Bits — application-only vendored components

- Project: https://reactbits.dev / https://github.com/DavidHDev/react-bits
- Install date: 2026-10-05
- Method: `pnpm -C frontend dlx shadcn@latest add --cwd frontend @react-bits/<Name>-TS-TW --yes` (shadcn 4.21.2).
- Source revision: `ca44b3f9ee180676a06d7de8ec6bea84cddff85b`.
  All seven registry files were byte-for-byte checked against `src/ts-tailwind/` at this commit before the one marked lint fix.
- Registry: `https://reactbits.dev/r/{Name}-TS-TW.json`.
- Components: BlurText, ShinyText, CountUp (`TextAnimations/`); AnimatedList, SpotlightCard, Stepper (`Components/`); AnimatedContent (`Animations/`). Each upstream file is `{category}/{Name}/{Name}.tsx`.
- Local change: Stepper's empty CheckIconProps interface becomes an equivalent type alias (marked inline). No other source changes; upstream formatting is preserved via Prettier ignore, ESLint still checks all sources.
- Use only inside this application. Do not sell, sublicense, or redistribute these components as a library or standalone bundle.

## Licence (upstream LICENSE.md, verbatim)

MIT + Commons Clause License Condition v1.0

Copyright (c) 2026 David Haz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, and distribute the Software **as part of an application, website, or product**, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

## Commons Clause Restriction

You may use this Software, including for any commercial purpose, **so long as you do not sell, sublicense, or redistribute the components themselves-whether alone, in a bundle, or as a ported version.**

## No Warranty

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
