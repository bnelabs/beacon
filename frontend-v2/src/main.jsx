import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import { AppProviders } from './providers/AppProviders.jsx'

ReactDOM.createRoot(document.getElementById('root')).render(
  <AppProviders>
    <App />
  </AppProviders>
)
