import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { CurrencyProvider } from "./lib/currency";
import { StoreProvider } from "./lib/store";
import "@fontsource-variable/plus-jakarta-sans/wght.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <StoreProvider>
        <CurrencyProvider>
          <App />
        </CurrencyProvider>
      </StoreProvider>
    </BrowserRouter>
  </StrictMode>,
);
