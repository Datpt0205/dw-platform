/**
 * The areas of Studio, one per artifact kind the running app registers: each
 * gets a menu entry in `/studio` and lends its read key to the "Studio" nav
 * item (R7.2). Empty until the first kind's spec registers that kind in
 * `ArtifactKindRegistry` (tenant-config/02 steps 5 and 6) and adds its area
 * here in the same change, with `readKey` the read key its registry entry
 * declares (tenant-config:R2.15).
 *
 * `readKey` is a string literal on purpose: the permission-catalogue coverage
 * test (`test_permission_catalogue.py`, `scan_configs`) reads it from this file
 * the way it reads `scope` in the nav registry.
 */
export interface StudioSection {
  /** The kind's code, as `ArtifactView.kind` carries it. */
  key: string;
  href: string;
  /** The Vietnamese label, from `STUDIO_MESSAGES`. */
  label: string;
  readKey: string;
}

export const STUDIO_SECTIONS: StudioSection[] = [];
