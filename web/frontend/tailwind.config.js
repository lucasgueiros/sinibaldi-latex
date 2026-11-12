/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html", "./obra/**/*.py", "./obra/**/*.html", "./frontend/**/*.js", "./static/js/**/*.js"],
  theme: {
    extend: {
      colors: {
        crimson: { DEFAULT: "#8B1A1A", deep: "#5E1010", light: "#A83232" },
        gold: { DEFAULT: "#B08D57", dark: "#8A6A3B", light: "#D9BF8C" },
        parchment: { DEFAULT: "#F6EFE0", light: "#FBF7EE", dark: "#EDE2CB" },
        ink: "#2A1F1A",
      },
      fontFamily: {
        display: ['"Cinzel"', '"Trajan Pro"', "Georgia", "serif"],
        serif: ['"EB Garamond"', "Garamond", "Georgia", "serif"],
      },
    },
  },
  plugins: [],
};
