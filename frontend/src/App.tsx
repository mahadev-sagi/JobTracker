import { Routes, Route } from 'react-router-dom';
import Sidebar from './components/common/Sidebar';
import { ToastProvider } from './components/common/Toast';
import Dashboard from './pages/Dashboard';
import Queue from './pages/Queue';

function App() {
  return (
    <ToastProvider>
      <div className="flex h-screen bg-gray-50 dark:bg-zinc-950">
        <Sidebar />
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/queue" element={<Queue />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}

export default App;
