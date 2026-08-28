import { createRoot } from "react-dom/client";
import App from "./App";
import { brand, brandLogo } from "./brand";
import "./styles.css";

document.title = brand.productName;
document.documentElement.lang = "zh-CN";
document.querySelector<HTMLMetaElement>('meta[name="description"]')?.setAttribute(
  "content",
  brand.description,
);
document.querySelector<HTMLLinkElement>('link[rel="icon"]')?.setAttribute(
  "href",
  brandLogo,
);

createRoot(document.getElementById("root")!).render(<App />);
