import React from 'react'
import ReactDOM from 'react-dom/client'
import { MsalProvider } from '@azure/msal-react'
import { ConfigProvider, theme } from 'antd'
import { msalInstance } from './api/msal'
import App from './App'
import 'antd/dist/reset.css'
// BEAR Design System — browser-surface theming (selection, caret, scrollbars,
// focus ring, tabular numerals) + the emerald brand slot. Loaded after Ant's
// reset so it wins.
import './styles/bear/theme.css'
import './styles/bear/theme.s3bear.css'

// BEAR "Carbon" neutrals + emerald accent (dark instantiation — the app is
// dark-only). Byte-identical to the rest of the BEAR system.
const BG        = '#0C0D10'  // carbon-950 — page / layout ground
const PANEL     = '#15171B'  // carbon-900 — panels, cards, sider
const PANEL_2   = '#1C1E23'  // carbon-850 — elevated inset (dropdowns/inputs)
const VOID      = '#08090B'  // carbon-void — tooltips / deepest
const BORDER    = '#282C33'  // carbon-800
const BORDER_2  = '#1C1E23'  // carbon-850 (hairline)
const PRIMARY   = '#10B981'  // emerald — the identity green (fixed)
const PRIMARY_H = '#34D399'  // emerald-400 (hover/press in dark)
const TEXT      = '#ECEEF1'  // carbon-100
const MUTED     = '#9AA0AA'  // carbon-400
const SUBTLE    = '#656B75'  // carbon-500
const INK       = '#0C0D10'  // ink label on emerald fill (AA-safe ~7.8:1)

// Flat by default; only true overlays lift.
const SHADOW_OVERLAY = '0 8px 24px -6px rgba(0,0,0,0.60), 0 2px 6px rgba(0,0,0,0.50)'
const SHADOW_MODAL   = '0 24px 60px -18px rgba(0,0,0,0.70), 0 4px 12px rgba(0,0,0,0.55)'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MsalProvider instance={msalInstance}>
      <ConfigProvider
        componentSize="large"
        theme={{
          algorithm: theme.darkAlgorithm,
          token: {
            colorPrimary: PRIMARY,
            colorBgBase: PANEL,
            colorBgContainer: PANEL,
            colorBgElevated: PANEL_2,
            colorBgLayout: BG,
            colorBgSpotlight: VOID,
            colorText: TEXT,
            colorTextSecondary: MUTED,
            colorTextTertiary: SUBTLE,
            colorTextPlaceholder: SUBTLE,
            colorBorder: BORDER,
            colorBorderSecondary: BORDER_2,
            // Sharp system: controls take a 4px chamfer; surfaces go square
            // via the component overrides below.
            borderRadius: 4,
            borderRadiusLG: 4,
            borderRadiusSM: 4,
            borderRadiusXS: 2,
            fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
            fontFamilyCode: "'JetBrains Mono', 'SFMono-Regular', Menlo, Monaco, monospace",
            fontSize: 15,
            // Shared semantics (identical across brands). info is sky, NOT brand.
            colorSuccess: '#22C55E',
            colorWarning: '#F59E0B',
            colorError: '#EF4444',
            colorInfo: '#0EA5E9',
            colorLink: PRIMARY_H,
            colorLinkHover: '#6EE7B7',
            // Flat by default; overlays lift with our elevation.
            boxShadow: SHADOW_OVERLAY,
            boxShadowSecondary: SHADOW_MODAL,
            wireframe: false,
          },
          components: {
            Layout: {
              siderBg: PANEL,
              headerBg: BG,
              bodyBg: BG,
            },
            Menu: {
              darkItemBg: 'transparent',
              darkSubMenuItemBg: 'transparent',
              darkItemSelectedBg: 'rgba(16,185,129,0.16)',
              darkItemSelectedColor: PRIMARY_H,
              darkItemHoverBg: 'rgba(16,185,129,0.08)',
              darkItemHoverColor: TEXT,
              itemBorderRadius: 4,
              itemHeight: 44,
              fontSize: 15,
            },
            // Surfaces go square (0); controls keep the 4px chamfer above.
            Card: {
              borderRadiusLG: 0,
              colorBgContainer: PANEL,
              colorBorderSecondary: BORDER,
              boxShadowTertiary: 'none',
            },
            Table: {
              borderRadiusLG: 0,
              colorBgContainer: 'transparent',
              headerBg: 'transparent',
              rowHoverBg: 'rgba(16,185,129,0.08)',
              rowSelectedBg: 'rgba(16,185,129,0.14)',
              borderColor: BORDER_2,
              cellPaddingBlock: 14,
            },
            Modal: {
              borderRadiusLG: 0,
              contentBg: PANEL,
              headerBg: PANEL,
            },
            Drawer: {
              colorBgElevated: PANEL,
            },
            Input: {
              borderRadius: 4,
              colorBgContainer: PANEL_2,
              colorBorder: BORDER,
              colorText: TEXT,
              activeBorderColor: PRIMARY,
              activeShadow: '0 0 0 2px rgba(52,211,153,0.35)',
            },
            Select: {
              borderRadius: 4,
              colorBgContainer: PANEL_2,
              colorBorder: BORDER,
            },
            // Ink-on-emerald label — the s3BEAR signature; fixes white-on-#10B981
            // (which fails AA).
            Button: {
              borderRadius: 4,
              primaryColor: INK,
            },
            Tag: {
              borderRadiusSM: 4,
            },
            Tooltip: {
              colorBgSpotlight: VOID,
            },
            Progress: {
              defaultColor: PRIMARY,
            },
            Statistic: {
              contentFontSize: 24,
              fontFamily: "'JetBrains Mono', 'SFMono-Regular', Menlo, monospace",
            },
          },
        }}
      >
        <App />
      </ConfigProvider>
    </MsalProvider>
  </React.StrictMode>,
)
