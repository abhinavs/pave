/** @type {import('tailwindcss').Config} */
//
// Theme is a thin alias layer over the CSS custom properties in
// static/css/source.css. Adding a new colour or radius means defining it
// in source.css first and then exposing it here - never the other way
// around. The two stay in lockstep so a class like `bg-primary` resolves
// to the same value the prose CSS uses.
module.exports = {
  content: ["./templates/**/*.html", "./app/**/*.py"],
  darkMode: ["selector", '[data-theme="dark"]'],
  // The component gallery builds swatch class names at render time
  // (bg-primary-500, bg-secondary-300, bg-tertiary-100, ...). Tailwind's
  // static content scan can't see those, so they need an explicit
  // safelist or the swatches render blank.
  safelist: [
    {
      pattern:
        /bg-(primary|secondary|tertiary)-(0|50|100|200|300|400|500|600|700|800|900|950)/,
    },
  ],
  theme: {
    extend: {
      colors: {
        // Primitive scales, exposed in case a template needs a specific
        // step rather than a semantic role.
        primary: {
          50: "var(--color-primary-50)",
          100: "var(--color-primary-100)",
          200: "var(--color-primary-200)",
          300: "var(--color-primary-300)",
          400: "var(--color-primary-400)",
          500: "var(--color-primary-500)",
          600: "var(--color-primary-600)",
          700: "var(--color-primary-700)",
          800: "var(--color-primary-800)",
          900: "var(--color-primary-900)",
          950: "var(--color-primary-950)",
          // The bare class `bg-primary` resolves to the semantic action
          // colour, which is what the component library expects.
          DEFAULT: "var(--color-primary)",
          foreground: "var(--color-primary-foreground)",
        },
        secondary: {
          50: "var(--color-secondary-50)",
          100: "var(--color-secondary-100)",
          200: "var(--color-secondary-200)",
          300: "var(--color-secondary-300)",
          400: "var(--color-secondary-400)",
          500: "var(--color-secondary-500)",
          600: "var(--color-secondary-600)",
          700: "var(--color-secondary-700)",
          800: "var(--color-secondary-800)",
          900: "var(--color-secondary-900)",
          950: "var(--color-secondary-950)",
          DEFAULT: "var(--color-secondary)",
          foreground: "var(--color-secondary-foreground)",
        },
        tertiary: {
          0: "var(--color-tertiary-0)",
          50: "var(--color-tertiary-50)",
          100: "var(--color-tertiary-100)",
          200: "var(--color-tertiary-200)",
          300: "var(--color-tertiary-300)",
          400: "var(--color-tertiary-400)",
          500: "var(--color-tertiary-500)",
          600: "var(--color-tertiary-600)",
          700: "var(--color-tertiary-700)",
          800: "var(--color-tertiary-800)",
          900: "var(--color-tertiary-900)",
          950: "var(--color-tertiary-950)",
          DEFAULT: "var(--color-tertiary)",
          foreground: "var(--color-tertiary-foreground)",
        },
        neutral: {
          0: "var(--color-neutral-0)",
          50: "var(--color-neutral-50)",
          100: "var(--color-neutral-100)",
          200: "var(--color-neutral-200)",
          300: "var(--color-neutral-300)",
          400: "var(--color-neutral-400)",
          500: "var(--color-neutral-500)",
          600: "var(--color-neutral-600)",
          700: "var(--color-neutral-700)",
          800: "var(--color-neutral-800)",
          900: "var(--color-neutral-900)",
          950: "var(--color-neutral-950)",
        },

        // Semantic roles. Templates should prefer these over the
        // primitive scales - that is how light/dark stay in sync.
        background: "var(--color-background)",
        foreground: "var(--color-foreground)",
        surface: {
          DEFAULT: "var(--color-surface)",
          muted: "var(--color-surface-muted)",
          subtle: "var(--color-surface-subtle)",
          elevated: "var(--color-surface-elevated)",
        },
        card: {
          DEFAULT: "var(--color-card)",
          foreground: "var(--color-card-foreground)",
        },
        popover: {
          DEFAULT: "var(--color-popover)",
          foreground: "var(--color-popover-foreground)",
        },
        muted: {
          DEFAULT: "var(--color-muted)",
          foreground: "var(--color-muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--color-accent)",
          foreground: "var(--color-accent-foreground)",
        },
        link: {
          DEFAULT: "var(--color-link)",
          hover: "var(--color-link-hover)",
        },
        destructive: {
          DEFAULT: "var(--color-destructive)",
          foreground: "var(--color-destructive-foreground)",
          ink: "var(--color-destructive-ink)",
        },
        border: {
          DEFAULT: "var(--color-border)",
          strong: "var(--color-border-strong)",
        },
        input: "var(--color-input)",
        ring: "var(--color-ring)",

        // Status (badges, alerts, swatches). The base name is the
        // solid hue used for fills and dots; the *-ink variant is the
        // theme-aware ink that survives sitting as text or as an icon
        // on a near-white background in the light theme.
        error: {
          DEFAULT: "var(--color-destructive)",
          ink: "var(--color-destructive-ink)",
        },
        warning: {
          DEFAULT: "var(--color-warning-500)",
          ink: "var(--color-warning-ink)",
        },
        success: {
          DEFAULT: "var(--color-success-500)",
          ink: "var(--color-success-ink)",
        },
        info: "var(--color-primary-500)",
      },
      borderRadius: {
        xs: "var(--radius-xs)",
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
      },
      boxShadow: {
        xs: "var(--shadow-xs)",
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        xl: "var(--shadow-xl)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        serif: ["var(--font-serif)"],
        mono: ["var(--font-mono)"],
      },
    },
  },
  plugins: [],
};
