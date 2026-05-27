import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import BusinessPerformanceDashboard from "./BusinessPerformanceDashboard.jsx";
import "./index.css";

const Root = window.location.pathname.startsWith("/business-performance-dashboard/")
  ? BusinessPerformanceDashboard
  : App;

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
