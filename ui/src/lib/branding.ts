/**
 * White-label branding switches, read once at module load.
 *
 * `NEXT_PUBLIC_WHITELABEL=true` turns off every Dograh cloud surface in the
 * operator-facing UI -- the GitHub star badge, the Slack link, the "Hire an
 * Expert" lead form, and the release nags -- so an agency can run the platform
 * in front of its own clients without advertising the upstream project.
 * `NEXT_PUBLIC_APP_NAME` renames the few places the product name is rendered
 * as text (browser tab, mobile header); the logo itself stays an asset the
 * deployment replaces in /public.
 *
 * NEXT_PUBLIC_* variables are inlined at build time, so changing them requires
 * a dev-server restart or rebuild -- intentional for a deployment-level switch.
 */
export const IS_WHITELABEL = process.env.NEXT_PUBLIC_WHITELABEL === "true";

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME?.trim() || "Dograh";
