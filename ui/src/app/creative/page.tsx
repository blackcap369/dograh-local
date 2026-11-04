import { redirect } from "next/navigation";

/**
 * /creative is a mode, not a destination. Land operators on the dashboard the
 * same way /overview anchors organization mode.
 */
export default function CreativeIndexPage() {
  redirect("/creative/dashboard");
}
