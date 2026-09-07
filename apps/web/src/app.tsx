import { useState } from "react";
import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";

import { currentToken } from "@/auth/session";
import { AppLayout } from "@/components/app-layout";
import { HealthPage } from "@/pages/health-page";
import { HomePage } from "@/pages/home-page";
import { NotFoundPage } from "@/pages/not-found-page";
import { ReviewPage } from "@/pages/review-page";
import { ReviewsPage } from "@/pages/reviews-page";
import { SignInPage } from "@/pages/sign-in-page";

// Редактор правил тянет CodeMirror — это сотни килобайт, которые не нужны
// на пути «загрузить документ → получить замечания». Грузим отдельным куском,
// иначе главный сценарий платит за страницу, куда заходят изредка.
const ReviewPackEditorPage = lazy(() =>
  import("@/pages/review-pack-editor-page").then((module) => ({
    default: module.ReviewPackEditorPage,
  })),
);

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
        <Route path="reviews" element={<ReviewsPage />} />
        <Route path="reviews/:reviewId" element={<ReviewPage />} />
        <Route
          element={
            <Suspense
              fallback={
                <p className="mx-auto w-full max-w-3xl text-sm text-text-secondary">
                  Загружаем редактор правил
                </p>
              }
            >
              <ReviewPackEditorPage />
            </Suspense>
          }
          path="review-packs/:packId/edit"
        />
        <Route path="debug/health" element={<HealthPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
