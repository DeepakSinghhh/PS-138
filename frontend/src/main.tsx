import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { CurrencyProvider } from "./lib/currency";
import { LangProvider } from "./lib/i18n";
import { SavedPlansProvider } from "./lib/saved";
import { StoreProvider } from "./lib/store";
import "@fontsource-variable/archivo/standard.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-ext-400.css";
import "@fontsource-variable/noto-sans-devanagari/wght.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <LangProvider>
      <StoreProvider>
        <CurrencyProvider>
          <SavedPlansProvider>
            <App />
          </SavedPlansProvider>
        </CurrencyProvider>
      </StoreProvider>
      </LangProvider>
    </BrowserRouter>
  </StrictMode>,
);
