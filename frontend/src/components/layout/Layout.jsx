import Header from './Header'
import Sidebar from './Sidebar'
import GlobalSearch from '../GlobalSearch'

export default function Layout({ children }) {
  return (
    <div className="flex h-screen bg-bne-ice overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
      <GlobalSearch />
    </div>
  )
}
