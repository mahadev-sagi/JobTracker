import { Navigate, Routes, Route } from 'react-router-dom';
import Sidebar from './components/common/Sidebar';
import LoadingSpinner from './components/common/LoadingSpinner';
import { ToastProvider } from './components/common/Toast';
import { AuthProvider, useAuth } from './auth/AuthContext';
import Dashboard from './pages/Dashboard';
import Login from './pages/Login';
import Queue from './pages/Queue';
import Settings from './pages/Settings';

const AppRoutes = () => {
  const { user } = useAuth();

  if (user === undefined) {
    return (
      <div className="h-screen bg-gray-50 dark:bg-zinc-950">
        <LoadingSpinner />
      </div>
    );
  }

  if (user === null) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-zinc-950">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
};

function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </ToastProvider>
  );
}

export default App;
