import { Route, Routes } from "react-router-dom";

import { AppLayout } from "@/components/app-layout";
import { HealthPage } from "@/pages/health-page";
import { HomePage } from "@/pages/home-page";
import { NotFoundPage } from "@/pages/not-found-page";

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="debug/health" element={<HealthPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
