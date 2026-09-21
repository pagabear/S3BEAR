import React from 'react'

/** Shared visual tokens for the s3BEAR console — BEAR "Carbon" ramp + emerald.
 *  Byte-identical to the rest of the BEAR Design System (websites + gatebear app). */
export const C = {
  bg: '#0C0D10',       // carbon-950
  surface: '#15171B',  // carbon-900 (panel)
  raised: '#1C1E23',   // carbon-850 (panel-2 / elevated inset)
  border: '#282C33',   // carbon-800
  text: '#ECEEF1',     // carbon-100
  muted: '#9AA0AA',    // carbon-400
  dim: '#656B75',      // carbon-500
  accent: '#10B981',   // emerald (identity green — fixed)
  accentHover: '#34D399',
  accentSoftBg: 'rgba(16,185,129,0.12)',
  accentSoftBorder: 'rgba(16,185,129,0.28)',
  warning: '#F59E0B',
  success: '#22C55E',
  danger: '#EF4444',
} as const

/** Monospace style for technical values (keys, regions, endpoints, ids). */
export const mono: React.CSSProperties = {
  fontFamily: "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
  fontVariantNumeric: 'tabular-nums',
}

/** Section-label style used above form groups and nav sections. */
export const sectionLabel: React.CSSProperties = {
  color: C.dim,
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
}

/** Provider type -> label/icon mapping is reused across pages. */
export const PROVIDER_TYPE_LABEL: Record<string, string> = {
  aws: 'AWS S3', minio: 'MinIO', ceph: 'Ceph', wasabi: 'Wasabi', custom: 'Custom',
}
