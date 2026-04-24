import { Outlet } from "react-router-dom";
import { Toaster } from "sonner";
import { Nav } from "./components/Nav";

export default function App() {
  return (
    <>
      <Nav />
      <main
        style={{
          maxWidth: 1200,
          margin: "0 auto",
          padding: "1rem 1.25rem 3rem",
        }}
      >
        <Outlet />
      </main>
      <Toaster theme="dark" position="top-right" />
    </>
  );
}
