import { Route, Routes } from "react-router-dom";

import { AppLayout } from "@/components/app-layout";
import { HealthPage } from "@/pages/health-page";
import { HomePage } from "@/pages/home-page";
import { NotFoundPage } from "@/pages/not-found-page";
import { ReviewPage } from "@/pages/review-page";
import { ResultsVisualFixturePage } from "@/pages/results-visual-fixture-page";

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="reviews/:reviewId" element={<ReviewPage />} />
        <Route path="debug/health" element={<HealthPage />} />
        {import.meta.env.DEV && (
          <Route path="debug/results-fixture" element={<ResultsVisualFixturePage />} />
        )}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
