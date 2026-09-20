import React from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import "./styles.css";
import { Shell } from "./components/Shell";
import { VocabProvider } from "./lib/vocab";
import { Dashboard } from "./pages/Dashboard";
import { Inbox } from "./pages/Inbox";
import { Detail } from "./pages/Detail";
import { Queue } from "./pages/Queue";
import { Proposals } from "./pages/Proposals";
import { Evaluation } from "./pages/Evaluation";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "inbox", element: <Inbox /> },
      { path: "queue", element: <Queue /> },
      { path: "proposals", element: <Proposals /> },
      { path: "evaluation", element: <Evaluation /> },
      { path: "records/:emailId", element: <Detail /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <VocabProvider>
      <RouterProvider router={router} />
    </VocabProvider>
  </React.StrictMode>,
);
