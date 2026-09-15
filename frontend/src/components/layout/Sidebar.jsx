import { cn } from '../../utils/cn'
import { useRouter } from '../../store/useRouter'

const iconProps = {
  fill: 'none',
  viewBox: '0 0 24 24',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  className: 'w-[18px] h-[18px]'
}

const groups = [
  {
    label: 'Monitor',
    items: [
      {
        name: 'Dashboard',
        page: 'dashboard',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
          </svg>
        )
      },
      {
        name: 'Risk Map',
        page: 'globe',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        )
      }
    ]
  },
  {
    label: 'Models',
    items: [
      {
        name: 'Models',
        page: 'models',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
        )
      },
      {
        name: 'Jobs',
        page: 'jobs',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )
      },
      {
        name: 'Performance',
        page: 'performance',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
        )
      }
    ]
  },
  {
    label: 'Data',
    items: [
      {
        name: 'Data Sources',
        page: 'datasources',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
          </svg>
        )
      },
      {
        name: 'Data Quality',
        page: 'data-quality',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
        )
      },
      {
        name: 'Country Profiles',
        page: 'countries',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
          </svg>
        )
      }
    ]
  },
  {
    label: 'Analysis',
    items: [
      {
        name: 'Results',
        page: 'results',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        )
      },
      {
        name: 'Analytics',
        page: 'analytics',
        icon: (
          <svg {...iconProps}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
          </svg>
        )
      }
    ]
  }
]

const secondaryNav = [
  {
    name: 'Settings',
    page: 'settings',
    icon: (
      <svg {...iconProps}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    )
  }
]

function NavButton({ item, active, onNavigate }) {
  return (
    <button
      key={item.name}
      onClick={() => onNavigate(item.page)}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative w-full flex items-center gap-2.5 pl-3 pr-2 py-[7px] rounded-r-md text-[13px] transition-colors text-left',
        active
          ? 'bg-bne-pine-50 text-bne-pine-700 font-semibold before:absolute before:left-0 before:top-1 before:bottom-1 before:w-[2.5px] before:rounded-r before:bg-bne-pine'
          : 'text-bne-muted font-medium hover:bg-bne-paper-dim hover:text-bne-ink border-l-[2.5px] border-transparent'
      )}
    >
      <span className={cn('shrink-0', active ? 'text-bne-pine' : 'text-bne-faint')}>
        {item.icon}
      </span>
      {item.name}
    </button>
  )
}

export default function Sidebar() {
  const { currentPage, navigate } = useRouter()

  return (
    <aside className="w-60 bg-bne-card border-r border-bne-line flex flex-col">
      <nav className="flex-1 px-2.5 pt-4 pb-2 overflow-y-auto">
        {groups.map((group, groupIndex) => (
          <div key={group.label} className={groupIndex > 0 ? 'mt-5' : undefined}>
            <p className="bne-micro px-3 mb-1.5">{group.label}</p>
            <div className="space-y-0.5 border-l border-bne-line-soft">
              {group.items.map((item) => (
                <NavButton
                  key={item.name}
                  item={item}
                  active={currentPage === item.page}
                  onNavigate={navigate}
                />
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-bne-line px-2.5 py-3">
        <div className="space-y-0.5 border-l border-bne-line-soft">
          {secondaryNav.map((item) => (
            <NavButton
              key={item.name}
              item={item}
              active={currentPage === item.page}
              onNavigate={navigate}
            />
          ))}
        </div>
        <p className="bne-micro mt-3 px-3 text-[9px] text-bne-faint/80">
          Systemic Liquidity Risk · v{__APP_VERSION__}
        </p>
      </div>
    </aside>
  )
}
