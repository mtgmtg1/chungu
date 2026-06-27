// [Flow: Step 1 (런타임 도메인 기반 URL 생성) -> Step 2 (Supabase client 생성)]
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = `${window.location.origin}/supabase`
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || ''

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    autoRefreshToken: true,
    persistSession: true,
  },
})
