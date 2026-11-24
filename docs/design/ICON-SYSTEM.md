# AutoTramita — Icon system
Date: 2026-11-24. Status: design specification for review; no implementation.
Parent: [Brand identity](BRAND-IDENTITY.md), AT-18, ADR-001/008.
Use Lucide outline icons via named imports from lucide-react in Next.js; verify exports against pinned version before implementation. Flutter should map equivalent glyphs through a compatible licensed library. Preserve upstream ISC license notices. No custom copies of the 50 SVGs required.

## Vehicles and business

| # | Lucide identifier | React export | Spanish label |
|---|---|---|---|
| 1 | `car-front` | `CarFront` | Vehículos |
| 2 | `truck` | `Truck` | Transporte |
| 3 | `key-round` | `KeyRound` | Llaves |
| 4 | `arrow-left-right` | `ArrowLeftRight` | Cambio de titularidad |
| 5 | `clipboard-check` | `ClipboardCheck` | ITV |
| 6 | `building-2` | `Building2` | Concesionarios |
| 7 | `users` | `Users` | Clientes |
| 8 | `user-round` | `UserRound` | Titular |
| 9 | `briefcase-business` | `BriefcaseBusiness` | Colaboradores |
| 10 | `globe` | `Globe` | Importación |

## Documents and cases

| # | Lucide identifier | React export | Spanish label |
|---|---|---|---|
| 11 | `folder-open` | `FolderOpen` | Expedientes |
| 12 | `file-text` | `FileText` | Documentos |
| 13 | `file-check` | `FileCheck` | Documentos verificados |
| 14 | `file-plus` | `FilePlus` | Nueva solicitud |
| 15 | `files` | `Files` | Duplicados |
| 16 | `upload` | `Upload` | Subir documentos |
| 17 | `download` | `Download` | Descargar |
| 18 | `signature` | `Signature` | Firma |
| 19 | `scan-line` | `ScanLine` | Escanear |
| 20 | `search` | `Search` | Buscar |

## Finance

| # | Lucide identifier | React export | Spanish label |
|---|---|---|---|
| 21 | `credit-card` | `CreditCard` | Pago con tarjeta |
| 22 | `wallet` | `Wallet` | Saldo |
| 23 | `receipt` | `Receipt` | Facturas y recibos |
| 24 | `calculator` | `Calculator` | Impuestos |
| 25 | `euro` | `Euro` | Importes |
| 26 | `landmark` | `Landmark` | Banco |
| 27 | `percent` | `Percent` | Descuentos |
| 28 | `chart-pie` | `ChartPie` | Análisis |
| 29 | `chart-no-axes-combined` | `ChartNoAxesCombined` | Estadísticas |
| 30 | `coins` | `Coins` | Tasas |

## Security and states

| # | Lucide identifier | React export | Spanish label |
|---|---|---|---|
| 31 | `shield-check` | `ShieldCheck` | Seguridad |
| 32 | `lock-keyhole` | `LockKeyhole` | Acceso protegido |
| 33 | `fingerprint` | `Fingerprint` | Identidad |
| 34 | `circle-check` | `CircleCheck` | Finalizado |
| 35 | `clock` | `Clock` | Pendiente |
| 36 | `loader-circle` | `LoaderCircle` | En tramitación |
| 37 | `circle-alert` | `CircleAlert` | Atención |
| 38 | `circle-x` | `CircleX` | Rechazado |
| 39 | `history` | `History` | Historial |
| 40 | `eye` | `Eye` | Ver |

## Navigation and communication

| # | Lucide identifier | React export | Spanish label |
|---|---|---|---|
| 41 | `layout-dashboard` | `LayoutDashboard` | Panel |
| 42 | `menu` | `Menu` | Menú |
| 43 | `settings` | `Settings` | Configuración |
| 44 | `bell` | `Bell` | Notificaciones |
| 45 | `mail` | `Mail` | Correo electrónico |
| 46 | `message-circle` | `MessageCircle` | Mensajes |
| 47 | `headset` | `Headset` | Soporte |
| 48 | `calendar-days` | `CalendarDays` | Calendario |
| 49 | `log-out` | `LogOut` | Cerrar sesión |
| 50 | `languages` | `Languages` | Idiomas |

## Usage
16px inline/table, 20px navigation, 24px standard actions, 32px feature cards; 2px nominal stroke on 24-unit viewBox, currentColor, consistent alignment. Brand blue #005BCB on light, #60A5FA on dark; secondary slate #475569 on light. Status text/icon combinations use accessible semantic colors from brand identity. Never infer authorization or payment completion from an icon. Pair status with text, use aria-hidden for decorative icons and accessible Spanish names for icon-only buttons; tooltip is supplemental. Minimum interactive target 24 CSS px (prefer 44px on touch). Respect reduced motion for loader; announce loading state without repetitive live updates. Icons are not a substitute for official marks or service catalog. Additional UI primitives may use Lucide beyond this core catalog. Review contrast, keyboard focus, RTL if introduced, and bundle tree-shaking. No dependencies installed.
