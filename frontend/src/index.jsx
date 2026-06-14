/**
 * Entry point for the MCP Server Dashboard React application.
 *
 * This file mounts the App component to the DOM.
 * It's imported and bundled by your build tool (Vite, Create React App, etc.).
 */

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
