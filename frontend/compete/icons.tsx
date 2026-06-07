/* MEFAI · BNB HACK sub-site icon set.
   Every glyph is hand-drawn SVG (no icon library, no emoji, no external
   assets). Stroke icons inherit currentColor and a 24x24 viewBox so they
   align on any baseline. Pass `size` to scale, `style`/`className` to theme. */

import type { CSSProperties, ReactNode } from 'react'

type IconProps = { size?: number; color?: string; style?: CSSProperties; className?: string; strokeWidth?: number }

function S({ size = 20, color = 'currentColor', style, className, strokeWidth = 1.7, children }:
  IconProps & { children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
      style={style} className={className} aria-hidden="true">
      {children}
    </svg>
  )
}

/* ─────────── chrome ─────────── */
export const IconMenu = (p: IconProps) => <S {...p}><path d="M3 6h18M3 12h18M3 18h18" /></S>
export const IconClose = (p: IconProps) => <S {...p}><path d="M5 5l14 14M19 5L5 19" /></S>
export const IconPalette = (p: IconProps) => <S {...p}>
  <path d="M12 3a9 9 0 1 0 0 18c1.2 0 1.8-.9 1.8-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-.9.7-1.6 1.6-1.6H17a4 4 0 0 0 4-4c0-4.4-4-8.2-9-8.2Z" />
  <circle cx="7.5" cy="11" r="1" fill="currentColor" stroke="none" />
  <circle cx="10" cy="7.5" r="1" fill="currentColor" stroke="none" />
  <circle cx="14.5" cy="7.5" r="1" fill="currentColor" stroke="none" />
  <circle cx="17" cy="11" r="1" fill="currentColor" stroke="none" />
</S>
export const IconType = (p: IconProps) => <S {...p}><path d="M5 6h14M5 6v-.5M19 6v-.5M12 6v13M9.5 19h5" /></S>
export const IconLang = (p: IconProps) => <S {...p}><path d="M3.5 15l3.2-8 3.2 8M4.6 12.4h4.2" /><path d="M13 9h7M16.5 9v1.4M19 11c-.5 2.3-2 4.2-4 5.6M14.5 12.2c.7 1.9 2.2 3.4 4.2 4.4" /></S>
export const IconArrow = (p: IconProps) => <S {...p}><path d="M5 12h13M13 6l6 6-6 6" /></S>
export const IconCode = (p: IconProps) => <S {...p}><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16" /></S>
export const IconStar = (p: IconProps) => <S {...p}><path d="M12 3.5l2.6 5.3 5.9.85-4.25 4.15 1 5.85L12 16.9l-5.25 2.75 1-5.85L3.5 9.65l5.9-.85L12 3.5Z" /></S>
export const IconCheck = (p: IconProps) => <S {...p}><path d="M5 12.5l4.5 4.5L19 6.5" /></S>
export const IconExternal = (p: IconProps) => <S {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></S>
export const IconSend = (p: IconProps) => <S {...p}><path d="M21 4L3 11l7 2.5L13 21l8-17ZM10 13.5L21 4" /></S>
export const IconChevron = (p: IconProps) => <S {...p}><path d="M9 6l6 6-6 6" /></S>
export const IconCaret = ({ dir = 'up', ...p }: IconProps & { dir?: 'up' | 'down' }) =>
  <S {...p}>{dir === 'up' ? <path d="M6 15l6-6 6 6" /> : <path d="M6 9l6 6 6-6" />}</S>
export const IconAlert = (p: IconProps) => <S {...p}><path d="M12 3l9 16H3l9-16Z" /><path d="M12 10v4M12 17h.01" /></S>

/* ─────────── feature glyphs ─────────── */
export const IconShield = (p: IconProps) => <S {...p}><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3Z" /><path d="M9 12l2 2 4-4" /></S>
export const IconLock = (p: IconProps) => <S {...p}><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></S>
export const IconScale = (p: IconProps) => <S {...p}><path d="M12 4v16M7 20h10M6 7h12M6 7l-3 6h6l-3-6Zm12 0l-3 6h6l-3-6Z" /></S>
export const IconLayers = (p: IconProps) => <S {...p}><path d="M12 3l9 5-9 5-9-5 9-5Z" /><path d="M3 13l9 5 9-5M3 17l9 5 9-5" /></S>
export const IconRadar = (p: IconProps) => <S {...p}><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4.5" /><path d="M12 12l6-4" /><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" /></S>
export const IconBolt = (p: IconProps) => <S {...p}><path d="M13 3L5 13h5l-1 8 8-11h-5l1-7Z" /></S>
export const IconChart = (p: IconProps) => <S {...p}><path d="M4 4v16h16" /><path d="M7 14l3-4 3 3 4-6" /></S>
export const IconBot = (p: IconProps) => <S {...p}><rect x="5" y="8" width="14" height="11" rx="3" /><path d="M12 8V5M9 3.5h6" /><circle cx="9.5" cy="13" r="1.1" fill="currentColor" stroke="none" /><circle cx="14.5" cy="13" r="1.1" fill="currentColor" stroke="none" /><path d="M9.5 16h5" /></S>
export const IconLink = (p: IconProps) => <S {...p}><path d="M9 15l6-6" /><path d="M10.5 6.5l1.5-1.5a4 4 0 0 1 5.6 5.6L16 12.2M8 11.8l-1.6 1.6a4 4 0 0 0 5.6 5.6l1.5-1.5" /></S>
export const IconKey = (p: IconProps) => <S {...p}><circle cx="8" cy="8" r="4" /><path d="M11 11l8 8M16 16l2-2M18 18l2-2" /></S>
export const IconPulse = (p: IconProps) => <S {...p}><path d="M3 12h4l2-6 4 14 2-8h6" /></S>
export const IconWallet = (p: IconProps) => <S {...p}><rect x="3" y="6" width="18" height="13" rx="2.5" /><path d="M3 9h18M16 13h2" /></S>
export const IconDocs = (p: IconProps) => <S {...p}><path d="M6 3h8l4 4v14H6V3Z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></S>
export const IconWhale = (p: IconProps) => <S {...p}><path d="M3 12c3 0 4-4 8-4s5 4 8 4c0 4-4 6-8 6-3 0-5-1.5-6-3" /><path d="M19 12c1-1 2-1 2-3M9 11.5h.01" /></S>
export const IconGavel = (p: IconProps) => <S {...p}><path d="M14 6l4 4-5 5-4-4 5-5Z" /><path d="M9 9l-5 5M19 21H9M14.5 10.5l3-3" /></S>

/* ─────────── sponsor / stack brand glyphs (hand-drawn SVG, no assets) ───────────
   Each mark is redrawn from the real brand silhouette so it reads as the brand
   at a glance · the BNB four-diamond, the Trust shield, the CMC ring meter, the
   PancakeSwap rabbit, the ERC token hexagon, the HTTP 402 coin, the Binance
   candles, the BscScan magnifier on a block. */
function Bs({ size = 22, children }: { size?: number; children: ReactNode }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style={{ display: 'block' }}>{children}</svg>
}
/* Binance / BNB · the iconic mark = centre square + four chevron diamonds. */
export const LogoBnb = (p: { size?: number }) => <Bs {...p}>
  <path d="M12 2.2l3.05 3.05L12 8.3 8.95 5.25 12 2.2Z" />
  <path d="M5.55 8.95L8.6 12l-3.05 3.05L2.5 12l3.05-3.05Z" />
  <path d="M18.45 8.95L21.5 12l-3.05 3.05L15.4 12l3.05-3.05Z" />
  <path d="M12 15.7l3.05 3.05L12 21.8 8.95 18.75 12 15.7Z" />
  <path d="M12 8.85L15.15 12 12 15.15 8.85 12 12 8.85Z" />
</Bs>
/* Trust Wallet · the two-tone shield (vertical split). */
export const LogoTrust = (p: { size?: number }) => <Bs {...p}>
  <path d="M12 2.5l7.2 2.85a1 1 0 0 1 .63.93v5.05c0 5.05-3.2 8.45-7.5 10.27a.9.9 0 0 1-.66 0C7.37 19.78 4.17 16.38 4.17 11.33V6.28a1 1 0 0 1 .63-.93L12 2.5Z" opacity=".5" />
  <path d="M12 2.5l7.2 2.85a1 1 0 0 1 .63.93v5.05c0 5.05-3.2 8.45-7.5 10.27a.9.9 0 0 1-.33-.08V2.5Z" />
</Bs>
/* CoinMarketCap · ring with the inner radial slice that pivots from the centre. */
export const LogoCmc = (p: { size?: number }) => <Bs {...p}>
  <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
  <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M7.6 13.6c.9-1.7 1.8-1.7 2.7 0 .6 1.1 1.2 1.1 1.8 0l.5-.9c.9-1.7 1.8-1.7 2.7 0" />
  <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" d="M12 12.7v-3.1" />
</Bs>
/* PancakeSwap · the rabbit head silhouette (two ears + round face). */
export const LogoPancake = (p: { size?: number }) => <Bs {...p}>
  <path d="M8.7 8.1C8 5.4 8 3.3 9.1 3.1c1-.2 1.9 1.6 2.4 4.3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  <path d="M15.3 8.1C16 5.4 16 3.3 14.9 3.1c-1-.2-1.9 1.6-2.4 4.3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  <path d="M12 7.3c3.6 0 6.4 2.7 6.4 6.2 0 3.4-2.9 5.7-6.4 5.7s-6.4-2.3-6.4-5.7c0-3.5 2.8-6.2 6.4-6.2Z" />
  <circle cx="9.6" cy="13" r="1" fill="#fff" opacity=".85" />
  <circle cx="14.4" cy="13" r="1" fill="#fff" opacity=".85" />
</Bs>
/* ERC-8004 · token standard = hexagon with an inscribed node. */
export const LogoErc = (p: { size?: number }) => <Bs {...p}>
  <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" d="M12 2.8l7.4 4.3v8.8L12 20.2 4.6 15.9V7.1L12 2.8Z" />
  <path d="M12 7.2l4.2 2.4v4.8L12 16.8l-4.2-2.4V9.6L12 7.2Z" opacity=".9" />
</Bs>
/* x402 · HTTP 402 payment coin with the in/out transfer arrows. */
export const LogoX402 = (p: { size?: number }) => <Bs {...p}>
  <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
  <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M7.6 10h7.2l-2.4-2.3M16.4 14H9.2l2.4 2.3" />
</Bs>
/* Binance market data · the candlestick column. */
export const LogoBinanceData = (p: { size?: number }) => <Bs {...p}>
  <rect x="4.6" y="9" width="2.6" height="8.2" rx="1" /><rect x="5.4" y="5.8" width="1" height="3.2" /><rect x="5.4" y="17.2" width="1" height="2.4" />
  <rect x="10.7" y="6.4" width="2.6" height="6.6" rx="1" /><rect x="11.5" y="4" width="1" height="2.4" /><rect x="11.5" y="13" width="1" height="3" />
  <rect x="16.8" y="10.8" width="2.6" height="6.6" rx="1" /><rect x="17.6" y="7.6" width="1" height="3.2" /><rect x="17.6" y="17.4" width="1" height="2.2" />
</Bs>
/* BscScan · block explorer = magnifier over a stacked block. */
export const LogoBscScan = (p: { size?: number }) => <Bs {...p}>
  <rect x="3.5" y="3.5" width="13" height="13" rx="3" fill="none" stroke="currentColor" strokeWidth="2" />
  <rect x="6.4" y="10" width="2.1" height="3.6" rx=".6" /><rect x="9" y="7.4" width="2.1" height="6.2" rx=".6" /><rect x="11.6" y="9" width="2.1" height="4.6" rx=".6" />
  <path fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" d="M16.6 16.6L20.5 20.5" />
</Bs>
export const SPONSOR_LOGO: Record<string, (p: { size?: number }) => ReactNode> = {
  'BNB Chain': LogoBnb, 'Trust Wallet': LogoTrust, 'CoinMarketCap': LogoCmc, 'PancakeSwap': LogoPancake,
  'ERC-8004': LogoErc, 'x402': LogoX402, 'Binance Data': LogoBinanceData, 'BscScan': LogoBscScan,
}

/* ─────────── brand lockup (MEFAI logo + wordmark) ─────────── */
export function BrandLogo({ height = 26, dark = false }: { height?: number; dark?: boolean }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
      <img src="/mefailogo.png" alt="MEFAI" style={{ height, width: height, borderRadius: 7, display: 'block' }} />
      <span style={{ fontWeight: 900, fontSize: height * 0.62, letterSpacing: '-.4px', color: dark ? '#fff' : 'var(--c-text)' }}>MEFAI</span>
    </span>
  )
}
