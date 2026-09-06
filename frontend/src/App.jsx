import React from "react";
import { BrowserRouter as Router, Routes, Route, useLocation } from "react-router-dom";
import Navbar from "./Components/Navbar/Navbar";
import Home from "./pages/Home";
import Signup from "./pages/Signup";
import Login from "./pages/Login";
import Profile from "./pages/Profile";
import VerifyOtp from "./pages/VerifyOtp";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import LawyerProfile from "./pages/LawyerProfile";
import LawyerDashboard from "./pages/LawyerDashboard";
import AdminDashboard from "./pages/AdminDashboard";
import LawyerConnect from "./pages/LawyerConnect";
import ChatList from "./pages/ChatList";
import Chat from "./pages/Chat";
import NotFound from "./pages/NotFound";
import ParticlesComponent from "./Components/Particles";
import ProtectedRoute from "./routes/ProtectedRoute";

function AppContent() {
  const location = useLocation();
  const hideNavbarRoutes = ['/login', '/signup', '/forgot-password', '/reset-password'];
  const shouldShowNavbar = !hideNavbarRoutes.includes(location.pathname);

  return (
    <div className="relative flex flex-col min-h-screen bg-background text-white" style={{ '--navbar-height': '4.5rem' }}>
      <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-b from-gray-900 via-gray-800 to-black opacity-60" style={{ zIndex: -2 }}></div>
      <div className="absolute top-0 left-1/2 transform -translate-x-1/2 w-3/4 h-3/4 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-blue-900/30 via-purple-900/20 to-transparent blur-3xl" style={{ zIndex: -1 }}></div>
      {shouldShowNavbar && <Navbar />}
      <div style={{ position: 'absolute', zIndex: -1, width: '100%', height: '100%', opacity: 0.4 }}>
        <ParticlesComponent id="tsparticles" />
      </div>
      <main className="flex-grow relative z-10" style={{ height: 'calc(100vh - var(--navbar-height))' }}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route
            path="/lawyer-connect"
            element={(
              <ProtectedRoute>
                <LawyerConnect />
              </ProtectedRoute>
            )}
          />
          <Route
            path="/lawyer-profile/:id"
            element={(
              <ProtectedRoute>
                <LawyerProfile />
              </ProtectedRoute>
            )}
          />
          <Route
            path="/lawyer-dashboard"
            element={(
              <ProtectedRoute>
                <LawyerDashboard />
              </ProtectedRoute>
            )}
          />
          <Route
            path="/admin-dashboard"
            element={(
              <ProtectedRoute>
                <AdminDashboard />
              </ProtectedRoute>
            )}
          />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/verify-otp" element={<VerifyOtp />} />
          <Route
            path="/profile"
            element={(
              <ProtectedRoute>
                <Profile />
              </ProtectedRoute>
            )}
          />
          <Route
            path="/chat"
            element={(
              <ProtectedRoute>
                <ChatList />
              </ProtectedRoute>
            )}
          />
          <Route
            path="/chat/:conversationId"
            element={(
              <ProtectedRoute>
                <Chat />
              </ProtectedRoute>
            )}
          />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  );
}

import { Toaster } from 'react-hot-toast';
import { AuthProvider } from './context/AuthContext';
import { GoogleOAuthProvider } from '@react-oauth/google';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

function App() {
  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <Router>
        <Toaster position="bottom-right" />
        <AuthProvider>
          <AppContent />
        </AuthProvider>
      </Router>
    </GoogleOAuthProvider>
  );
}

export default App;
