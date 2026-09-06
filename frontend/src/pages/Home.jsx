"use client"

import { ArrowRight, Shield, MessageSquare, Star, Users, Sparkles } from "lucide-react"
import { Button } from "@/Components/ui/button"
import { Link } from "react-router-dom"
import React, { Suspense } from "react"
import { useAuth } from '../context/AuthContext'

const Subtle3DBackground = React.lazy(() => import("../Components/Subtle3DBackground.jsx"))

export default function Home() {
  const { isAuthenticated } = useAuth()

  return (
    <div className="min-h-screen bg-background text-foreground overflow-hidden relative">
      <div className="fixed inset-0 z-0 opacity-40 pointer-events-none">
        <Suspense fallback={null}>
          <Subtle3DBackground />
        </Suspense>
      </div>

      <div className="relative z-10">
        <section className="relative overflow-hidden py-20 md:py-32">
          <div className="absolute inset-0 overflow-hidden">
            <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary/20 rounded-full blur-3xl animate-float"></div>
            <div
              className="absolute -bottom-20 -left-40 w-80 h-80 bg-secondary/20 rounded-full blur-3xl animate-float"
              style={{ animationDelay: "2s" }}
            ></div>
          </div>

          <div className="relative w-full px-4 sm:px-6 lg:px-8">
            <div className="grid md:grid-cols-2 gap-12 items-center">
              <div className="space-y-6 z-10">
                <div className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-primary to-secondary border border-primary/20 rounded-full">
                  <Sparkles className="w-4 h-4 text-primary" />
                  <span className="text-sm font-bold text-white">Legal Connection Platform</span>
                </div>
                <h1 className="text-5xl md:text-6xl font-black leading-tight text-balance">
                  Connect with
                  <span className="block bg-gradient-to-r from-primary via-purple-500 to-secondary bg-clip-text text-transparent">
                    Expert Lawyers
                  </span>
                </h1>
                <p className="text-lg text-muted-foreground leading-relaxed max-w-lg">
                  Find verified legal professionals, request consultations, chat in real-time,
                  join Google Meet sessions, and share feedback through ratings.
                </p>
                <div className="flex flex-col sm:flex-row gap-4 pt-4">
                  {isAuthenticated ? (
                    <>
                      <Button
                        size="lg"
                        className="gap-2 bg-gradient-to-r from-primary to-secondary hover:shadow-lg hover:shadow-primary/50 text-white font-bold text-base px-8"
                        asChild
                      >
                        <Link to="/lawyer-connect">
                          Find a Lawyer <ArrowRight className="w-5 h-5" />
                        </Link>
                      </Button>
                      <Button
                        size="lg"
                        variant="outline"
                        className="border-2 border-muted-foreground/30 font-bold text-base px-8 bg-transparent"
                        asChild
                      >
                        <Link to="/chat">Messages</Link>
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        size="lg"
                        className="gap-2 bg-gradient-to-r from-primary to-secondary hover:shadow-lg hover:shadow-primary/50 text-white font-bold text-base px-8"
                        asChild
                      >
                        <Link to="/signup">
                          Sign Up <ArrowRight className="w-5 h-5" />
                        </Link>
                      </Button>
                      <Button
                        size="lg"
                        variant="outline"
                        className="border-2 border-muted-foreground/30 font-bold text-base px-8 bg-transparent"
                        asChild
                      >
                        <Link to="/login">Sign In</Link>
                      </Button>
                    </>
                  )}
                </div>
              </div>

              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-br from-primary/20 to-secondary/20 rounded-2xl blur-xl"></div>
                <div className="relative bg-gradient-to-br from-primary/5 to-secondary/5 rounded-2xl p-1 border border-primary/30">
                  <div className="bg-card rounded-xl overflow-hidden border border-primary/10 p-8 space-y-4">
                    <div className="flex items-center gap-3 pb-4 border-b border-primary/20">
                      <div className="w-10 h-10 bg-gradient-to-br from-primary to-secondary rounded-lg flex items-center justify-center">
                        <Users className="w-6 h-6 text-white" />
                      </div>
                      <span className="font-bold text-lg">How It Works</span>
                    </div>
                    <div className="space-y-3">
                      <div className="flex items-center gap-3 p-3 bg-primary/5 rounded-lg border border-primary/10">
                        <Shield className="w-5 h-5 text-primary flex-shrink-0" />
                        <span className="text-sm font-medium">Browse verified lawyer profiles</span>
                      </div>
                      <div className="flex items-center gap-3 p-3 bg-secondary/5 rounded-lg border border-secondary/10">
                        <MessageSquare className="w-5 h-5 text-secondary flex-shrink-0" />
                        <span className="text-sm font-medium">Connect, chat, and join Google Meet</span>
                      </div>
                      <div className="flex items-center gap-3 p-3 bg-primary/5 rounded-lg border border-primary/10">
                        <Star className="w-5 h-5 text-primary flex-shrink-0" />
                        <span className="text-sm font-medium">Rate your consultation experience</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <footer className="border-t border-border relative">
          <div className="w-full px-4 sm:px-6 lg:px-8 py-16 relative z-10">
            <div className="text-center">
              <p className="text-xs text-muted-foreground">Empowering Justice through Legal Connections.</p>
            </div>
          </div>
        </footer>
      </div>
    </div>
  )
}
