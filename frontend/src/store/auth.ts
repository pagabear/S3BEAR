import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { authApi, UserInfo } from '../api/auth'

// Single-flight guard: concurrent 401s must share one refresh call. Because the
// backend rotates the refresh token on every use, firing several refreshes in
// parallel would send an already-consumed token and log the user out. This
// promise lives outside the store so it is never persisted or serialized.
let refreshInFlight: Promise<boolean> | null = null

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: UserInfo | null
  isAuthenticated: boolean
  setTokens: (access: string, refresh: string) => void
  setUser: (user: UserInfo) => void
  logout: () => void
  refresh: () => Promise<boolean>
  loadUser: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,

      setTokens: (access, refresh) => {
        set({ accessToken: access, refreshToken: refresh, isAuthenticated: true })
      },

      setUser: (user) => set({ user }),

      logout: () => {
        set({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false })
      },

      refresh: async () => {
        // Coalesce concurrent refreshes into the one already in flight.
        if (refreshInFlight) return refreshInFlight

        refreshInFlight = (async () => {
          const { refreshToken } = get()
          if (!refreshToken) return false
          try {
            const res = await authApi.refresh(refreshToken)
            set({
              accessToken: res.data.access_token,
              refreshToken: res.data.refresh_token,
              isAuthenticated: true,
            })
            return true
          } catch {
            set({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false })
            return false
          }
        })()

        try {
          return await refreshInFlight
        } finally {
          refreshInFlight = null
        }
      },

      loadUser: async () => {
        try {
          const res = await authApi.me()
          set({ user: res.data })
        } catch {
          // token might be expired — handled by interceptor
        }
      },
    }),
    {
      name: 's3gw-auth',
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
)
