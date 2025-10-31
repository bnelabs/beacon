export function Shell({ header, children, sidebar }) {
  return (
    <div className="min-h-screen w-full bg-gradient-to-br from-bne-ice via-white to-bne-silver/30">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-2 sm:px-0">
        <header className="px-4 py-5 sm:px-6 lg:px-8 lg:py-6">
          <div className="flex flex-col gap-4 rounded-3xl bg-white/70 px-6 py-5 shadow-bne-panel backdrop-blur-halo sm:flex-row sm:items-center sm:justify-between lg:px-8">
            {header}
          </div>
        </header>

        <main className="flex flex-1 flex-col gap-6 px-4 pb-12 sm:px-6 lg:flex-row lg:items-start lg:px-8">
          <section className="flex-1 rounded-3xl bg-white/70 p-4 shadow-bne-panel backdrop-blur-halo sm:p-6 lg:p-8">
            {children}
          </section>

          {sidebar ? (
            <aside className="w-full rounded-3xl bg-white/80 p-6 shadow-bne-panel backdrop-blur-halo sm:p-7 lg:max-w-sm">
              {sidebar}
            </aside>
          ) : null}
        </main>
      </div>
    </div>
  )
}
