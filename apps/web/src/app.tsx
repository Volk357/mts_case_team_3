import { useState } from "react";
import { Route, Routes } from "react-router-dom";

import { currentToken } from "@/auth/session";
import { AppLayout } from "@/components/app-layout";
import { ArchitecturePage } from "@/pages/architecture-page";
import { HealthPage } from "@/pages/health-page";
import { HomePage } from "@/pages/home-page";
import { NotFoundPage } from "@/pages/not-found-page";
import { ReviewPage } from "@/pages/review-page";
import { ReviewsPage } from "@/pages/reviews-page";
import { SignInPage } from "@/pages/sign-in-page";

export function App() {
  // Учётные данные живут во вкладке: вернулись на страницу — вход сохранился,
  // закрыли вкладку — доступ закончился.
  const [signedIn, setSignedIn] = useState(() => currentToken() !== null);

  if (!signedIn) {
    return <SignInPage onSignedIn={() => setSignedIn(true)} />;
  }

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="architecture" element={<ArchitecturePage />} />
        <Route path="reviews" element={<ReviewsPage />} />
        <Route path="reviews/:reviewId" element={<ReviewPage />} />
        <Route path="debug/health" element={<HealthPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
