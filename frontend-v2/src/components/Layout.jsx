export function Shell({ header, children, sidebar }) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-bne-ice via-white to-bne-silver/30">
      <div className="flex min-h-screen flex-col">
        <header className="px-8 py-6">
          <div className="flex items-center justify-between rounded-3xl bg-white/70 px-8 py-5 shadow-bne-panel backdrop-blur-halo">
            {header}
          </div>
        </header>

        <main className="flex flex-1 flex-col gap-6 px-8 pb-10 lg:flex-row">
          <section className="flex-1 rounded-3xl bg-white/70 shadow-bne-panel backdrop-blur-halo">
            {children}
          </section>

          {sidebar ? (
            <aside className="w-full max-w-sm rounded-3xl bg-white/80 p-6 shadow-bne-panel backdrop-blur-halo">
              {sidebar}
            </aside>
          ) : null}
        </main>
      </div>
    </div>
  )
}
