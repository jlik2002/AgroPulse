import { Navigate, Route, Routes } from "react-router-dom";

import { ProjectIndexRedirect, ProjectLayout } from "@/app/ProjectLayout";
import { DataPage } from "@/pages/DataPage";
import { FarmPage } from "@/pages/FarmPage";
import { FarmsPage } from "@/pages/FarmsPage";
import { FieldPage } from "@/pages/FieldPage";
import { FieldsPage } from "@/pages/FieldsPage";
import { ForecastPage } from "@/pages/ForecastPage";
import { ProcessingPage } from "@/pages/ProcessingPage";
import { ReportsPage } from "@/pages/ReportsPage";
import { StartPage } from "@/pages/StartPage";
import { SummaryPage } from "@/pages/SummaryPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<StartPage />} />
      <Route path="/p/:projectId" element={<ProjectLayout />}>
        <Route index element={<ProjectIndexRedirect />} />
        <Route path="fields" element={<FieldsPage />} />
        <Route path="farms" element={<FarmsPage />} />
        <Route path="farm/:farmId" element={<FarmPage />} />
        <Route path="processing" element={<ProcessingPage />} />
        <Route path="summary" element={<SummaryPage />} />
        <Route path="data" element={<DataPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="field/:fieldId" element={<FieldPage />} />
        <Route path="field/:fieldId/forecast" element={<ForecastPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
