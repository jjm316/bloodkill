import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

// No StrictMode: its dev double-invoke would open the game socket twice.
ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
