import React, { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/Components/ui/button";
import { User, LogOut, Menu, X } from "lucide-react";
import { useAuth } from '../../context/AuthContext'; // Import useAuth

export default function Navbar() {
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const profileMenuRef = useRef(null);
  const { user, isAuthenticated, logout } = useAuth(); // Use AuthContext

  useEffect(() => {
    function handleClickOutside(event) {
      if (profileMenuRef.current && !profileMenuRef.current.contains(event.target)) {
        setShowProfileMenu(false);
      }
    }

    if (showProfileMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showProfileMenu]);

  const navLinks = [
    { to: "/", label: "Home" },
    { to: "/lawyer-connect", label: "Connect" },
    { to: "/chat", label: "Chat", requiresAuth: true },
  ];

  if (isAuthenticated && user?.role === 'lawyer') {
    navLinks.push({ to: "/lawyer-dashboard", label: "Lawyer Dashboard", requiresAuth: true });
  }
  if (isAuthenticated && user?.role === 'admin') {
    navLinks.push({ to: "/admin-dashboard", label: "Admin Dashboard", requiresAuth: true });
  }

  return (
    <nav className="bg-background/80 sticky top-0 z-50 border-b py-4 border-border shadow-lg shadow-black/20">
      <div className="container mx-auto px-5 h-full">
        <div className="flex items-center justify-between h-17">
          <Link to="/" className="text-3xl font-extrabold text-white hover:text-primary transition-colors duration-200 bg-gradient-to-r from-foreground to-primary bg-clip-text text-transparent">
            AdvocAI
          </Link>
          
          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center space-x-2">
            {navLinks.map((link, index) => (
              ((!link.requiresAuth) || isAuthenticated) && (
                <Link 
                  to={link.to} 
                  key={index} 
                  className="text-muted-foreground hover:text-foreground px-4 py-2 rounded-lg hover:bg-foreground/5 transition-all duration-200 relative group"
                >
                  {link.label}
                  <span className="absolute bottom-1 left-0 w-0 h-0.5 bg-primary group-hover:w-full transition-all duration-300"></span>
                </Link>
              )
            ))}
          </div>

          {/* Desktop Auth Section */}
          <div className="hidden md:flex items-center space-x-4">
            {isAuthenticated ? (
              <>
                <Link to="/profile">
                  <Button variant="ghost" className="hover:bg-foreground/5 rounded-full">
                    {user && user.profile_picture ? (
                      <img src={user.profile_picture} alt="Profile" className="w-9 h-8 rounded-full border-2 border-primary/50 hover:border-primary transition-colors" />
                    ) : (
                      <div className="w-9 h-8 rounded-full bg-primary/20 flex items-center justify-center border border-primary/30">
                        <User size={17} className="text-primary" />
                      </div>
                    )}
                  </Button>
                </Link>
                <Button 
                  onClick={logout} 
                  variant="outline" 
                  size="sm"
                  className="border-border hover:border-destructive hover:bg-destructive/10 hover:text-destructive transition-all duration-200"
                >
                  <LogOut size={15} className="mr-2" />
                  Logout
                </Button>
              </>
            ) : (
              <Link to="/login">
                <Button className="bg-gradient-to-r from-primary to-secondary hover:from-primary hover:to-secondary text-white shadow-md shadow-primary/30 hover:shadow-lg shadow-primary/40 transition-all duration-200">
                  Login
                </Button>
              </Link>
            )}
          </div>

          {/* Mobile Menu Button */}
          <div className="md:hidden flex items-center">
            <button 
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              className="p-3 rounded-lg hover:bg-foreground/10 transition-colors duration-200 text-muted-foreground hover:text-foreground"
              aria-label={isMenuOpen ? "Close menu" : "Open menu"}
            >
              {isMenuOpen ? <X size={23} /> : <Menu size={23} />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu Overlay and Sidebar */}
      {isMenuOpen && (
        <>
          {/* Overlay */}
          <div
            className="md:hidden fixed inset-0 bg-black/50 z-40 transition-opacity duration-300"
            onClick={() => setIsMenuOpen(false)}
          ></div>

                    {/* Sidebar Panel */}

                    <div className={`md:hidden fixed top-0 bottom-0 left-0 w-64 bg-background z-[51] flex flex-col items-start space-y-8 p-6 transition-transform duration-300 ease-in-out ${isMenuOpen ? 'translate-x-0' : '-translate-x-full'}`} style={{ height: 'calc(100vh - var(--navbar-height))', top: 'var(--navbar-height)' }}>
            <button
              onClick={() => setIsMenuOpen(false)}
              className="absolute  top-5 right-5 p-3 rounded-lg hover:bg-foreground/10 transition-colors duration-200 text-foreground"
            >
              <X size={24} />
            </button>
            <div className="flex flex-col space-y-4 pt-10 w-full"> {/* Added pt-10 for spacing from close button */}
              {navLinks.map((link, index) => (
                ((!link.requiresAuth) || isAuthenticated) && (
                  <Link 
                    to={link.to} 
                    key={index} 
                    className="text-xl font-bold text-foreground hover:text-primary transition-colors duration-200"
                    onClick={() => setIsMenuOpen(false)}
                  >
                    {link.label}
                  </Link>
                )
              ))}
              {isAuthenticated ? (
                <>
                  <Link to="/profile" className="text-xl font-bold text-foreground hover:text-primary transition-colors duration-200" onClick={() => setIsMenuOpen(false)}>
                    Profile
                  </Link>
                  <Button 
                    onClick={() => { logout(); setIsMenuOpen(false); }} 
                    variant="outline" 
                    size="lg"
                    className="border-border hover:border-destructive hover:bg-destructive/10 hover:text-destructive transition-all duration-200 text-xl font-bold w-full"
                  >
                    <LogOut size={20} className="mr-3" />
                    Logout
                  </Button>
                </>
              ) : (
                <Button
                  asChild
                  size="lg"
                  className="bg-gradient-to-r from-primary to-secondary hover:from-primary hover:to-secondary text-white shadow-md shadow-primary/30 hover:shadow-lg shadow-primary/40 transition-all duration-200 text-xl font-bold w-full"
                  onClick={() => setIsMenuOpen(false)}
                >
                  <Link to="/login">
                    Login
                  </Link>
                </Button>
              )}
            </div>
          </div>
        </>
      )}
    </nav>
  );
}
