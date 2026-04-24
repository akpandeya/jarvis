import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "./App";
import Upcoming from "./pages/Upcoming";
import Timeline from "./pages/Timeline";
import Search from "./pages/Search";
import Summary from "./pages/Summary";
import Sessions from "./pages/Sessions";
import Insights from "./pages/Insights";
import Chat from "./pages/Chat";
import Prs from "./pages/Prs";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/upcoming" replace /> },
      { path: "upcoming", element: <Upcoming /> },
      { path: "timeline", element: <Timeline /> },
      { path: "search", element: <Search /> },
      { path: "summary", element: <Summary /> },
      { path: "sessions", element: <Sessions /> },
      { path: "insights", element: <Insights /> },
      { path: "chat", element: <Chat /> },
      { path: "prs", element: <Prs /> },
      { path: "*", element: <Navigate to="/upcoming" replace /> },
    ],
  },
]);
