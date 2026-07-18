/// <reference types="vite/client" />

/**
 * Build-time constant injected by vite.config.ts `define` (decision 1/3):
 * the default gateway URL baked into the bundle when the integrator's
 * `<script>` tag does not supply `data-api-base`. Always a public URL,
 * never a secret.
 */
declare const __WIDGET_API_BASE__: string;
