import { createContext, useContext } from "react";

import type { Field, Project } from "@/api/types";

export interface ProjectContextValue {
  project: Project;
  fields: Field[];
  /** Номер поля в проекте: он же подписан на карте и в списке приоритета. */
  indexOf: (fieldId: string) => number;
  refetchFields: () => void;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

export const ProjectProvider = ProjectContext.Provider;

export function useProjectContext(): ProjectContextValue {
  const value = useContext(ProjectContext);
  if (!value) {
    throw new Error("useProjectContext вызван вне ProjectLayout");
  }
  return value;
}
