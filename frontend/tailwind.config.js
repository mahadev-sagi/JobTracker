/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        status: {
          applied: '#3b82f6', // blue
          rejected: '#ef4444', // red
          offered: '#22c55e', // green
          interview: '#f59e0b', // amber
          unapplied: '#6b7280', // gray
          oa_received: '#8b5cf6', // purple
        }
      }
    },
  },
  plugins: [],
}
